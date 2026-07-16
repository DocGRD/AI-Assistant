// LoreMaster — Bible study helpers (Phase 1 seed of the Phase 2 renderer).
//
// Right now this provides ONE thing: a hovercard for cross-reference links inside Bible notes
// (notes carrying `cssclasses: [bible]`). Obsidian's built-in Page Preview shows the target verse
// text but can't add a "Book chapter:verse" header — so hovering a marker shows only "11 …text".
// This card shows the reference label ("Matthew 1:11") + the verse text + Open / Open-in-new-tab.
//
// The `parseBibleRef` target→label parser and the hovercard are deliberately standalone so the
// Phase 2 custom renderer can reuse them.

import { Plugin, TFile } from "obsidian";

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
