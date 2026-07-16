// LoreMaster — Bible study helpers (Phase 1 seed of the Phase 2 renderer).
//
// Right now this provides ONE thing: a hovercard for cross-reference links inside Bible notes
// (notes carrying `cssclasses: [bible]`). Obsidian's built-in Page Preview shows the target verse
// text but can't add a "Book chapter:verse" header — so hovering a marker shows only "11 …text".
// This card shows the reference label ("Matthew 1:11") + the verse text + Open / Open-in-new-tab.
//
// The `parseBibleRef` target→label parser and the hovercard are deliberately standalone so the
// Phase 2 custom renderer can reuse them.

import { Plugin, TFile, MarkdownPostProcessorContext } from "obsidian";

// Book slug -> canonical number, for building cross-reference target paths (bible/{NN}-{slug}/...).
const BOOK_NUM: Record<string, number> = {
    "genesis":1,"exodus":2,"leviticus":3,"numbers":4,"deuteronomy":5,"joshua":6,"judges":7,"ruth":8,
    "1-samuel":9,"2-samuel":10,"1-kings":11,"2-kings":12,"1-chronicles":13,"2-chronicles":14,"ezra":15,
    "nehemiah":16,"esther":17,"job":18,"psalms":19,"proverbs":20,"ecclesiastes":21,"song-of-solomon":22,
    "isaiah":23,"jeremiah":24,"lamentations":25,"ezekiel":26,"daniel":27,"hosea":28,"joel":29,"amos":30,
    "obadiah":31,"jonah":32,"micah":33,"nahum":34,"habakkuk":35,"zephaniah":36,"haggai":37,"zechariah":38,
    "malachi":39,"matthew":40,"mark":41,"luke":42,"john":43,"acts":44,"romans":45,"1-corinthians":46,
    "2-corinthians":47,"galatians":48,"ephesians":49,"philippians":50,"colossians":51,"1-thessalonians":52,
    "2-thessalonians":53,"1-timothy":54,"2-timothy":55,"titus":56,"philemon":57,"hebrews":58,"james":59,
    "1-peter":60,"2-peter":61,"1-john":62,"2-john":63,"3-john":64,"jude":65,"revelation":66,
};
const SUP_LETTERS = "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ";
const XREF_SHOWN = 5;   // cross-references shown inline per verse (top by votes)

export type BibleLayout = "verses" | "flow";

/** Apply the reading layout globally. Plugin-owned (no user CSS snippet needed): a body class the
 *  shipped stylesheet keys on, so all `cssclasses:[bible]` notes render verse-by-verse or flowing. */
export function applyBibleLayout(mode: BibleLayout): void {
    document.body.toggleClass("lm-bible-flow", mode === "flow");
}

export interface BibleRef {
    label: string;          // e.g. "Matthew 1:11"
    linkpath: string;       // e.g. "AI/Library/matthew-web/matthew-1"
    block: string | null;   // e.g. "v11" (no leading ^), or null for a whole-chapter link
}

/** Turn a wikilink target into a human "Book chapter:verse" label.
 *  "AI/Library/matthew-web/matthew-1#^v11" → { label: "Matthew 1:11", linkpath, block: "v11" }.
 *  Filenames follow `<book-slug>-<chapter>` (e.g. song-of-solomon-3). Returns null if it doesn't. */
export function parseBibleRef(target: string): BibleRef | null {
    if (!target) return null;
    const [rawPath, frag] = target.split("#");
    const base = (rawPath.split("/").pop() || rawPath).replace(/\.md$/i, "");
    const m = base.match(/^(.+)-(\d+)$/);        // book-slug + chapter
    if (!m) return null;
    const book = m[1].split("-")
        .map(w => (w.length <= 2 && /^\d/.test(w)) ? w : w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
    let label = `${book} ${m[2]}`;
    let block: string | null = null;
    if (frag) {
        const vm = frag.match(/\^?v(\d+)/i);
        if (vm) { label += `:${vm[1]}`; block = `v${vm[1]}`; }
    }
    return { label, linkpath: rawPath, block };
}

/** Pull a single verse's clean reading text out of a chapter note by its block anchor. */
async function readVerseText(plugin: Plugin, linkpath: string, block: string | null): Promise<string> {
    const file = plugin.app.metadataCache.getFirstLinkpathDest(linkpath, "");
    if (!(file instanceof TFile)) return "";
    if (!block) return "";
    const content = await plugin.app.vault.cachedRead(file);
    const anchor = ` ^${block}`;                 // block anchors sit at the end of the verse line
    let line = "";
    for (const raw of content.split(/\r?\n/)) {  // split by line — robust to CRLF (`.` skips \r)
        const trimmed = raw.replace(/\s+$/, "");
        if (trimmed.endsWith(anchor)) { line = trimmed.slice(0, -anchor.length); break; }
    }
    if (!line) return "";
    return line
        .replace(/^\*\*\d+\*\*\s*/, "")             // drop the leading **verse-number**
        .replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, "")  // drop cross-ref wikilinks (markers only)
        .replace(/\[\[[^\]]*\]\]/g, "")
        // drop leftover superscript marker glyphs (the exact set we emit — safe, prose never uses them)
        .replace(/[ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ⁰¹²³⁴⁵⁶⁷⁸⁹]/g, "")
        .replace(/\s{2,}/g, " ")
        .trim();
}

