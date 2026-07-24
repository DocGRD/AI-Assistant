// LoreMaster — the approximation / alignment engine.
//
// A pasted translation (ESV, NASB, WEB…) has no original-language links. This engine GUESSES them by
// projecting the pasted English onto translations we already have Strong's for — the "anchors": the BSB
// reverse-interlinear reading notes, the unfoldingWord ULT (AI/bible-ult), and the KJV+Strong's data. All
// three are English, cover the same verse, and largely share word order, so aligning them to the pasted
// verse is a MONOLINGUAL alignment (no statistical MT, no model, fully offline). Each anchor votes on a
// word's Strong's number; agreement + match quality give a confidence. The guesses are stored as a
// sidecar overlay (AI/bible-guess/{version}/{book}.json) and rendered as clearly-marked *approximate*
// tags; the reader lets you confirm / change / reject each, and those decisions live in the note's
// frontmatter (portable, user-owned) — see registerBibleStrongsOverlay in bible-strongs.ts.

import { Plugin, TFile, Notice, Modal, MarkdownView } from "obsidian";
import { BOOK_NUM, pad2, pad3, bookLabel } from "./bible";

export const GUESS_DIR = "AI/bible-guess";

// A LINK: the run of `n` English words starting at word index `w` that render ONE original-language word.
// n is 1 for the common case; it is >1 when a single Greek/Hebrew word takes several English words
// ("ἐν ἀρχῇ" → "In the beginning"). English words with no original counterpart (supplied for clarity)
// simply get no link at all.
export type GuessWord = { w: number; n?: number; s: string; c: number };
export type GuessChapter = Record<string, GuessWord[]>;          // "book.ch.v" -> links

