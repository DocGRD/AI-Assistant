// LoreMaster — Bible Strong's study tools: a per-chapter INTERLINEAR panel and a CONCORDANCE search.
//
// Data is sidecar JSON under AI/bible-strongs/ (built by assistant_core/bible/tools/gen_strongs.py from
// the public-domain KJV+Strong's — the WEB's own USFM tags are corrupt). The WEB stays the reading
// text; this is a study overlay:
//   {book}.json          per-book interlinear: {"book.ch.v": [[phrase, [strongs]], ...]}
//   _concordance-H/G.json {strong: [refs]}   — every verse that uses a Strong's number
//   _words.json          KJV head-word -> [strongs]   (word-based concordance search)
//   _lexicon-H/G.json    {strong: {l: lemma, t: translit, g: gloss}}

import { Plugin, TFile, MarkdownView, MarkdownPostProcessorContext, Modal, Setting, Platform, Notice } from "obsidian";
import { BOOK_NUM, pad2, pad3, bookLabel, wordEdgeInsertPoint, StrongsInputModal, rerenderAfterMetadata } from "./bible";
import { mergedTagsForChapter, writeDecision, isNativelyTagged } from "./bible-align";

type Interlinear = Record<string, [string, string[]][]>;
type Concordance = Record<string, string[]>;
type Lexicon = Record<string, { l: string; t: string; g: string; d?: string; r?: string }>;   // l=lemma, r=root/derivation
type SblgntWord = { g: string; l: string; m: string; s: string };
type SblgntInterlinear = Record<string, SblgntWord[]>;
type WlcWord = { h: string; m: string; s: string };           // Hebrew word, readable morph, Strong's
type WlcInterlinear = Record<string, WlcWord[]>;
type BsbWord = { o: string; e: string; s: string; m: string; t: string };  // orig, English gloss, Strong's, morph, translit
type BsbInterlinear = Record<string, BsbWord[]>;

const DIR = "AI/bible-strongs";           // KJV + Strong's (Textus Receptus basis)
const SBLGNT_DIR = "AI/bible-sblgnt";      // SBLGNT (modern critical text), NT/Greek only
const WLC_DIR = "AI/bible-wlc";            // WLC + OSHB morphology (Hebrew OT)
const BSB_DIR = "AI/bible-bsb";            // BSB reverse interlinear (English glosses in original order), whole Bible
const isGreek = (s: string) => s.charAt(0).toUpperCase() === "G";

/** Which text the study tools sit on: KJV/Strong's (TR), SBLGNT (Greek NT), WLC (Hebrew OT), or the BSB
 *  reverse interlinear (English glosses in original word order, whole Bible). */
type StudySource = "strongs" | "sblgnt" | "wlc" | "bsb";
function getSource(plugin: Plugin): StudySource {
    const s = (plugin as any).settings?.bibleStudySource;
    return (s === "sblgnt" || s === "wlc" || s === "bsb") ? s : "strongs";
}
async function setSource(plugin: Plugin, s: StudySource): Promise<void> {
    const st = (plugin as any).settings;
    if (st) { st.bibleStudySource = s; try { await (plugin as any).saveSettings?.(); } catch { /* best-effort */ } }
}

/** Small cached JSON loaders for the sidecar data (each file read at most once). */
class StrongsData {
    private cache = new Map<string, Promise<any>>();
    constructor(private plugin: Plugin) {}
    private read<T>(dir: string, file: string): Promise<T> {
        const path = `${dir}/${file}`;
        let p = this.cache.get(path);
        if (!p) {
            p = this.plugin.app.vault.adapter.read(path).then(s => JSON.parse(s)).catch(() => ({}));
            this.cache.set(path, p);
        }
        return p as Promise<T>;
    }
    interlinear(book: string) { return this.read<Interlinear>(DIR, `${book}.json`); }
    concordance(strong: string) { return this.read<Concordance>(DIR, `_concordance-${isGreek(strong) ? "G" : "H"}.json`); }
    lexicon(strong: string) { return this.read<Lexicon>(DIR, `_lexicon-${isGreek(strong) ? "G" : "H"}.json`); }
    words() { return this.read<Record<string, string[]>>(DIR, "_words.json"); }
    // SBLGNT (modern critical Greek text) — parallel interlinear + concordance, keyed to the same Strong's.
    sblgnt(book: string) { return this.read<SblgntInterlinear>(SBLGNT_DIR, `${book}.json`); }
    sblgntConcordance() { return this.read<Concordance>(SBLGNT_DIR, "_concordance-G.json"); }
    async sblgntAvailable(): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`${SBLGNT_DIR}/_concordance-G.json`).catch(() => false);
    }
    // WLC + OSHB morphology (Hebrew OT) — the OT counterpart to SBLGNT, keyed to the same Strong's.
    wlc(book: string) { return this.read<WlcInterlinear>(WLC_DIR, `${book}.json`); }
    wlcConcordance() { return this.read<Concordance>(WLC_DIR, "_concordance-H.json"); }
    async wlcAvailable(): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`${WLC_DIR}/_concordance-H.json`).catch(() => false);
    }
    // BSB reverse interlinear — English glosses in ORIGINAL word order, keyed to Strong's (whole Bible).
    bsb(book: string) { return this.read<BsbInterlinear>(BSB_DIR, `${book}.json`); }
    async bsbAvailable(book: string): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`${BSB_DIR}/${book}.json`).catch(() => false);
    }
    // A pasted version that has been aligned (approximate Strong's) → its own reverse interlinear.
    async guessAvailable(version: string, book: string): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`AI/bible-guess/${version}/${book}.json`).catch(() => false);
    }
    async available(): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`${DIR}/_words.json`).catch(() => false);
    }

    /** Every original-language word of a verse — manuscript form `o`, its transliteration `t`, readable
     *  morph `m`, Strong's `s` — from the best available interlinear (SBLGNT for the NT, WLC for the OT,
     *  else the BSB). SBLGNT/WLC give the fuller readable morphology; the manuscript transliteration is
     *  taken from the BSB (which carries it for the whole Bible), matched by Strong's occurrence. Used to
     *  show a word's manuscript form and to pick which original word an English selection connects to. */
    async verseOriginals(book: string, chapter: number, verse: number): Promise<{ o: string; t: string; m: string; s: string }[]> {
        const key = `${book}.${chapter}.${verse}`;
        const isNT = (BOOK_NUM[book] || 0) >= 40;
        // Build a Strong's → [transliteration…] (in order) map from the BSB, to enrich SBLGNT/WLC.
        const bsbT = new Map<string, string[]>();
        if (await this.bsbAvailable(book)) {
            for (const w of (await this.bsb(book))[key] || []) {
                if (!w.s) continue;
                if (!bsbT.has(w.s)) bsbT.set(w.s, []);
                bsbT.get(w.s)!.push(w.t || "");
            }
        }
        const withT = (list: { o: string; m: string; s: string }[]) => {
            const seen = new Map<string, number>();
            return list.map(e => {
                const k = seen.get(e.s) ?? 0; seen.set(e.s, k + 1);
                return { ...e, t: (bsbT.get(e.s) || [])[k] || "" };
            });
        };
        if (isNT && await this.sblgntAvailable()) {
            const v = (await this.sblgnt(book))[key];
            if (v?.length) return withT(v.map(w => ({ o: w.g, m: w.m, s: w.s })));
        }
        if (!isNT && await this.wlcAvailable()) {
            const v = (await this.wlc(book))[key];
            if (v?.length) return withT(v.map(w => ({ o: w.h, m: w.m, s: w.s })));
        }
        if (await this.bsbAvailable(book)) {
            const v = (await this.bsb(book))[key];
            if (v?.length) return v.filter(w => w.o).map(w => ({ o: w.o, t: w.t || "", m: w.m, s: w.s }));
        }
        return [];
    }
}