/** Register the Bible cross-reference hovercard (reading view). Safe to call once from onload. */
export function registerBibleHovercards(plugin: Plugin): void {
    let card: HTMLElement | null = null;
    let overCard = false;
    let hideTimer: number | null = null;
    let activeAnchor: HTMLElement | null = null;

    const destroy = () => {
        if (hideTimer) { window.clearTimeout(hideTimer); hideTimer = null; }
        card?.remove();
        card = null;
        activeAnchor = null;
        overCard = false;
    };
    const scheduleHide = () => {
        if (hideTimer) window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(() => { if (!overCard) destroy(); }, 180);
    };

    plugin.registerDomEvent(document, "mouseover", async (evt: MouseEvent) => {
        const t = evt.target as HTMLElement | null;
        if (!t || !(t instanceof HTMLElement)) return;
        const a = t.closest("a.internal-link") as HTMLElement | null;
        if (!a) return;
        if (!a.closest(".markdown-preview-view.bible, .markdown-reading-view.bible")) return;
        if (a === activeAnchor && card) return;   // already showing this one

        const target = a.getAttribute("data-href") || a.getAttribute("href") || "";
        const ref = parseBibleRef(target);
        if (!ref) return;

        destroy();
        activeAnchor = a;
        const text = await readVerseText(plugin, ref.linkpath, ref.block);
        if (a !== activeAnchor) return;           // moved off before the read finished

        card = document.body.createDiv("loremaster-bible-hovercard");
        card.createDiv("loremaster-bible-hovercard-ref").setText(ref.label);
        if (text) card.createDiv("loremaster-bible-hovercard-text").setText(text);
        const actions = card.createDiv("loremaster-bible-hovercard-actions");
        const openIn = (newLeaf: boolean) =>
            plugin.app.workspace.openLinkText(target, "", newLeaf);
        actions.createEl("button", { text: "Open" })
            .addEventListener("click", () => { openIn(false); destroy(); });
        actions.createEl("button", { text: "Open in new tab" })
            .addEventListener("click", () => { openIn(true); destroy(); });

        const r = a.getBoundingClientRect();
        card.style.top = `${window.scrollY + r.bottom + 6}px`;
        card.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 320)}px`;

        card.addEventListener("mouseenter", () => { overCard = true; });
        card.addEventListener("mouseleave", () => { overCard = false; scheduleHide(); });
        a.addEventListener("mouseleave", scheduleHide, { once: true });
    });
}

const pad2 = (n: number) => String(n).padStart(2, "0");
const pad3 = (n: number) => String(n).padStart(3, "0");

/** Register the cross-reference OVERLAY: cross-refs are stored once (bible/.crossrefs/{book}.json,
 *  version-independent) and injected by the renderer, so every version shares them and adding a
 *  version repeats no cross-reference work. Runs on `cssclasses:[bible]` chapter notes. */
export function registerBibleCrossrefs(plugin: Plugin): void {
    const cache = new Map<string, Promise<Record<string, any[]>>>();
    const loadBook = (book: string): Promise<Record<string, any[]>> => {
        let p = cache.get(book);
        if (!p) {
            p = plugin.app.vault.adapter.read(`AI/bible-crossrefs/${book}.json`)
                .then(s => JSON.parse(s)).catch(() => ({}));
            cache.set(book, p);
        }
        return p;
    };

    plugin.registerMarkdownPostProcessor(async (el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        // Derive book/chapter/version from the note PATH (robust — no dependency on frontmatter
        // being cached yet): bible/{NN}-{slug}/{version}/{slug}-{CCC}.md
        const path = ctx.sourcePath || "";
        if (!path.startsWith("bible/")) return;
        const parts = path.split("/");
        if (parts.length < 4) return;
        const book = parts[parts.length - 3].replace(/^\d+-/, "");
        const version = parts[parts.length - 2];
        const chapter = parseInt((parts[parts.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        if (!book || !version || !chapter) return;

        // Obsidian may hand us the container OR a bare <p>; collect both so we never miss a verse.
        const paras = Array.from(el.querySelectorAll("p")) as HTMLParagraphElement[];
        if (el.tagName === "P") paras.push(el as HTMLParagraphElement);
        const verses = paras.filter(p => {
            const s = p.firstElementChild;
            return s && s.tagName === "STRONG" && /^\d+$/.test((s.textContent || "").trim())
                && !p.hasAttribute("data-lm-xref");
        });
        if (!verses.length) return;
        const data = await loadBook(book);

        for (const p of verses) {
            p.setAttribute("data-lm-xref", "1");
            const vnum = (p.firstElementChild!.textContent || "").trim();
            const targets = data[`${book}.${chapter}.${vnum}`];
            if (!targets || !targets.length) continue;
            for (let i = 0; i < Math.min(targets.length, XREF_SHOWN); i++) {
                const t = targets[i];
                const num = BOOK_NUM[t.b];
                if (!num) continue;
                const href = `bible/${pad2(num)}-${t.b}/${version}/${t.b}-${pad3(t.c)}#^v${t.v}`;
                const sup = p.createEl("sup");
                sup.appendText(" ");
                const a = sup.createEl("a", {
                    text: SUP_LETTERS[i] || "*",
                    cls: "internal-link lm-xref",
                    attr: { "data-href": href, href, "aria-label": t.n },
                });
                a.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    plugin.app.workspace.openLinkText(href, ctx.sourcePath, ev.ctrlKey || ev.metaKey);
                });
            }
        }
    });
}