// ── English light stemmer (symmetric-ish: loved/love → "lov", heavens/heaven, beginning/begin) ──
function stem(word: string): string {
    let s = word.toLowerCase().replace(/[^a-z]+/g, "");
    if (s.length <= 3) return s;
    s = s.replace(/'?s$/, "");
    s = s.replace(/(ings?|edly|eth|est|ed)$/, "");
    s = s.replace(/ies$/, "y");
    s = s.replace(/es$/, "");
    s = s.replace(/s$/, "");
    s = s.replace(/([bcdfghjklmnpqrstvwxz])\1$/, "$1");   // beginn -> begin
    s = s.replace(/e$/, "");                              // love/gave -> lov/gav
    return s || word.toLowerCase().replace(/[^a-z]+/g, "");
}
const STOP = new Set(["the", "a", "an", "of", "and", "to", "in", "is", "was", "for", "with", "that",
    "this", "he", "she", "it", "they", "them", "his", "her", "their", "him", "you", "your", "we", "us",
    "not", "but", "as", "be", "are", "were", "on", "at", "by", "or", "so", "then", "which", "who"]);

/** Tokenise a verse body the SAME way the reader does — the verse number is already removed, so split the
 *  visible text on whitespace. Returns raw tokens (indices match the overlay's word index). */
function tokenizeVerse(body: string): string[] {
    return decodeEntities(body.replace(/<[^>]+>/g, "")).split(/\s+/).filter(Boolean);
}

/** Extract each verse of a chapter note as { verse, body } — MULTI-LINE aware. A poetry verse whose stichs
 *  span several lines (`**1** …rage⏎ and …vain? ^v1`) is gathered into one body, so it aligns like prose.
 *  The reader renders those stichs into a single verse <p> (with <br>s), so a whitespace tokenise of `body`
 *  yields the same words + indices the overlay uses. */
function versesFromMd(md: string): { verse: string; body: string }[] {
    const out: { verse: string; body: string }[] = [];
    let cur: { verse: string; parts: string[] } | null = null;
    for (const line of md.split(/\r?\n/)) {   // tolerate CRLF — a stray \r breaks the `(.*)$` start match
        const start = line.match(/^\*\*(\d+)\*\*[ \t]*(.*)$/);
        if (start) cur = { verse: start[1], parts: [start[2]] };
        else if (cur) cur.parts.push(line);
        if (cur && new RegExp(`\\^v${cur.verse}\\b`).test(line)) {
            const body = cur.parts.join(" ").replace(new RegExp(`[ \\t]*\\^v${cur.verse}\\b.*$`), "").trim();
            out.push({ verse: cur.verse, body });
            cur = null;
        }
    }
    return out;
}
function decodeEntities(s: string): string {
    return s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#39;|&rsquo;|&apos;/g, "'");
}
const clean = (t: string): string => t.toLowerCase().replace(/^[^a-z0-9']+|[^a-z0-9']+$/g, "");

// ── anchor loading (cached per book) ────────────────────────────────────────
// `og` identifies the ORIGINAL word this English word renders (anchor-scoped). Several consecutive
// English words sharing an og came from ONE Greek/Hebrew word, and are merged into one link.
type RefWord = { w: string; s: string; og: string };
type RefVerse = RefWord[];
type Gloss = Record<string, { g?: string; d?: string }>;

class Anchors {
    private cache = new Map<string, Promise<any>>();
    constructor(private plugin: Plugin) {}
    private read<T>(path: string, fallback: T): Promise<T> {
        let p = this.cache.get(path);
        if (!p) { p = this.plugin.app.vault.adapter.read(path).then(s => JSON.parse(s)).catch(() => fallback); this.cache.set(path, p); }
        return p as Promise<T>;
    }
    ult(book: string) { return this.read<Record<string, { e: string; s: string; g?: number }[]>>(`AI/bible-ult/${book}.json`, {}); }
    kjv(book: string) { return this.read<Record<string, [string, string[]][]>>(`AI/bible-strongs/${book}.json`, {}); }
    words() { return this.read<Record<string, string[]>>(`AI/bible-strongs/_words.json`, {}); }
    glossH() { return this.read<Gloss>(`AI/bible-strongs/_lexicon-H.json`, {}); }
    glossG() { return this.read<Gloss>(`AI/bible-strongs/_lexicon-G.json`, {}); }
    /** BSB reading note, parsed per verse into English-order (word, Strong's). */
    private bsbNoteCache = new Map<string, Promise<Record<string, RefVerse>>>();
    bsbNote(book: string, chapter: number): Promise<Record<string, RefVerse>> {
        const num = BOOK_NUM[book];
        const path = `bible/${pad2(num)}-${book}/bsb/${book}-${pad3(chapter)}.md`;
        let p = this.bsbNoteCache.get(path);
        if (!p) {
            p = this.plugin.app.vault.adapter.read(path).then(parseBsbNote).catch(() => ({}));
            this.bsbNoteCache.set(path, p);
        }
        return p;
    }
}

/** Parse a BSB reading note into { "book.ch.v": [{w, s}] } — words in English order, each with its tag. */
function parseBsbNote(md: string): Record<string, RefVerse> {
    const out: Record<string, RefVerse> = {};
    const book = (md.match(/bible-book:\s*(\S+)/) || [])[1];
    const chapter = (md.match(/bible-chapter:\s*(\d+)/) || [])[1];
    if (!book || !chapter) return out;
    for (const line of md.split("\n")) {
        const m = line.match(/^\*\*(\d+)\*\*\s+(.*?)\s*\^v\1\s*$/);
        if (!m) continue;
        const verse = m[1];
        const words: RefVerse = [];
        const re = /<span class="lm-s" data-s="([^"]+)">([^<]*)<\/span>|([^<]+)/g;
        let mm: RegExpExecArray | null;
        let span = 0;
        while ((mm = re.exec(m[2]))) {
            if (mm[1]) {
                // one tagged span = ONE original word, however many English words it took ("Can he")
                const og = `b${++span}`;
                for (const w of decodeEntities(mm[2]).split(/\s+/).filter(Boolean)) words.push({ w, s: mm[1], og });
            } else {
                for (const w of decodeEntities(mm[3]).replace(/<[^>]+>/g, "").split(/\s+/).filter(Boolean)) words.push({ w, s: "", og: "" });
            }
        }
        if (words.length) out[`${book}.${chapter}.${verse}`] = words;
    }
    return out;
}

// ── Needleman–Wunsch monotonic alignment of pasted tokens ↔ an anchor's English-order words ──
function glossStems(g: Gloss, strong: string): Set<string> {
    const e = g[strong];
    const set = new Set<string>();
    if (!e) return set;
    for (const src of [e.g, e.d]) if (src) for (const w of src.toLowerCase().split(/[^a-z]+/)) if (w.length > 2) set.add(stem(w));
    return set;
}
function sim(xStem: string, rWord: string, rStrong: string, gloss: Gloss): number {
    const rs = stem(rWord);
    if (!xStem || !rs) return 0;
    if (xStem === rs) return 1;
    if (xStem.length >= 4 && rs.length >= 4 && (xStem.startsWith(rs) || rs.startsWith(xStem))) return 0.7;
    if (rStrong && glossStems(gloss, rStrong).has(xStem)) return 0.45;   // synonym via the lexicon gloss
    return 0;
}