/** "john.3.16" → vault link "bible/43-john/web/john-003#^v16" (WEB reading note). */
function refToLink(ref: string, version = "web"): string | null {
    const [book, c, v] = ref.split(".");
    const num = BOOK_NUM[book];
    if (!num) return null;
    return `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(parseInt(c, 10))}#^v${v}`;
}
function refLabel(ref: string): string {
    const [book, c, v] = ref.split(".");
    return `${bookLabel(book)} ${c}:${v}`;
}

/** The book-slug + chapter of the active Bible note, from its path. */
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

// ── shared: a lexicon "gloss card" for one Strong's number, with a link into the concordance ──
async function lexiconLine(el: HTMLElement, data: StrongsData, strong: string,
                           onConcordance: (s: string) => void): Promise<void> {
    const lex = (await data.lexicon(strong))[strong];
    const row = el.createDiv("lm-strongs-lex");
    const head = row.createDiv("lm-strongs-lex-head");
    head.createEl("a", { text: strong, cls: "lm-strongs-num", href: "#" })
        .addEventListener("click", (e) => { e.preventDefault(); onConcordance(strong); });
    if (lex?.l) head.createSpan({ cls: "lm-strongs-lemma", text: ` ${lex.l}` });
    if (lex?.t) head.createSpan({ cls: "lm-strongs-translit", text: ` ${lex.t}` });
    if (lex?.g) row.createDiv("lm-strongs-gloss").setText(lex.g);
    if (lex?.d) {
        const full = row.createDiv("lm-strongs-fuller");
        full.createSpan({ cls: "lm-strongs-fuller-src", text: isGreek(strong) ? "Dodson" : "BDB" });
        full.createSpan({ text: " " + lex.d });
    }
}

