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
type Lexicon = Record<string, { l: string; t: string; g: string }>;

const DIR = "AI/bible-strongs";
const isGreek = (s: string) => s.charAt(0).toUpperCase() === "G";

/** Small cached JSON loaders for the sidecar data (each file read at most once). */
class StrongsData {
    private cache = new Map<string, Promise<any>>();
    constructor(private plugin: Plugin) {}
    private read<T>(file: string): Promise<T> {
        let p = this.cache.get(file);
        if (!p) {
            p = this.plugin.app.vault.adapter.read(`${DIR}/${file}`).then(s => JSON.parse(s)).catch(() => ({}));
            this.cache.set(file, p);
        }
        return p as Promise<T>;
    }
    interlinear(book: string) { return this.read<Interlinear>(`${book}.json`); }
    concordance(strong: string) { return this.read<Concordance>(`_concordance-${isGreek(strong) ? "G" : "H"}.json`); }
    lexicon(strong: string) { return this.read<Lexicon>(`_lexicon-${isGreek(strong) ? "G" : "H"}.json`); }
    words() { return this.read<Record<string, string[]>>("_words.json"); }
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
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "KJV word ↔ Strong's number. Tap a number for its Hebrew/Greek word, meaning, and every verse that uses it." });
        const inter = await this.data.interlinear(this.book);
        const body = contentEl.createDiv("lm-interlinear");
        const openConc = (s: string) => new ConcordanceModal(this.plugin, this.data, s).open();
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
    onClose(): void { this.contentEl.empty(); }
}

// ── Concordance: every verse that uses a Strong's number (or an English word → numbers) ──────
class ConcordanceModal extends Modal {
    constructor(private plugin: Plugin, private data: StrongsData, private initial = "") {
        super(plugin.app);
    }
    async onOpen(): Promise<void> {
        const { contentEl } = this;
        contentEl.addClass("lm-strongs-modal");
        contentEl.createEl("h3", { text: "Concordance" });
        let query = this.initial;
        const results = contentEl.createDiv("lm-concordance-results");
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
        const refs = (await this.data.concordance(strong))[strong] || [];
        el.createEl("div", { cls: "lm-concordance-count",
            text: `${refs.length} verse${refs.length === 1 ? "" : "s"}` + (refs.length > 400 ? " (showing first 400)" : "") });
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
            if (lex?.g) row.createDiv({ cls: "lm-strongs-gloss", text: lex.g.length > 160 ? lex.g.slice(0, 160) + "…" : lex.g });
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
}