/** Align pasted cleaned tokens X to an anchor reference R; return, per X index, the projected Strong's +
 *  sim + the original-word group it came from (so a run rendering one original word can be merged). */
function alignTo(X: string[], R: RefVerse, gloss: Gloss): ({ s: string; sim: number; og: string } | null)[] {
    const n = X.length, m = R.length;
    const GAP = -0.3;
    const xStems = X.map(stem);
    const S: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = 1; i <= n; i++) S[i][0] = i * GAP;
    for (let j = 1; j <= m; j++) S[0][j] = j * GAP;
    for (let i = 1; i <= n; i++) for (let j = 1; j <= m; j++) {
        const d = S[i - 1][j - 1] + sim(xStems[i - 1], R[j - 1].w, R[j - 1].s, gloss);
        S[i][j] = Math.max(d, S[i - 1][j] + GAP, S[i][j - 1] + GAP);
    }
    const out: ({ s: string; sim: number; og: string } | null)[] = new Array(n).fill(null);
    let i = n, j = m;
    while (i > 0 && j > 0) {
        const sm = sim(xStems[i - 1], R[j - 1].w, R[j - 1].s, gloss);
        if (S[i][j] === S[i - 1][j - 1] + sm) {
            if (sm > 0 && R[j - 1].s) out[i - 1] = { s: R[j - 1].s, sim: sm, og: R[j - 1].og };
            i--; j--;
        } else if (S[i][j] === S[i - 1][j] + GAP) { i--; } else { j--; }
    }
    return out;
}

