// LoreMaster — Bible Strong's study tools: a per-chapter INTERLINEAR panel and a CONCORDANCE search.
//
// Data is sidecar JSON under AI/bible-strongs/ (built by assistant_core/bible/tools/gen_strongs.py from
// the public-domain KJV+Strong's — the WEB's own USFM tags are corrupt). The WEB stays the reading
// text; this is a study overlay:
//   {book}.json          per-book interlinear: {"book.ch.v": [[phrase, [strongs]], ...]}
//   _concordance-H/G.json {strong: [refs]}   — every verse that uses a Strong's number
//   _words.json          KJV head-word -> [strongs]   (word-based concordance search)
//   _lexicon-H/G.json    {strong: {l: lemma, t: translit, g: gloss}}

import { Plugin, TFile, MarkdownView, Modal, Setting, Platform } from "obsidian";
import { BOOK_NUM, pad2, pad3, bookLabel } from "./bible";

type Interlinear = Record<string, [string, string[]][]>;
type Concordance = Record<string, string[]>;
type Lexicon = Record<string, { l: string; t: string; g: string; d?: string }>;
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
    async available(): Promise<boolean> {
        return this.plugin.app.vault.adapter.exists(`${DIR}/_words.json`).catch(() => false);
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
        let source: StudySource = getSource(this.plugin);
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

        if (origAvail || bsbAvail) {
            const origLabel = isNT ? "SBLGNT (Greek)" : "WLC (Hebrew)";
            new Setting(toolbar).setName("Text")
                .setDesc("Choose the basis: KJV/Strong's, the original text, or English glosses laid out in original word order.")
                .addDropdown(d => {
                    d.addOption("strongs", "KJV / Strong's (TR)");
                    if (origAvail) d.addOption(origKey, origLabel);
                    if (bsbAvail) d.addOption("bsb", "English ⟶ original order (BSB)");
                    d.setValue(source).onChange(async (v) => { source = v as StudySource; await setSource(this.plugin, source); await render(); });
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
    let card: HTMLElement | null = null;
    let overCard = false;
    let dwell: number | null = null;
    let hideT: number | null = null;
    let activeSpan: HTMLElement | null = null;

    const destroy = () => {
        if (dwell) { window.clearTimeout(dwell); dwell = null; }
        if (hideT) { window.clearTimeout(hideT); hideT = null; }
        card?.remove(); card = null; activeSpan = null; overCard = false;
    };
    const scheduleHide = () => {
        if (hideT) window.clearTimeout(hideT);
        hideT = window.setTimeout(() => { if (!overCard) destroy(); }, 200);
    };

    const build = async (span: HTMLElement) => {
        const codes = (span.getAttribute("data-s") || "").split(/\s+/).filter(Boolean);
        if (!codes.length) return;
        destroy();
        activeSpan = span;
        const c = document.body.createDiv("lm-strongs-pop");
        card = c;
        for (const s of codes) {
            const lex = (await data.lexicon(s))[s];
            if (span !== activeSpan) return;                 // moved away before load
            const row = c.createDiv("lm-strongs-pop-row");
            const head = row.createDiv("lm-strongs-pop-head");
            if (lex?.l) head.createSpan({ cls: "lm-strongs-lemma", text: lex.l });
            if (lex?.t) head.createSpan({ cls: "lm-strongs-translit", text: ` ${lex.t}` });
            head.createEl("a", { text: ` ${s}`, cls: "lm-strongs-num", href: "#" })
                .addEventListener("click", (e) => { e.preventDefault(); destroy(); new ConcordanceModal(plugin, data, s).open(); });
            // prefer the fuller free-lexicon definition (Dodson/BDB) — it is cleaner and more
            // accurate than the terse Strong's gloss; the full entry is one tap away.
            const meaning = lex?.d || lex?.g;
            if (meaning) row.createDiv({ cls: "lm-strongs-gloss", text: meaning.length > 160 ? meaning.slice(0, 160) + "…" : meaning });
        }
        c.createEl("a", { text: "Open Strong's entry →", cls: "lm-strongs-pop-open", href: "#" })
            .addEventListener("click", (e) => { e.preventDefault(); const s = codes[0]; destroy(); new ConcordanceModal(plugin, data, s).open(); });
        const r = span.getBoundingClientRect();
        c.style.top = `${window.scrollY + r.bottom + 4}px`;
        c.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 320)}px`;
        c.addEventListener("mouseenter", () => { overCard = true; });
        c.addEventListener("mouseleave", () => { overCard = false; scheduleHide(); });
    };

    const spanAt = (t: EventTarget | null): HTMLElement | null => {
        const el = t as HTMLElement | null;
        if (!el || !(el instanceof HTMLElement)) return null;
        const s = el.closest("span.lm-s") as HTMLElement | null;
        if (!s || !s.closest(".markdown-preview-view.bible, .markdown-reading-view.bible")) return null;
        return s;
    };

    // Register BOTH — hover for desktop, tap/click for phone (and desktop click as a bonus). We don't
    // gate on Platform.isMobile because it's unreliable across environments; a touch device simply
    // never fires mouseover, and a desktop gets both. Tapping away dismisses.
    plugin.registerDomEvent(document, "click", (evt: MouseEvent) => {
        const s = spanAt(evt.target);
        if (s) { evt.preventDefault(); evt.stopPropagation(); void build(s); return; }
        if (card && !card.contains(evt.target as Node)) destroy();
    });
    plugin.registerDomEvent(document, "mouseover", (evt: MouseEvent) => {
        const s = spanAt(evt.target);
        if (!s || s === activeSpan) return;
        if (dwell) window.clearTimeout(dwell);
        dwell = window.setTimeout(() => void build(s), 220);
        s.addEventListener("mouseleave", () => { if (dwell) { window.clearTimeout(dwell); dwell = null; } scheduleHide(); }, { once: true });
    });
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