// ── Interlinear: the active chapter, word-by-word with Strong's numbers ──────────────────────
class InterlinearModal extends Modal {
    constructor(private plugin: Plugin, private data: StrongsData,
                private book: string, private chapter: number, private version: string) {
        super(plugin.app);
    }
    async onOpen(): Promise<void> {
        const { contentEl } = this;
        contentEl.addClass("lm-strongs-modal");
        contentEl.createEl("h3", { text: `${bookLabel(this.book)} ${this.chapter} — interlinear` });
        const isNT = (BOOK_NUM[this.book] || 0) >= 40;
        const origKey: StudySource = isNT ? "sblgnt" : "wlc";
        const origAvail = isNT ? await this.data.sblgntAvailable() : await this.data.wlcAvailable();
        const bsbAvail = await this.data.bsbAvailable(this.book);
        // This version's own approximate reverse interlinear (pasted + aligned; needs BSB for original order).
        const alignedAvail = !isNativelyTagged(this.version) && bsbAvail && await this.data.guessAvailable(this.version, this.book);
        let source: StudySource | "aligned" = getSource(this.plugin);
        // an "original text" source only applies to its own testament (SBLGNT=NT, WLC=OT)
        if ((source === "sblgnt" || source === "wlc") && (!origAvail || source !== origKey)) source = "strongs";
        if (source === "bsb" && !bsbAvail) source = "strongs";

        const toolbar = contentEl.createDiv();                    // source switch sits at the top
        const desc = contentEl.createEl("p", { cls: "setting-item-description" });
        const body = contentEl.createDiv("lm-interlinear");
        const openConc = (s: string) => new ConcordanceModal(this.plugin, this.data, s).open();

        const render = async () => {
            body.empty();
            if (source === "bsb") {
                desc.setText("English glosses in ORIGINAL word order (Berean Standard Bible), each tagged with its "
                    + "Strong's number. Tap a number for its meaning + every verse that uses it.");
                const inter = await this.data.bsb(this.book);
                for (let v = 1; v < 400; v++) {
                    const cells = inter[`${this.book}.${this.chapter}.${v}`];
                    if (!cells) continue;
                    const line = body.createDiv("lm-interlinear-verse");
                    line.createSpan({ cls: "lm-interlinear-vnum", text: `${v} ` });
                    for (const w of cells) {
                        const wd = line.createSpan("lm-interlinear-word " + (isNT ? "lm-interlinear-gk" : "lm-interlinear-heb"));
                        if (w.o) wd.createSpan({ cls: isNT ? "lm-interlinear-grk" : "lm-interlinear-hbo", text: w.o + " " });
                        if (w.e) wd.createSpan({ cls: "lm-interlinear-en-gloss", text: w.e });
                        if (w.m) wd.createSpan({ cls: "lm-interlinear-morph", text: w.m });
                        if (w.s) wd.createEl("a", { text: " " + w.s, cls: "lm-strongs-num", href: "#" })
                            .addEventListener("click", (e) => { e.preventDefault(); openConc(w.s); });
                    }
                }
            } else if (source === "aligned") {
                desc.setText(`Your ${this.version.toUpperCase()} words laid out in ORIGINAL word order — the approximate `
                    + "connections (confirm or edit each in the reader). Dimmed = the BSB gloss where no "
                    + `${this.version.toUpperCase()} word is linked yet. Tap a number for its meaning and every verse that uses it.`);
                const inter = await this.data.bsb(this.book);                                  // original word order + Strong's
                const merged = await mergedTagsForChapter(this.plugin, this.book, this.version, this.chapter);
                for (let v = 1; v < 400; v++) {
                    const cells = inter[`${this.book}.${this.chapter}.${v}`];
                    if (!cells) continue;
                    const q = new Map<string, string[]>();                                     // Strong's → this version's word(s)
                    for (const t of merged[`${this.book}.${this.chapter}.${v}`] || []) {
                        if (!t.s || !t.text) continue;
                        if (!q.has(t.s)) q.set(t.s, []);
                        q.get(t.s)!.push(t.text);
                    }
                    const line = body.createDiv("lm-interlinear-verse");
                    line.createSpan({ cls: "lm-interlinear-vnum", text: `${v} ` });
                    for (const w of cells) {
                        const wd = line.createSpan("lm-interlinear-word " + (isNT ? "lm-interlinear-gk" : "lm-interlinear-heb"));
                        if (w.o) wd.createSpan({ cls: isNT ? "lm-interlinear-grk" : "lm-interlinear-hbo", text: w.o + " " });
                        const eng = q.get(w.s)?.shift();
                        wd.createSpan({ cls: eng ? "lm-interlinear-en-gloss" : "lm-interlinear-en-gloss lm-interlinear-en-fallback", text: eng || w.e });
                        if (w.m) wd.createSpan({ cls: "lm-interlinear-morph", text: w.m });
                        if (w.s) wd.createEl("a", { text: " " + w.s, cls: "lm-strongs-num", href: "#" })
                            .addEventListener("click", (e) => { e.preventDefault(); openConc(w.s); });
                    }
                }
            } else if (source === "wlc") {
                desc.setText("WLC — the Hebrew Old Testament (Westminster Leningrad Codex) with OSHB morphology, "
                    + "word-by-word + Strong's. Tap a number for its meaning and every verse that uses it.");
                const inter = await this.data.wlc(this.book);
                for (let v = 1; v < 400; v++) {
                    const cells = inter[`${this.book}.${this.chapter}.${v}`];
                    if (!cells) continue;
                    const line = body.createDiv("lm-interlinear-verse");
                    line.createSpan({ cls: "lm-interlinear-vnum", text: `${v} ` });
                    for (const w of cells) {
                        const wd = line.createSpan("lm-interlinear-word lm-interlinear-heb");
                        wd.createSpan({ cls: "lm-interlinear-hbo", text: w.h + " " });
                        if (w.m) wd.createSpan({ cls: "lm-interlinear-morph", text: w.m });
                        if (w.s) wd.createEl("a", { text: " " + w.s, cls: "lm-strongs-num", href: "#" })
                            .addEventListener("click", (e) => { e.preventDefault(); openConc(w.s); });
                    }
                }
            } else if (source === "sblgnt") {
                desc.setText("SBLGNT — the modern critical Greek text, word-by-word with morphology + Strong's. "
                    + "Tap a number for its meaning and every verse that uses it.");
                const inter = await this.data.sblgnt(this.book);
                for (let v = 1; v < 400; v++) {
                    const cells = inter[`${this.book}.${this.chapter}.${v}`];
                    if (!cells) continue;
                    const line = body.createDiv("lm-interlinear-verse");
                    line.createSpan({ cls: "lm-interlinear-vnum", text: `${v} ` });
                    for (const w of cells) {
                        const wd = line.createSpan("lm-interlinear-word lm-interlinear-gk");
                        wd.createSpan({ cls: "lm-interlinear-grk", text: w.g + " " });
                        if (w.m) wd.createSpan({ cls: "lm-interlinear-morph", text: w.m });
                        if (w.s) wd.createEl("a", { text: " " + w.s, cls: "lm-strongs-num", href: "#" })
                            .addEventListener("click", (e) => { e.preventDefault(); openConc(w.s); });
                    }
                }
            } else {
                desc.setText("KJV word ↔ Strong's number. Tap a number for its Hebrew/Greek word, meaning, and every verse that uses it.");
                const inter = await this.data.interlinear(this.book);
                for (let v = 1; v < 400; v++) {
                    const cells = inter[`${this.book}.${this.chapter}.${v}`];
                    if (!cells) continue;
                    const line = body.createDiv("lm-interlinear-verse");
                    line.createSpan({ cls: "lm-interlinear-vnum", text: `${v} ` });
                    for (const [phrase, codes] of cells) {
                        const w = line.createSpan("lm-interlinear-word");
                        if (phrase) w.createSpan({ cls: "lm-interlinear-en", text: phrase + " " });
                        for (const s of codes) {
                            w.createEl("a", { text: s, cls: "lm-strongs-num", href: "#" })
                                .addEventListener("click", (e) => { e.preventDefault(); openConc(s); });
                        }
                    }
                }
            }
        };

        if (origAvail || bsbAvail || alignedAvail) {
            const origLabel = isNT ? "SBLGNT (Greek)" : "WLC (Hebrew)";
            new Setting(toolbar).setName("Text")
                .setDesc("Choose the basis: KJV/Strong's, the original text, or English glosses laid out in original word order.")
                .addDropdown(d => {
                    d.addOption("strongs", "KJV / Strong's (TR)");
                    if (origAvail) d.addOption(origKey, origLabel);
                    if (bsbAvail) d.addOption("bsb", "English ⟶ original order (BSB)");
                    if (alignedAvail) d.addOption("aligned", `English ⟶ original order (${this.version.toUpperCase()})`);
                    d.setValue(source).onChange(async (v) => {
                        source = v as StudySource | "aligned";
                        if (v !== "aligned") await setSource(this.plugin, source as StudySource);   // "aligned" is version-specific, not a global default
                        await render();
                    });
                });
        }
        await render();
    }
    onClose(): void { this.contentEl.empty(); }
}