/** Align one chapter of a pasted version; returns the guesses and (unless dryRun) writes the sidecar. */
export async function alignChapter(plugin: Plugin, book: string, version: string, chapter: number,
                                   opts: { dryRun?: boolean } = {}): Promise<GuessChapter> {
    const num = BOOK_NUM[book];
    if (!num) return {};
    const notePath = `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(chapter)}.md`;
    const md = await plugin.app.vault.adapter.read(notePath).catch(() => "");
    if (!md) return {};

    const A = new Anchors(plugin);
    const [ult, kjv, bsbNote, prior] = await Promise.all([A.ult(book), A.kjv(book), A.bsbNote(book, chapter), A.words()]);
    const gloss = book && BOOK_NUM[book] >= 40 ? await A.glossG() : await A.glossH();

    const kjvVerse = (key: string): RefVerse => {
        const out: RefVerse = [];
        let g = 0;
        for (const [phrase, strongs] of kjv[key] || []) {
            const s = (strongs || [])[0] || "";
            const og = `k${++g}`;                       // one KJV phrase entry = one original word
            for (const w of String(phrase).split(/\s+/).filter(Boolean)) out.push({ w, s, og });
        }
        return out;
    };
    const ultVerse = (key: string): RefVerse =>
        (ult[key] || []).map(x => ({ w: x.e, s: x.s, og: x.g != null ? `u${x.g}` : "" }));

    const result: GuessChapter = {};
    for (const { verse, body } of versesFromMd(md)) {
        const key = `${book}.${chapter}.${verse}`;
        const X = tokenizeVerse(body).map(clean);
        if (!X.some(Boolean)) continue;

        // Each anchor projects a Strong's onto each pasted word; collect the votes.
        const anchors: { name: string; proj: ({ s: string; sim: number; og: string } | null)[] }[] = [];
        for (const [name, R] of [["ult", ultVerse(key)], ["bsb", bsbNote[key] || []], ["kjv", kjvVerse(key)]] as [string, RefVerse][])
            if (R.length) anchors.push({ name, proj: alignTo(X, R, gloss) });
        if (!anchors.length) continue;

        // Pass 1 — per English word, the winning Strong's + which original word EACH anchor thinks it
        // came from (anchors segment phrases differently, so we keep them all and merge on any agreement).
        type Pick = { s: string; c: number; ogs: Record<string, string> };
        const picks: (Pick | null)[] = new Array(X.length).fill(null);
        for (let i = 0; i < X.length; i++) {
            if (!X[i]) continue;
            const votes = new Map<string, { simSum: number; names: Set<string> }>();
            for (const a of anchors) {
                const p = a.proj[i];
                if (!p || !p.s) continue;
                const v = votes.get(p.s) || { simSum: 0, names: new Set() };
                v.simSum += p.sim; v.names.add(a.name); votes.set(p.s, v);
            }
            if (!votes.size) continue;              // no anchor links this word — supplied for clarity
            let best = ""; let bestScore = -1; let bestAgree = 0; let bestAvg = 0;
            for (const [s, v] of votes) {
                const score = v.names.size * 10 + v.simSum;
                if (score > bestScore) { bestScore = score; best = s; bestAgree = v.names.size; bestAvg = v.simSum / v.names.size; }
            }
            if (!best) continue;
            let c = bestAvg * (0.55 + 0.45 * Math.min(bestAgree, 3) / 3);
            if ((prior[X[i]] || []).includes(best)) c = Math.min(1, c + 0.12);   // global head-word prior agrees
            if (STOP.has(X[i]) && bestAgree < 2) c *= 0.8;                        // be humbler on function words
            c = Math.round(Math.min(1, Math.max(0, c)) * 100) / 100;
            if (c < 0.2) continue;
            // Record, per anchor that backed the winner, which original word it assigned this English word to.
            const ogs: Record<string, string> = {};
            for (const a of anchors) { const p = a.proj[i]; if (p && p.s === best && p.og) ogs[a.name] = p.og; }
            picks[i] = { s: best, c, ogs };
        }

        // Pass 2 — merge a RUN of adjacent English words that render the SAME original word into one link
        // ("In the beginning" → H7225, "he gave" → G1325). Two neighbours belong together when they share a
        // Strong's AND at least one anchor puts them on the same original word. Chaining across neighbours
        // lets a 3+ word phrase form even when different anchors segment it differently. Words no anchor
        // links at all get no link — those are the ones supplied in English for clarity.
        const sameOriginal = (p: Pick, q: Pick): boolean =>
            p.s === q.s && Object.keys(p.ogs).some(k => q.ogs[k] && q.ogs[k] === p.ogs[k]);
        const words: GuessWord[] = [];
        for (let i = 0; i < picks.length; i++) {
            const p = picks[i];
            if (!p) continue;
            let j = i; const cs = [p.c];
            while (j + 1 < picks.length) {
                const q = picks[j + 1];
                if (!q || !sameOriginal(picks[j]!, q)) break;
                cs.push(q.c); j++;
            }
            const n = j - i + 1;
            const c = Math.round((cs.reduce((a, b) => a + b, 0) / cs.length) * 100) / 100;
            words.push(n > 1 ? { w: i, n, s: p.s, c } : { w: i, s: p.s, c });
            i = j;
        }
        if (words.length) result[key] = words;
    }

    if (!opts.dryRun) await writeGuessSidecar(plugin, version, book, chapter, result);
    return result;
}

// ── sidecar (computed guesses) read/write, per book, merged across chapters ──
export async function loadGuessSidecar(plugin: Plugin, version: string, book: string): Promise<GuessChapter> {
    return plugin.app.vault.adapter.read(`${GUESS_DIR}/${version}/${book}.json`).then(s => JSON.parse(s)).catch(() => ({}));
}
async function writeGuessSidecar(plugin: Plugin, version: string, book: string, chapter: number, chapterGuesses: GuessChapter): Promise<void> {
    const dir = `${GUESS_DIR}/${version}`;
    try { await plugin.app.vault.adapter.mkdir(dir); } catch { /* exists */ }
    const existing = await loadGuessSidecar(plugin, version, book);
    for (const k of Object.keys(existing)) if (k.startsWith(`${book}.${chapter}.`)) delete existing[k];  // replace this chapter
    Object.assign(existing, chapterGuesses);
    await plugin.app.vault.adapter.write(`${dir}/${book}.json`, JSON.stringify(existing));
}

// ── user decisions (confirm / edit / reject) → note frontmatter (portable) ───
export type Decisions = {
    confirmed: Map<string, string>;   // "v:w" -> strong   (accept the guess as-is)
    edited: Map<string, string>;      // "v:w" -> strong   (replace with a corrected number)
    rejected: Set<string>;            // "v:w"             (this word has no original / wrong)
};
export function readDecisions(fm: any): Decisions {
    const pair = (arr: any): [string, string][] =>
        (Array.isArray(arr) ? arr : []).map(String).map(s => { const m = s.match(/^(\d+:\d+):(.+)$/); return m ? [m[1], m[2]] as [string, string] : null; }).filter(Boolean) as [string, string][];
    return {
        confirmed: new Map(pair(fm?.["bible-strongs-confirmed"])),
        edited: new Map(pair(fm?.["bible-strongs-edited"])),
        rejected: new Set((Array.isArray(fm?.["bible-strongs-rejected"]) ? fm["bible-strongs-rejected"] : []).map(String)),
    };
}
/** Record a decision for verse:word. kind "confirm"/"edit" carry a Strong's; "reject" and "clear" don't. */
export async function writeDecision(plugin: Plugin, notePath: string, verse: number, wordIndex: number,
                                    kind: "confirm" | "edit" | "reject" | "clear", strong = ""): Promise<void> {
    const file = plugin.app.vault.getAbstractFileByPath(notePath);
    if (!(file instanceof TFile)) return;
    const id = `${verse}:${wordIndex}`;
    await plugin.app.fileManager.processFrontMatter(file, (fm: any) => {
        const list = (k: string): string[] => Array.isArray(fm[k]) ? fm[k].map(String) : [];
        let conf = list("bible-strongs-confirmed").filter(s => !s.startsWith(`${id}:`));
        let edit = list("bible-strongs-edited").filter(s => !s.startsWith(`${id}:`));
        let rej = list("bible-strongs-rejected").filter(s => s !== id);
        if (kind === "confirm") conf.push(`${id}:${strong}`);
        else if (kind === "edit") edit.push(`${id}:${strong}`);
        else if (kind === "reject") rej.push(id);
        const set = (k: string, v: string[]) => { if (v.length) fm[k] = v; else delete fm[k]; };
        set("bible-strongs-confirmed", conf); set("bible-strongs-edited", edit); set("bible-strongs-rejected", rej);
    });
}

// ── merged view: sidecar guesses + the note's confirm/edit/reject decisions ──
/** One resolved link: `n` English words from index `w` rendering the original word `s`. */
export type MergedTag = { w: number; n: number; s: string; guess: boolean; text: string };

/** The final per-word Strong's tags for a chapter of an aligned version: sidecar guesses overridden by
 *  the note's frontmatter decisions (edited/confirmed win, rejected removes). Keyed "book.ch.v".
 *  `text` is the pasted word at that index (tokenised like the reader). Shared by the reader overlay and
 *  the interlinear's "English ⟶ original order" view. */
export async function mergedTagsForChapter(plugin: Plugin, book: string, version: string, chapter: number): Promise<Record<string, MergedTag[]>> {
    const num = BOOK_NUM[book];
    if (!num) return {};
    const notePath = `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(chapter)}.md`;
    const [sidecar, md] = await Promise.all([
        loadGuessSidecar(plugin, version, book),
        plugin.app.vault.adapter.read(notePath).catch(() => ""),
    ]);
    const fm = plugin.app.metadataCache.getCache(notePath)?.frontmatter;
    const dec = readDecisions(fm);

    const tokensByVerse: Record<string, string[]> = {};
    for (const { verse, body } of versesFromMd(md)) tokensByVerse[`${book}.${chapter}.${verse}`] = tokenizeVerse(body);

    const out: Record<string, MergedTag[]> = {};
    const verseKeys = new Set<string>([...Object.keys(tokensByVerse)]);
    for (const k of Object.keys(sidecar)) if (k.startsWith(`${book}.${chapter}.`)) verseKeys.add(k);
    for (const key of verseKeys) {
        const verse = key.split(".")[2];
        const map = new Map<number, { s: string; guess: boolean; n: number }>();
        for (const g of sidecar[key] || []) map.set(g.w, { s: g.s, guess: true, n: Math.max(1, g.n || 1) });
        // A decision keeps the link's word-span; it only changes the number (or removes it).
        const spanOf = (w: number) => map.get(w)?.n ?? 1;
        for (const [id, s] of dec.confirmed) { const [v, w] = id.split(":"); if (v === verse) map.set(+w, { s, guess: false, n: spanOf(+w) }); }
        for (const [id, s] of dec.edited) { const [v, w] = id.split(":"); if (v === verse) map.set(+w, { s, guess: false, n: spanOf(+w) }); }
        for (const id of dec.rejected) { const [v, w] = id.split(":"); if (v === verse) map.delete(+w); }
        const toks = tokensByVerse[key] || [];
        const strip = (t: string) => t.replace(/^[^A-Za-z0-9']+|[^A-Za-z0-9']+$/g, "");
        const arr: MergedTag[] = [];
        for (const [w, { s, guess, n }] of map)
            arr.push({ w, n, s, guess, text: toks.slice(w, w + n).map(strip).filter(Boolean).join(" ") });
        arr.sort((a, b) => a.w - b.w);
        if (arr.length) out[key] = arr;
    }
    return out;
}