// ── Concordance: every verse that uses a Strong's number (or an English word → numbers) ──────
class ConcordanceModal extends Modal {
    private source: StudySource = "strongs";
    constructor(private plugin: Plugin, private data: StrongsData, private initial = "") {
        super(plugin.app);
    }
    async onOpen(): Promise<void> {
        const { contentEl } = this;
        contentEl.addClass("lm-strongs-modal");
        contentEl.createEl("h3", { text: "Concordance" });
        const origOK = (await this.data.sblgntAvailable()) || (await this.data.wlcAvailable());
        this.source = getSource(this.plugin);
        let query = this.initial;
        const results = contentEl.createDiv("lm-concordance-results");
        if (origOK) {
            // One switch for both testaments: "original" counts Greek numbers over the SBLGNT and Hebrew
            // numbers over the WLC. (Stored as a non-"strongs" source; interpreted per number type below.)
            new Setting(contentEl).setName("Text")
                .setDesc("Count verses over the KJV/Textus Receptus, or over the original SBLGNT (Greek) / WLC (Hebrew) text.")
                .addDropdown(d => d.addOption("strongs", "KJV / Strong's (TR)").addOption("orig", "Original (SBLGNT / WLC)")
                    .setValue(this.source === "strongs" ? "strongs" : "orig").onChange(async (v) => {
                        this.source = (v === "orig" ? "sblgnt" : "strongs") as StudySource;
                        await setSource(this.plugin, this.source);
                        if (/^[hg]\d+$/i.test(query.trim())) await this.showStrong(results, query.trim().toUpperCase());
                    }));
        }
        const search = new Setting(contentEl).setName("Strong's number or word")
            .setDesc("e.g. H430, G26, or “love”.");
        search.addText(t => { t.setValue(this.initial).onChange(v => query = v);
            t.inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") void run(); }); });
        search.addButton(b => b.setButtonText("Search").setCta().onClick(() => void run()));

        const run = async () => {
            results.empty();
            const q = query.trim();
            if (!q) return;
            if (/^[hg]\d+$/i.test(q)) return this.showStrong(results, q.toUpperCase());
            // English word → candidate Strong's numbers
            const words = await this.data.words();
            const hits = words[q.toLowerCase().replace(/[^a-z]/g, "")] || [];
            if (!hits.length) { results.createEl("p", { text: `No Strong's numbers found for “${q}”.` }); return; }
            results.createEl("p", { cls: "setting-item-description", text: `“${q}” maps to ${hits.length} Strong's number(s) — pick one:` });
            for (const s of hits) await lexiconLine(results, this.data, s, (x) => this.showStrong(results, x));
        };
        if (this.initial) await run();
    }
    private async showStrong(el: HTMLElement, strong: string): Promise<void> {
        el.empty();
        await lexiconLine(el, this.data, strong, (s) => this.showStrong(el, s));
        // "Original" counts Greek over the SBLGNT and Hebrew over the WLC; otherwise the KJV/Strong's data.
        const useOrig = this.source !== "strongs";
        const useSblgnt = useOrig && isGreek(strong) && await this.data.sblgntAvailable();
        const useWlc = useOrig && !isGreek(strong) && await this.data.wlcAvailable();
        const refs = useSblgnt ? ((await this.data.sblgntConcordance())[strong] || [])
                   : useWlc ? ((await this.data.wlcConcordance())[strong] || [])
                   : ((await this.data.concordance(strong))[strong] || []);
        el.createEl("div", { cls: "lm-concordance-count",
            text: `${refs.length} verse${refs.length === 1 ? "" : "s"}`
                  + (useSblgnt ? " · SBLGNT" : useWlc ? " · WLC" : "")
                  + (refs.length > 400 ? " (showing first 400)" : "") });
        const list = el.createDiv("lm-concordance-list");
        for (const ref of refs.slice(0, 400)) {
            const link = refToLink(ref);
            const a = list.createEl("a", { text: refLabel(ref), cls: "lm-concordance-item", href: link || "#" });
            if (link) a.addEventListener("click", (e) => {
                e.preventDefault(); this.close();
                this.plugin.app.workspace.openLinkText(link, "", (e as MouseEvent).ctrlKey || (e as MouseEvent).metaKey);
            });
        }
    }
    onClose(): void { this.contentEl.empty(); }
}

// ── Word-level Strong's popup ────────────────────────────────────────────────
// KJV notes carry per-word `<span class="lm-s" data-s="H430">…</span>`. On hover (desktop) or tap
// (mobile) of a tagged word, show its original Hebrew/Greek word + transliteration + number + gloss,
// with a link to open the full Strong's entry (the concordance modal).
export function registerBibleStrongsHover(plugin: Plugin): void {
    const data = new StrongsData(plugin);
    let card: HTMLElement | null = null;      // the visible popup, or null
    let cardSpan: HTMLElement | null = null;  // the word it's showing
    let overCard = false;
    let dwell: number | null = null;          // timer: open a word's card after a short hover
    let hideT: number | null = null;          // timer: hide the card after leaving
    let pending: HTMLElement | null = null;   // the word `dwell` will open
    let buildSeq = 0;                         // supersede guard for the async build

    // Remove just the card (leaves the dwell/pending alone, so a card being swapped to the next word
    // isn't cancelled). `destroy` is the full teardown used on real dismissal.
    const removeCard = () => { card?.remove(); card = null; cardSpan = null; overCard = false; };
    const destroy = () => {
        if (dwell) { window.clearTimeout(dwell); dwell = null; }
        if (hideT) { window.clearTimeout(hideT); hideT = null; }
        pending = null; removeCard();
    };
    const scheduleHide = () => {
        if (hideT) window.clearTimeout(hideT);
        hideT = window.setTimeout(() => { if (!overCard) removeCard(); }, 240);
    };

    // The book/chapter/verse of a hovered word, from the active note path + the verse's <p>.
    const contextOf = (span: HTMLElement): { book: string; chapter: number; verse: number } | null => {
        const path = plugin.app.workspace.getActiveFile()?.path || "";
        if (!path.startsWith("bible/")) return null;
        const pp = path.split("/");
        const book = pp[pp.length - 3]?.replace(/^\d+-/, "") || "";
        const chapter = parseInt((pp[pp.length - 1]?.match(/-(\d+)\.md$/) || [])[1] || "", 10);
        const p = span.closest("p");
        const num = p?.firstElementChild;
        const verse = num && num.tagName === "STRONG" && /^\d+$/.test((num.textContent || "").trim())
            ? parseInt((num.textContent || "").trim(), 10) : 0;
        return book && chapter && verse ? { book, chapter, verse } : null;
    };

    const build = async (span: HTMLElement) => {
        const codes = (span.getAttribute("data-s") || "").split(/\s+/).filter(Boolean);
        if (!codes.length) return;
        if (span === cardSpan) return;                       // already showing this word
        const seq = ++buildSeq;                              // newer build supersedes this one
        // Build into a DETACHED node and only swap it in when ready — so there's never an empty box, and
        // the current card stays put until the new one is fully built (no flicker while chaining).
        const c = document.createElement("div");
        c.className = "lm-strongs-pop";
        const ctx = contextOf(span);
        for (const s of codes) {
            const lex = (await data.lexicon(s))[s];
            if (seq !== buildSeq) return;                    // superseded by a newer word before load
            // The manuscript (inflected) form + morphology of THIS word in THIS verse.
            const forms = ctx ? (await data.verseOriginals(ctx.book, ctx.chapter, ctx.verse)).filter(w => w.s === s) : [];
            if (seq !== buildSeq) return;
            const row = c.createDiv("lm-strongs-pop-row");
            // Line 1 — the MANUSCRIPT form (what actually stands in the text) + its transliteration + parsing.
            const manuscript = forms.map(f => f.o).filter(Boolean).join(" · ");
            const msTranslit = forms.map(f => f.t).filter(Boolean).join(" · ");
            const morph = forms.map(f => f.m).filter(Boolean).join(" · ");
            const head = row.createDiv("lm-strongs-pop-head");
            if (manuscript) {
                head.createSpan({ cls: "lm-strongs-lemma", text: manuscript });
                if (msTranslit) head.createSpan({ cls: "lm-strongs-translit", text: ` ${msTranslit}` });
            } else if (lex?.l) {
                // no interlinear form for this verse — fall back to the lemma on line 1
                head.createSpan({ cls: "lm-strongs-lemma", text: lex.l });
                if (lex?.t) head.createSpan({ cls: "lm-strongs-translit", text: ` ${lex.t}` });
            }
            if (morph) row.createDiv({ cls: "lm-strongs-morph", text: morph });
            // Line 2 — the LEMMA (dictionary form) + its transliteration (shown when we led with a form).
            if (manuscript && lex?.l) {
                const lemLine = row.createDiv("lm-strongs-lemma-line");
                lemLine.createSpan({ cls: "lm-strongs-lemma-word", text: lex.l });
                if (lex?.t) lemLine.createSpan({ cls: "lm-strongs-translit", text: ` ${lex.t}` });
            }
            // Then the Strong's number (opens the concordance).
            row.createEl("a", { text: s, cls: "lm-strongs-num lm-strongs-num-line", href: "#" })
                .addEventListener("click", (e) => { e.preventDefault(); destroy(); new ConcordanceModal(plugin, data, s).open(); });
            // prefer the fuller free-lexicon definition (Dodson/BDB) — it is cleaner and more
            // accurate than the terse Strong's gloss; the full entry is one tap away.
            const meaning = lex?.d || lex?.g;
            if (meaning) row.createDiv({ cls: "lm-strongs-gloss", text: meaning.length > 160 ? meaning.slice(0, 160) + "…" : meaning });
            if (lex?.r) {
                const rootEl = row.createDiv("lm-strongs-root");
                rootEl.createSpan({ cls: "lm-strongs-root-label", text: "root " });
                // link any Strong's numbers named in the derivation ("from G25 (ἀγαπάω)")
                let last = 0; const re = /([GH]\d+)/g; let mm: RegExpExecArray | null;
                while ((mm = re.exec(lex.r))) {
                    if (mm.index > last) rootEl.appendText(lex.r.slice(last, mm.index));
                    const num = mm[1];
                    rootEl.createEl("a", { text: num, cls: "lm-strongs-num", href: "#" })
                        .addEventListener("click", (e) => { e.preventDefault(); destroy(); new ConcordanceModal(plugin, data, num).open(); });
                    last = mm.index + num.length;
                }
                if (last < lex.r.length) rootEl.appendText(lex.r.slice(last));
            }
        }
        c.createEl("a", { text: "Open Concordance →", cls: "lm-strongs-pop-open", href: "#" })
            .addEventListener("click", (e) => { e.preventDefault(); const s = codes[0]; destroy(); new ConcordanceModal(plugin, data, s).open(); });

        // Approximation controls — for guessed tags (overlay) and the user's own confirmed/edited ones,
        // let them confirm / change / reject the connection right from the popup.
        const guess = span.getAttribute("data-guess") === "1";
        const approx = guess || span.getAttribute("data-approx") === "1";
        if (approx) {
            const verse = parseInt(span.getAttribute("data-lm-verse") || "0", 10);
            const widx = parseInt(span.getAttribute("data-lm-widx") || "-1", 10);
            const notePath = plugin.app.workspace.getActiveFile()?.path || "";
            const foot = c.createDiv("lm-strongs-approx");
            foot.createDiv({ cls: "lm-strongs-approx-label", text: guess ? "≈ approximate — is this right?" : "✓ your confirmed link" });
            const btns = foot.createDiv("lm-strongs-approx-btns");
            const act = (fn: () => Promise<void>) => { destroy(); void (async () => { await fn(); rerenderAfterMetadata(plugin, notePath); })(); };
            if (verse && widx >= 0 && notePath) {
                if (guess) btns.createEl("button", { text: "Confirm" })
                    .addEventListener("click", () => act(() => writeDecision(plugin, notePath, verse, widx, "confirm", codes[0])));
                btns.createEl("button", { text: "Change…" }).addEventListener("click", () => {
                    destroy();
                    new StrongsInputModal(plugin, (n) => { void (async () => {
                        await writeDecision(plugin, notePath, verse, widx, "edit", n);
                        rerenderAfterMetadata(plugin, notePath);
                    })(); }).open();
                });
                btns.createEl("button", { text: "Not a match" })
                    .addEventListener("click", () => act(() => writeDecision(plugin, notePath, verse, widx, "reject")));
                if (!guess) btns.createEl("button", { text: "Revert to guess" })
                    .addEventListener("click", () => act(() => writeDecision(plugin, notePath, verse, widx, "clear")));
            }
        }
        if (seq !== buildSeq) return;                        // superseded while building — discard
        // Swap the finished card in (replaces any current card without an in-between empty state).
        removeCard();
        card = c; cardSpan = span;
        document.body.appendChild(c);
        const r = span.getBoundingClientRect();
        c.style.top = `${window.scrollY + r.bottom + 4}px`;
        c.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 320)}px`;
        c.addEventListener("mouseenter", () => { overCard = true; if (hideT) { window.clearTimeout(hideT); hideT = null; } });
        c.addEventListener("mouseleave", () => { overCard = false; scheduleHide(); });
    };

    const spanAt = (t: EventTarget | null): HTMLElement | null => {
        const el = t as HTMLElement | null;
        if (!el || !(el instanceof HTMLElement)) return null;
        const s = el.closest("span.lm-s") as HTMLElement | null;
        if (!s || !s.closest(".markdown-preview-view.bible, .markdown-reading-view.bible")) return null;
        return s;
    };
    const onCard = (t: EventTarget | null): boolean => !!card && (t === card || card.contains(t as Node));

    // Register BOTH — hover for desktop, tap/click for phone (and desktop click as a bonus). We don't
    // gate on Platform.isMobile because it's unreliable across environments; a touch device simply
    // never fires mouseover, and a desktop gets both. Tapping away dismisses.
    plugin.registerDomEvent(document, "click", (evt: MouseEvent) => {
        const s = spanAt(evt.target);
        if (s) { evt.preventDefault(); evt.stopPropagation(); if (dwell) { window.clearTimeout(dwell); dwell = null; } pending = null; void build(s); return; }
        if (card && !onCard(evt.target)) destroy();
    });
    // Hover chaining: `mousemove` (not `mouseover`) so we track what's under the cursor CONTINUOUSLY —
    // crossing the whitespace between two words no longer cancels the card. Over a word → (re)arm a short
    // dwell to open it; over a gap → do nothing to the pending open (you may be heading to the next word),
    // just arm a hide; over the card → keep it. Landing on a word cancels the hide.
    plugin.registerDomEvent(document, "mousemove", (evt: MouseEvent) => {
        const s = spanAt(evt.target);
        if (s) {
            if (hideT) { window.clearTimeout(hideT); hideT = null; }
            if (s === cardSpan) { pending = null; if (dwell) { window.clearTimeout(dwell); dwell = null; } return; }
            if (s === pending) return;                         // already armed for this word
            pending = s;
            if (dwell) window.clearTimeout(dwell);
            dwell = window.setTimeout(() => { dwell = null; pending = null; void build(s); }, 120);
            return;
        }
        if (onCard(evt.target)) { if (hideT) { window.clearTimeout(hideT); hideT = null; } return; }
        // A gap or empty space — arm a hide (cancelled if we reach a word), but DON'T cancel a pending open.
        if (card && !overCard && !hideT) scheduleHide();
    });
}

/** Wrap the (wordIndex)-th word of a verse <p> in a Strong's span (used by the overlay for pasted
 *  versions that have no baked tags). Uses the reader's word tokeniser so indices match the guess data.
 *  Wrapping doesn't change the verse's visible text, so processing words in any order stays consistent. */
function wrapWordSpan(p: HTMLElement, wordIndex: number, count: number, strong: string, guess: boolean, verse: number): boolean {
    const mark = (b: { node: Text; offset: number }, a: { node: Text; offset: number }): boolean => {
        if (b.node !== a.node || a.offset <= b.offset) return false;
        const mid = b.node.splitText(b.offset);
        mid.splitText(a.offset - b.offset);
        const span = document.createElement("span");
        span.className = guess ? "lm-s lm-s-guess" : "lm-s";
        span.setAttribute("data-s", strong);
        span.setAttribute("data-lm-verse", String(verse));
        span.setAttribute("data-lm-widx", String(wordIndex));   // the LINK's start word — its decision key
        span.setAttribute(guess ? "data-guess" : "data-approx", "1");
        mid.parentNode!.insertBefore(span, mid);
        span.appendChild(mid);
        return true;
    };
    const n = Math.max(1, count);
    // Preferred: one span over the WHOLE phrase, so several English words rendering one original word
    // read (and hover) as a single link.
    const b = wordEdgeInsertPoint(p, wordIndex, "before");
    const a = wordEdgeInsertPoint(p, wordIndex + n - 1, "after");
    if (b && a && mark(b, a)) return true;
    // Fallback (phrase straddles other markup, e.g. a red-letter boundary): tag each word of the phrase
    // separately with the same number — still correct, just not visually joined. Right-to-left so the
    // earlier words' offsets stay valid.
    let any = false;
    for (let k = n - 1; k >= 0; k--) {
        const bb = wordEdgeInsertPoint(p, wordIndex + k, "before");
        const aa = wordEdgeInsertPoint(p, wordIndex + k, "after");
        if (bb && aa && mark(bb, aa)) any = true;
    }
    return any;
}

/** Reader overlay: for a pasted (non-natively-tagged) version, wrap each word that the approximation
 *  engine linked to a Strong's number in an `lm-s` span — so the same hover/concordance the KJV & BSB
 *  enjoy works here too. Guessed links get `.lm-s-guess` (marked approximate); confirmed/edited ones
 *  render solid. Data comes from the guess sidecar merged with the note's confirm/edit/reject frontmatter. */
export function registerBibleStrongsOverlay(plugin: Plugin): void {
    plugin.registerMarkdownPostProcessor(async (el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        const path = ctx.sourcePath || "";
        if (!path.startsWith("bible/")) return;
        const parts = path.split("/");
        if (parts.length < 4) return;
        const book = parts[parts.length - 3].replace(/^\d+-/, "");
        const version = parts[parts.length - 2];
        const chapter = parseInt((parts[parts.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        if (!book || !version || !chapter || !BOOK_NUM[book] || isNativelyTagged(version)) return;

        const merged = await mergedTagsForChapter(plugin, book, version, chapter);
        if (!Object.keys(merged).length) return;

        const paras = Array.from(el.querySelectorAll("p")) as HTMLParagraphElement[];
        if (el.tagName === "P") paras.push(el as HTMLParagraphElement);
        for (const p of paras) {
            const s = p.firstElementChild;
            if (!(s && s.tagName === "STRONG" && /^\d+$/.test((s.textContent || "").trim()))) continue;
            if (p.hasAttribute("data-lm-strongs")) continue;
            p.setAttribute("data-lm-strongs", "1");
            const verse = (s.textContent || "").trim();
            const tags = merged[`${book}.${chapter}.${verse}`];
            if (!tags || !tags.length) continue;
            if (p.querySelector("span.lm-s")) continue;                 // already has baked/manual tags — don't double up
            for (const t of [...tags].sort((x, y) => y.w - x.w)) if (t.s) wrapWordSpan(p, t.w, t.n, t.s, t.guess, parseInt(verse, 10));
        }
    });
}

// ── Manually connect an English selection to an original word ────────────────
export type VerseSelection = { book: string; chapter: number; verse: number; w: number; n: number; text: string; notePath: string };

/** Map the current reading-view selection to a verse + word span, tokenised like the overlay so the word
 *  indices line up with the guess/decision data. Returns null if the selection isn't inside a Bible verse. */
function verseWordRangeFromSelection(plugin: Plugin): VerseSelection | null {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const range = sel.getRangeAt(0);
    const startEl = range.startContainer.nodeType === 3 ? range.startContainer.parentElement : (range.startContainer as Element);
    const p = startEl?.closest("p");
    if (!p || !p.closest(".markdown-reading-view, .markdown-preview-view")) return null;
    const numEl = p.firstElementChild;
    if (!(numEl && numEl.tagName === "STRONG" && /^\d+$/.test((numEl.textContent || "").trim()))) return null;
    const verse = parseInt((numEl.textContent || "").trim(), 10);
    const path = plugin.app.workspace.getActiveFile()?.path || "";
    const pp = path.split("/");
    const book = pp[pp.length - 3]?.replace(/^\d+-/, "") || "";
    const chapter = parseInt((pp[pp.length - 1]?.match(/-(\d+)\.md$/) || [])[1] || "", 10);
    if (!book || !chapter || !BOOK_NUM[book]) return null;

    const nodes: Text[] = []; let combined = "";
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, {
        acceptNode: (node: Node) => {
            const el = (node as Text).parentElement;
            if (!el) return NodeFilter.FILTER_REJECT;
            if (el.closest("sup")) return NodeFilter.FILTER_REJECT;
            if (el.tagName === "STRONG" && el === p.firstElementChild) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    for (let tn = walker.nextNode() as Text | null; tn; tn = walker.nextNode() as Text | null) { nodes.push(tn); combined += tn.nodeValue || ""; }
    const charOf = (node: Node, offset: number): number => {
        let acc = 0;
        for (const tn of nodes) { if (tn === node) return acc + offset; acc += (tn.nodeValue || "").length; }
        return -1;
    };
    let startChar = charOf(range.startContainer, range.startOffset);
    let endChar = charOf(range.endContainer, range.endOffset);
    if (startChar < 0) startChar = 0;
    if (endChar < 0) endChar = combined.length;
    if (endChar <= startChar) return null;

    const toks: { s: number; e: number }[] = []; const re = /\S+/g; let mm: RegExpExecArray | null;
    while ((mm = re.exec(combined))) toks.push({ s: mm.index, e: mm.index + mm[0].length });
    if (!toks.length) return null;
    let startW = toks.findIndex(t => t.e > startChar); if (startW < 0) startW = toks.length - 1;
    let endW = startW;
    for (let i = 0; i < toks.length; i++) { if (toks[i].s < endChar) endW = i; else break; }
    if (endW < startW) endW = startW;
    const w = startW, n = endW - startW + 1;
    const text = toks.slice(w, w + n).map(t => combined.slice(t.s, t.e)).join(" ");
    return { book, chapter, verse, w, n, text, notePath: path };
}

/** Modal: pick which ORIGINAL (Greek/Hebrew) word of the verse the English selection connects to. Shows
 *  each original word's manuscript form, morphology, lemma and gloss; picking one writes a manual link. */
class ConnectOriginalModal extends Modal {
    constructor(private plugin: Plugin, private data: StrongsData, private sel: VerseSelection) { super(plugin.app); }
    async onOpen(): Promise<void> {
        const { contentEl } = this;
        contentEl.addClass("lm-strongs-modal");
        const { book, chapter, verse, w, n, text, notePath } = this.sel;
        contentEl.createEl("h3", { text: "Connect to an original word" });
        contentEl.createEl("p", { cls: "setting-item-description" })
            .setText(`Selected “${text}” — ${bookLabel(book)} ${chapter}:${verse}. Choose the Hebrew/Greek word it renders.`);

        const commit = async (strong: string) => {
            this.close();
            await writeDecision(this.plugin, notePath, verse, w, "link", strong, n);
            rerenderAfterMetadata(this.plugin, notePath);
        };

        const originals = await this.data.verseOriginals(book, chapter, verse);
        if (originals.length) {
            const list = contentEl.createDiv("lm-connect-list");
            for (const o of originals) {
                const lex = (await this.data.lexicon(o.s))[o.s];
                const row = list.createEl("button", { cls: "lm-connect-row" });
                row.createSpan({ cls: "lm-connect-orig", text: o.o });
                if (o.m) row.createSpan({ cls: "lm-connect-morph", text: ` ${o.m}` });
                row.createSpan({ cls: "lm-connect-num", text: ` ${o.s}` });
                const gloss = lex?.g || lex?.d;
                if (gloss) row.createDiv({ cls: "lm-connect-gloss", text: gloss.length > 90 ? gloss.slice(0, 90) + "…" : gloss });
                row.addEventListener("click", () => void commit(o.s));
            }
        } else {
            contentEl.createEl("p", { cls: "setting-item-description",
                text: "No original-language text for this verse in the vault — type the Strong's number instead." });
        }
        const foot = contentEl.createDiv("lm-connect-foot");
        foot.createEl("button", { text: "Type a Strong's number…" })
            .addEventListener("click", () => new StrongsInputModal(this.plugin, (num) => void commit(num)).open());
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Command + entry point: connect the current reading-view selection to an original word. */
export function registerBibleConnectOriginal(plugin: Plugin): void {
    const data = new StrongsData(plugin);
    plugin.addCommand({
        id: "bible-connect-original",
        name: "Bible: connect selection to an original word",
        callback: () => {
            const sel = verseWordRangeFromSelection(plugin);
            if (!sel) { new Notice("Select the English word(s) in a Bible chapter first (reading view)."); return; }
            new ConnectOriginalModal(plugin, data, sel).open();
        },
    });
}
/** Used by the right-click menu to know whether to offer "connect selection". */
export function bibleSelectionForConnect(plugin: Plugin): VerseSelection | null {
    return verseWordRangeFromSelection(plugin);
}
export function openConnectOriginal(plugin: Plugin, sel: VerseSelection): void {
    new ConnectOriginalModal(plugin, new StrongsData(plugin), sel).open();
}

// Full grammatical terms → the compact abbreviations the SBLGNT morphology uses (so a user can type
// "aorist active participle" instead of "aor act ptcp").
const MORPH_ALIASES: Record<string, string> = {
    aorist: "aor", present: "pres", imperfect: "impf", future: "fut", perfect: "perf", pluperfect: "plup",
    active: "act", middle: "mid", passive: "pass",
    indicative: "ind", imperative: "impv", subjunctive: "subj", optative: "opt", infinitive: "inf",
    participle: "ptcp", participial: "ptcp",
    nominative: "nom", genitive: "gen", dative: "dat", accusative: "acc",
    singular: "sg", plural: "pl", masculine: "masc", feminine: "fem", neuter: "neut",
    adjective: "adj", adverb: "adv", first: "1", second: "2", third: "3",
};
const normMorph = (t: string): string => { const l = t.toLowerCase(); return MORPH_ALIASES[l] || l; };

/** Search the SBLGNT for a lemma / Strong's number, optionally filtered by grammatical form — the
 *  "find every aorist passive of ἀγαπάω" search that paid Bible software is known for. NT/Greek only. */
class MorphSearchModal extends Modal {
    constructor(private plugin: Plugin, private data: StrongsData) { super(plugin.app); }
    async onOpen(): Promise<void> {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Morphology search (SBLGNT)" });
        if (!(await this.data.sblgntAvailable())) {
            contentEl.createEl("p", { cls: "setting-item-description",
                text: "The SBLGNT data isn't in this vault yet, so morphology search is unavailable." });
            return;
        }
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Find New-Testament Greek words by Strong's number or lemma, filtered by grammatical form." });
        let key = "", morph = "";
        new Setting(contentEl).setName("Strong's or Greek lemma")
            .addText((t) => { t.setPlaceholder("e.g. G25 or ἀγαπάω").onChange((v) => key = v); setTimeout(() => t.inputEl.focus(), 0); });
        new Setting(contentEl).setName("Form (optional)")
            .setDesc("Tense / voice / mood / case / number — e.g. “aorist active”, “present participle”, “genitive plural”.")
            .addText((t) => { t.setPlaceholder("aorist active…").onChange((v) => morph = v); });
        const status = contentEl.createEl("p", { cls: "setting-item-description" });
        const results = contentEl.createDiv("lm-askbible-results");
        const run = async () => {
            const k = key.trim();
            if (!k) { status.setText("Enter a Strong's number (e.g. G25) or a Greek lemma."); return; }
            const strong = /^g?\d+$/i.test(k) ? "G" + k.replace(/^g/i, "") : "";
            const lemma = strong ? "" : k.toLowerCase();
            const filters = morph.trim().split(/\s+/).filter(Boolean).map(normMorph);
            status.setText("Searching…"); results.empty();
            const ntSlugs = Object.keys(BOOK_NUM).filter((s) => BOOK_NUM[s] >= 40).sort((a, b) => BOOK_NUM[a] - BOOK_NUM[b]);
            const hits: { slug: string; c: number; v: number; g: string; m: string }[] = [];
            for (const slug of ntSlugs) {
                const book = await this.data.sblgnt(slug);
                for (const [refKey, words] of Object.entries(book || {})) {
                    const parts = refKey.split("."); const v = +(parts.pop() || 0), c = +(parts.pop() || 0);
                    for (const w of words) {
                        const matchKey = strong ? w.s === strong : (w.l || "").toLowerCase().includes(lemma);
                        if (!matchKey) continue;
                        const mset = new Set((w.m || "").toLowerCase().split(" "));   // whole-token match ("pl" ≠ "plup")
                        if (filters.every((f) => mset.has(f))) hits.push({ slug, c, v, g: w.g, m: w.m });
                    }
                }
                if (hits.length > 600) break;
            }
            if (!hits.length) { status.setText("No matches — check the Strong's number/lemma and the form terms."); return; }
            status.setText(`${hits.length}${hits.length > 600 ? "+" : ""} occurrence${hits.length > 1 ? "s" : ""}:`);
            for (const h of hits.slice(0, 600)) {
                const num = BOOK_NUM[h.slug];
                const href = `bible/${pad2(num)}-${h.slug}/web/${h.slug}-${pad3(h.c)}#^v${h.v}`;
                const row = results.createDiv("lm-askbible-row");
                const a = row.createEl("a", { text: `${bookLabel(h.slug)} ${h.c}:${h.v}`, cls: "lm-askbible-ref", attr: { href } });
                a.addEventListener("click", (ev) => { ev.preventDefault(); this.plugin.app.workspace.openLinkText(href, "", ev.ctrlKey || ev.metaKey); this.close(); });
                const d = row.createDiv("lm-askbible-text");
                d.createSpan({ cls: "lm-interlinear-grk", text: h.g + "  " });
                d.createSpan({ cls: "lm-interlinear-morph", text: h.m });
            }
        };
        new Setting(contentEl).addButton((b) => b.setButtonText("Search").setCta().onClick(() => void run()));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the interlinear + concordance commands. */
export function registerBibleStrongs(plugin: Plugin): void {
    const data = new StrongsData(plugin);
    plugin.addCommand({
        id: "bible-interlinear",
        name: "Bible: interlinear (this chapter)",
        checkCallback: (checking: boolean) => {
            const ctx = activeBibleChapter(plugin);
            if (!ctx) return false;
            if (!checking) new InterlinearModal(plugin, data, ctx.book, ctx.chapter, ctx.version).open();
            return true;
        },
    });
    plugin.addCommand({
        id: "bible-concordance",
        name: "Bible: concordance (Strong's number or word)",
        callback: () => new ConcordanceModal(plugin, data).open(),
    });
    plugin.addCommand({
        id: "bible-morph-search",
        name: "Bible: morphology search (SBLGNT Greek)",
        callback: () => new MorphSearchModal(plugin, data).open(),
    });
}