// ── commands + the paste hook ───────────────────────────────────────────────
function activeBibleChapter(plugin: Plugin): { book: string; chapter: number; version: string } | null {
    const file = plugin.app.workspace.getActiveFile();
    if (!file || !file.path.startsWith("bible/")) return null;
    const pp = file.path.split("/");
    if (pp.length < 4) return null;
    const book = pp[pp.length - 3].replace(/^\d+-/, "");
    const version = pp[pp.length - 2];
    const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
    return chapter && BOOK_NUM[book] ? { book, chapter, version } : null;
}

/** True if this version's chapters carry BAKED Strong's tags already (KJV/BSB) — no need to approximate. */
export function isNativelyTagged(version: string): boolean {
    return version === "kjv" || version === "bsb";
}

/** Align the whole vault-present set of chapters for one version+book (used by the "align this version" scope). */
async function alignWholeBook(plugin: Plugin, book: string, version: string): Promise<number> {
    const num = BOOK_NUM[book];
    const dir = `bible/${pad2(num)}-${book}/${version}`;
    const listing = await plugin.app.vault.adapter.list(dir).catch(() => null);
    let n = 0;
    for (const f of listing?.files || []) {
        const ch = parseInt((f.match(/-(\d+)\.md$/) || [])[1] || "", 10);
        if (ch) { await alignChapter(plugin, book, version, ch); n++; }
    }
    return n;
}

/** Kick off alignment for a freshly-pasted chapter (called from the paste modal). Best-effort, non-blocking. */
export function alignAfterPaste(plugin: Plugin, book: string, version: string, chapter: number): void {
    if (isNativelyTagged(version)) return;
    void (async () => {
        try {
            const r = await alignChapter(plugin, book, version, chapter);
            const nWords = Object.values(r).reduce((a, ws) => a + ws.length, 0);
            if (nWords) new Notice(`Approximated ${nWords} Strong's links for ${bookLabel(book)} ${chapter} (${version.toUpperCase()}). Tap a word to confirm or edit.`);
        } catch { /* best-effort */ }
    })();
}

export function registerBibleAlign(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-align-version",
        name: "Bible: align this version to the original (approximate)",
        callback: async () => {
            const cur = activeBibleChapter(plugin);
            if (!cur) { new Notice("Open a Bible chapter first."); return; }
            if (isNativelyTagged(cur.version)) { new Notice(`${cur.version.toUpperCase()} is already tagged with Strong's — no approximation needed.`); return; }
            new AlignScopeModal(plugin, cur).open();
        },
    });
    plugin.addCommand({
        id: "bible-review-guesses",
        name: "Bible: review Strong's guesses (this chapter)",
        callback: async () => {
            const cur = activeBibleChapter(plugin);
            if (!cur) { new Notice("Open a Bible chapter first."); return; }
            if (isNativelyTagged(cur.version)) { new Notice(`${cur.version.toUpperCase()} is already tagged — nothing to review.`); return; }
            new ReviewGuessesModal(plugin, cur).open();
        },
    });
}

/** Step through a chapter's still-guessed Strong's links, lowest-confidence first, to confirm / correct /
 *  reject each. The heavy-lift review flow that makes a whole pasted chapter tractable. */
type ReviewItem = { verse: number; w: number; n: number; s: string; c: number; tokens: string[] };
class ReviewGuessesModal extends Modal {
    private items: ReviewItem[] = [];
    private idx = 0;
    private counts = { confirmed: 0, changed: 0, rejected: 0, skipped: 0 };
    private lex: Record<string, { l?: string; t?: string; g?: string; d?: string }> = {};
    constructor(private plugin: Plugin, private cur: { book: string; chapter: number; version: string }) { super(plugin.app); }

    async onOpen(): Promise<void> {
        const { book, chapter, version } = this.cur;
        const num = BOOK_NUM[book];
        const notePath = `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(chapter)}.md`;
        const [sidecar, md] = await Promise.all([
            loadGuessSidecar(this.plugin, version, book),
            this.plugin.app.vault.adapter.read(notePath).catch(() => ""),
        ]);
        const dec = readDecisions(this.plugin.app.metadataCache.getCache(notePath)?.frontmatter);
        const tokensByVerse: Record<number, string[]> = {};
        for (const { verse, body } of versesFromMd(md)) tokensByVerse[+verse] = tokenizeVerse(body);
        const decided = (v: number, w: number) => dec.confirmed.has(`${v}:${w}`) || dec.edited.has(`${v}:${w}`) || dec.rejected.has(`${v}:${w}`);
        // Only the UNCERTAIN guesses need review — high-confidence links (multi-anchor exact matches) are
        // almost always right, so reviewing them would bury the ~dozen that actually need a decision.
        const REVIEW_MAX_CONF = 0.9;
        for (const [key, ws] of Object.entries(sidecar)) {
            const parts = key.split("."); if (parts[0] !== book || +parts[1] !== chapter) continue;
            const verse = +parts[2];
            for (const g of ws) if (g.c < REVIEW_MAX_CONF && !decided(verse, g.w))
                this.items.push({ verse, w: g.w, n: Math.max(1, g.n || 1), s: g.s, c: g.c, tokens: tokensByVerse[verse] || [] });
        }
        this.items.sort((a, b) => a.c - b.c);
        this.lex = await this.plugin.app.vault.adapter
            .read(`AI/bible-strongs/_lexicon-${num >= 40 ? "G" : "H"}.json`).then(s => JSON.parse(s)).catch(() => ({}));
        this.render();
    }

    private async decide(kind: "confirm" | "edit" | "reject", strong = ""): Promise<void> {
        const it = this.items[this.idx];
        const notePath = `bible/${pad2(BOOK_NUM[this.cur.book])}-${this.cur.book}/${this.cur.version}/${this.cur.book}-${pad3(this.cur.chapter)}.md`;
        await writeDecision(this.plugin, notePath, it.verse, it.w, kind, strong);
        if (kind === "confirm") this.counts.confirmed++; else if (kind === "edit") this.counts.changed++; else this.counts.rejected++;
        this.next();
    }
    private next(): void { this.idx++; this.render(); }

    private render(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.addClass("lm-strongs-modal");
        contentEl.createEl("h3", { text: `Review Strong's guesses — ${bookLabel(this.cur.book)} ${this.cur.chapter}` });
        if (this.idx >= this.items.length) {
            const c = this.counts;
            contentEl.createEl("p", { text: this.items.length
                ? `Done — ${c.confirmed} confirmed, ${c.changed} changed, ${c.rejected} removed, ${c.skipped} skipped.`
                : "No uncertain guesses to review — the approximate links here are all high-confidence (or already decided). You can still change any word from its hover popup, or run “Bible: align this version…” if you haven't yet." });
            contentEl.createEl("button", { text: "Close", cls: "mod-cta" }).addEventListener("click", () => { rerender(this.plugin); this.close(); });
            return;
        }
        const it = this.items[this.idx];
        contentEl.createEl("p", { cls: "setting-item-description", text: `${this.idx + 1} of ${this.items.length} · lowest-confidence first` });

        // verse text with the target word highlighted
        const verseEl = contentEl.createDiv("lm-review-verse");
        verseEl.createEl("b", { text: `${it.verse} ` });
        // highlight the whole linked phrase (one original word may take several English words)
        it.tokens.forEach((tok, i) => {
            if (i >= it.w && i < it.w + it.n) verseEl.createEl("mark", { text: tok + " " });
            else verseEl.createSpan({ text: tok + " " });
        });
        if (it.n > 1) contentEl.createEl("p", { cls: "setting-item-description",
            text: `These ${it.n} words together render one original word.` });

        const lx = this.lex[it.s] || {};
        const card = contentEl.createDiv("lm-review-card");
        card.createSpan({ cls: "lm-review-strong", text: it.s });
        if (lx.l) card.createSpan({ cls: "lm-strongs-lemma", text: ` ${lx.l}` });
        if (lx.t) card.createSpan({ cls: "lm-strongs-translit", text: ` ${lx.t}` });
        const meaning = lx.d || lx.g;
        if (meaning) card.createDiv({ cls: "lm-strongs-gloss", text: meaning.length > 180 ? meaning.slice(0, 180) + "…" : meaning });
        card.createDiv({ cls: "lm-review-conf", text: `confidence ${(it.c * 100).toFixed(0)}%` });

        const btns = contentEl.createDiv("lm-review-btns");
        btns.createEl("button", { text: "Confirm", cls: "mod-cta" }).addEventListener("click", () => void this.decide("confirm", it.s));
        btns.createEl("button", { text: "Change…" }).addEventListener("click", () =>
            new StrongsInputModal2(this.plugin, (n) => void this.decide("edit", n)).open());
        btns.createEl("button", { text: "Not a match" }).addEventListener("click", () => void this.decide("reject"));
        btns.createEl("button", { text: "Skip" }).addEventListener("click", () => { this.counts.skipped++; this.next(); });
    }
    onClose(): void { rerender(this.plugin); this.contentEl.empty(); }
}

/** Minimal "enter a Strong's number" prompt (mirrors bible.ts's StrongsInputModal; kept local so the
 *  aligner has no import cycle back into bible.ts's modal). */
class StrongsInputModal2 extends Modal {
    constructor(private plugin: Plugin, private onSubmit: (n: string) => void) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Correct the Strong's number" });
        const input = contentEl.createEl("input", { type: "text", attr: { placeholder: "e.g. H430 or G26" } });
        input.style.width = "100%";
        const submit = () => { const v = input.value.trim().toUpperCase(); this.close();
            if (/^[HG]\d+$/.test(v)) this.onSubmit(v); else new Notice("Enter a Strong's number like H430 or G26."); };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
        const row = contentEl.createDiv(); row.style.marginTop = "8px";
        row.createEl("button", { text: "Save", cls: "mod-cta" }).addEventListener("click", submit);
        setTimeout(() => input.focus(), 0);
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Ask whether to align just this chapter or the whole book for this version. */
class AlignScopeModal extends Modal {
    constructor(private plugin: Plugin, private cur: { book: string; chapter: number; version: string }) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        const { book, chapter, version } = this.cur;
        contentEl.createEl("h3", { text: "Approximate Strong's links" });
        contentEl.createEl("p", { cls: "setting-item-description", text:
            `Guess the original-language (Strong's) connection for each word of the ${version.toUpperCase()} text by ` +
            `comparing it to the tagged BSB, ULT and KJV. Guesses are marked approximate — you can confirm or edit each.` });
        const run = async (whole: boolean) => {
            this.close();
            new Notice(whole ? `Aligning all of ${bookLabel(book)} (${version.toUpperCase()})…` : `Aligning ${bookLabel(book)} ${chapter}…`);
            try {
                if (whole) { const n = await alignWholeBook(this.plugin, book, version); new Notice(`Aligned ${n} chapter(s) of ${bookLabel(book)}.`); }
                else { const r = await alignChapter(this.plugin, book, version, chapter); const w = Object.values(r).reduce((a, ws) => a + ws.length, 0); new Notice(`Aligned ${bookLabel(book)} ${chapter} — ${w} words.`); }
                rerender(this.plugin);
            } catch (e) { new Notice("Alignment failed: " + (e as Error).message); }
        };
        const row = contentEl.createDiv(); row.style.cssText = "display:flex;gap:8px;margin-top:12px;";
        row.createEl("button", { text: `This chapter (${chapter})`, cls: "mod-cta" }).addEventListener("click", () => void run(false));
        row.createEl("button", { text: `All of ${bookLabel(book)}` }).addEventListener("click", () => void run(true));
    }
    onClose(): void { this.contentEl.empty(); }
}

function rerender(plugin: Plugin): void {
    const view = plugin.app.workspace.getActiveViewOfType(MarkdownView);
    (view as any)?.previewMode?.rerender?.(true);
}
