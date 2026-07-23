// LoreMaster — Bible study helpers (Phase 1 seed of the Phase 2 renderer).
//
// Right now this provides ONE thing: a hovercard for cross-reference links inside Bible notes
// (notes carrying `cssclasses: [bible]`). Obsidian's built-in Page Preview shows the target verse
// text but can't add a "Book chapter:verse" header — so hovering a marker shows only "11 …text".
// This card shows the reference label ("Matthew 1:11") + the verse text + Open / Open-in-new-tab.
//
// The `parseBibleRef` target→label parser and the hovercard are deliberately standalone so the
// Phase 2 custom renderer can reuse them.

import { Plugin, TFile, MarkdownView, MarkdownPostProcessorContext, Modal, Setting, Notice, Platform, Menu, Editor } from "obsidian";
import { commentaryNotesForVerse, mhcNoteFor } from "./bible-commentary";
import { alignAfterPaste, isNativelyTagged } from "./bible-align";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** An AbortSignal that fires after `ms`. `AbortSignal.timeout` is missing on some mobile WebViews —
 *  calling it there throws, so fall back to a controller. Never throws (returns undefined if even
 *  that fails), so a fetch's option object can't blow up the caller synchronously. This matters:
 *  the Bible cross-ref post-processor `await`s a backend fetch, and a synchronous throw here used
 *  to abort the whole processor → NO cross-reference markers rendered on the phone. */
export function timeoutSignal(ms: number): AbortSignal | undefined {
    try {
        const anyAS = AbortSignal as unknown as { timeout?: (ms: number) => AbortSignal };
        if (typeof AbortSignal !== "undefined" && typeof anyAS.timeout === "function") return anyAS.timeout(ms);
        const c = new AbortController();
        setTimeout(() => c.abort(), ms);
        return c.signal;
    } catch { return undefined; }
}

// Book slug -> canonical number, for building cross-reference target paths (bible/{NN}-{slug}/...).
export const BOOK_NUM: Record<string, number> = {
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
const UP_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";   // labels for word-connected cross-references (uppercase)

export type BibleLayout = "verses" | "flow";

/** Apply the reading layout globally. Plugin-owned (no user CSS snippet needed): a body class the
 *  shipped stylesheet keys on, so all `cssclasses:[bible]` notes render verse-by-verse or flowing. */
export function applyBibleLayout(mode: BibleLayout): void {
    document.body.toggleClass("lm-bible-flow", mode === "flow");
}

/** Reader text size. Sets a CSS variable the `.bible` stylesheet multiplies its font-size by, so the
 *  user can scale Bible reading text (80–160%) without touching Obsidian's global font size. */
export function applyBibleFontScale(percent: number): void {
    const clamped = Math.max(80, Math.min(200, Math.round(percent || 100)));
    document.body.style.setProperty("--lm-bible-font-scale", String(clamped / 100));
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
    let label = `${book} ${parseInt(m[2], 10)}`;   // strip leading zeros ("021" → "21")
    let block: string | null = null;
    if (frag) {
        const vm = frag.match(/\^?v(\d+)/i);
        if (vm) { label += `:${parseInt(vm[1], 10)}`; block = `v${parseInt(vm[1], 10)}`; }
    }
    return { label, linkpath: rawPath, block };
}

/** Pull a single verse's clean reading text out of a chapter note by its block anchor. */
export async function readVerseText(plugin: Plugin, linkpath: string, block: string | null): Promise<string> {
    const file = plugin.app.metadataCache.getFirstLinkpathDest(linkpath, "");
    if (!(file instanceof TFile)) return "";
    if (!block) return "";
    const content = await plugin.app.vault.cachedRead(file);
    const anchor = ` ^${block}`;                 // block anchors sit at the end of the verse's last line
    const lines = content.split(/\r?\n/).map(l => l.replace(/\s+$/, ""));  // CRLF-safe
    const end = lines.findIndex(l => l.endsWith(anchor));
    if (end < 0) return "";
    // A verse may span several lines (poetry stichs); walk back to its **number** so the card shows
    // the WHOLE verse, not just the last stich.
    let start = end;
    while (start > 0 && !/^\*\*\d+\*\*/.test(lines[start])) start--;
    return lines.slice(start, end + 1).join(" ")
        .replace(/\s*\^v\d+/g, "")                  // drop the block anchor (safe — prose has no ^vN)
        .replace(/^\*\*\d+\*\*\s*/, "")             // drop the leading **verse-number**
        .replace(/<\/?span[^>]*>/g, "")             // drop red-letter spans
        .replace(/ /g, "")                     // drop poetry em-space indents
        .replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, "")  // drop cross-ref wikilinks (markers only)
        .replace(/\[\[[^\]]*\]\]/g, "")
        .replace(/[ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ⁰¹²³⁴⁵⁶⁷⁸⁹]/g, "")   // leftover superscript markers
        .replace(/\s{2,}/g, " ")
        .trim();
}

/** Like readVerseText but PRESERVES the red-letter/Strong's `<span>`s, for the flowing passage embed
 *  (which reconstructs them via DOM). Strips only the verse number, block anchor, poetry indents, and
 *  cross-reference marker wikilinks. */
export async function readVerseRaw(plugin: Plugin, linkpath: string, block: string | null): Promise<string> {
    const file = plugin.app.metadataCache.getFirstLinkpathDest(linkpath, "");
    if (!(file instanceof TFile) || !block) return "";
    const content = await plugin.app.vault.cachedRead(file);
    const anchor = ` ^${block}`;
    const lines = content.split(/\r?\n/).map(l => l.replace(/\s+$/, ""));
    const end = lines.findIndex(l => l.endsWith(anchor));
    if (end < 0) return "";
    let start = end;
    while (start > 0 && !/^\*\*\d+\*\*/.test(lines[start])) start--;
    // Keep each stich as its own line (poetry keeps its shape) and keep the leading em-space indents —
    // the passage renderer turns \n into <br> and the em-spaces render as the poetic indent. A prose
    // verse is a single line and just flows.
    return lines.slice(start, end + 1).join("\n")
        .replace(/[ \t]*\^v\d+/g, "")               // block anchor (spaces/tabs only, not the newline)
        .replace(/^\*\*\d+\*\*[ \t]*/, "")          // drop the leading **verse-number** (span text kept)
        .replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, "")  // strip cross-ref wikilink markers
        .replace(/\[\[[^\]]*\]\]/g, "")
        .replace(/[ \t]{2,}/g, " ")                 // collapse space runs (NOT newlines, NOT em-spaces)
        .trim();
}

// ── Shared cross-ref / embedding hovercard ──────────────────────────────────
// One card at a time. Used by BOTH desktop hover (mouseover) and mobile tap (a marker's click
// handler), so on the phone a tap opens the card to READ — with an Open button — instead of
// immediately navigating away.
let hcCard: HTMLElement | null = null;
let hcOverCard = false;
let hcHideTimer: number | null = null;
let hcActiveAnchor: HTMLElement | null = null;

function hcDestroy(): void {
    if (hcHideTimer) { window.clearTimeout(hcHideTimer); hcHideTimer = null; }
    hcCard?.remove();
    hcCard = null;
    hcActiveAnchor = null;
    hcOverCard = false;
}
function hcScheduleHide(): void {
    if (hcHideTimer) window.clearTimeout(hcHideTimer);
    hcHideTimer = window.setTimeout(() => { if (!hcOverCard) hcDestroy(); }, 180);
}

/** A small popup listing several cross-references pinned to the SAME word — shown when a collapsed
 *  multi-marker is tapped/hovered. Each item opens its read-card. Reuses the single-card slot. */
function showWordRefList(plugin: Plugin, anchor: HTMLElement,
                        refs: { b: string; c: number; v: number }[], hrefFor: (t: any) => string): void {
    hcDestroy();
    // Use the styled hovercard base (`loremaster-bible-hovercard` — position/background/border/shadow);
    // the old `lm-bible-hovercard` class had NO CSS, so the list flowed unstyled to the page bottom and
    // only its heading showed (looked like a bare "N cross-references" notice).
    const card = document.body.createDiv("loremaster-bible-hovercard lm-wordref-list");
    hcCard = card; hcActiveAnchor = anchor;
    card.createDiv("lm-wordref-list-head").setText(`${refs.length} cross-references`);
    for (const t of refs) {
        const href = hrefFor(t);
        const a = card.createEl("a", { text: `${bookLabel(t.b)} ${t.c}:${t.v}`, cls: "lm-wordref-item", attr: { href } });
        a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); hcDestroy(); void showBibleHovercard(plugin, anchor, href); });
    }
    const r = anchor.getBoundingClientRect();
    card.style.top = `${window.scrollY + r.bottom + 4}px`;
    card.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 240)}px`;
    card.addEventListener("mouseenter", () => { hcOverCard = true; });
    card.addEventListener("mouseleave", () => { hcOverCard = false; hcScheduleHide(); });
    setTimeout(() => {
        const off = (ev: Event) => { if (!card.contains(ev.target as Node)) { hcDestroy(); document.removeEventListener("pointerdown", off, true); } };
        document.addEventListener("pointerdown", off, true);
    }, 0);
}

/** Build + position the hovercard for a marker anchor. `target` is the verse link (data-href). */
async function showBibleHovercard(plugin: Plugin, anchor: HTMLElement, target: string): Promise<void> {
    const ref = parseBibleRef(target);
    if (!ref) return;
    if (anchor === hcActiveAnchor && hcCard) return;   // already showing this one

    hcDestroy();
    hcActiveAnchor = anchor;
    let text = await readVerseText(plugin, ref.linkpath, ref.block);
    let openTarget = target;
    let note = "";
    if (!text && !/\/web\//.test(ref.linkpath)) {
        // Couldn't read the verse in this translation — fall back to the complete World English Bible.
        // Distinguish WHY: if the version's chapter note exists in the vault but this verse is absent,
        // the translation genuinely omits it ("not in this translation"); if we don't have that
        // version/chapter at all, it's only an availability gap ("not available in this translation").
        const parts = ref.linkpath.split("/");
        if (parts.length >= 4) {
            parts[parts.length - 2] = "web";
            const webPath = parts.join("/");
            const webText = await readVerseText(plugin, webPath, ref.block);
            if (webText) {
                text = webText;
                openTarget = ref.block ? `${webPath}#^${ref.block}` : webPath;
                const versionChapterExists =
                    plugin.app.metadataCache.getFirstLinkpathDest(ref.linkpath, "") instanceof TFile;
                note = versionChapterExists
                    ? "Shown from the World English Bible — this verse is not in this translation."
                    : "Shown from the World English Bible — not available in this translation.";
            }
        }
    }
    if (anchor !== hcActiveAnchor) return;             // moved off before the read finished

    const card = document.body.createDiv("loremaster-bible-hovercard");
    hcCard = card;
    const refRow = card.createDiv("loremaster-bible-hovercard-ref");
    refRow.createSpan({ text: ref.label });
    refRow.createEl("button", { text: "×", cls: "loremaster-bible-hovercard-close", attr: { "aria-label": "Close" } })
        .addEventListener("click", (e) => { e.stopPropagation(); hcDestroy(); });
    if (text) card.createDiv("loremaster-bible-hovercard-text").setText(text);
    else card.createDiv("loremaster-bible-hovercard-note").setText("(verse text not available in this translation)");
    if (note) card.createDiv("loremaster-bible-hovercard-note").setText(note);
    const actions = card.createDiv("loremaster-bible-hovercard-actions");
    const openIn = (newLeaf: boolean) => plugin.app.workspace.openLinkText(openTarget, "", newLeaf);
    actions.createEl("button", { text: "Open" })
        .addEventListener("click", () => { openIn(false); hcDestroy(); });
    actions.createEl("button", { text: "Open in new tab" })
        .addEventListener("click", () => { openIn(true); hcDestroy(); });

    const r = anchor.getBoundingClientRect();
    card.style.top = `${window.scrollY + r.bottom + 6}px`;
    card.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 320)}px`;

    card.addEventListener("mouseenter", () => { hcOverCard = true; });
    card.addEventListener("mouseleave", () => { hcOverCard = false; hcScheduleHide(); });
    // Dismiss by tapping/clicking anywhere outside the card (all platforms — mobile has no mouseleave,
    // and a card spawned from the verse-number panel on desktop has no hover relationship either).
    setTimeout(() => {
        const dismiss = (ev: Event) => {
            const n = ev.target as Node;
            if (card.contains(n) || anchor.contains(n)) return;     // taps on the card/anchor keep it
            card.remove();
            if (hcCard === card) hcCard = null;
            document.removeEventListener("pointerdown", dismiss, true);
            document.removeEventListener("click", dismiss, true);
        };
        document.addEventListener("pointerdown", dismiss, true);
        document.addEventListener("click", dismiss, true);
    }, 0);
}

/** True when a marker tap should OPEN THE CARD rather than navigate (mobile — so you can read the
 *  verse and press Open). On desktop, hover shows the card and click navigates as before. */
function markerTapOpensCard(): boolean {
    return Platform.isMobile;
}

/** Register the Bible cross-reference hovercard (reading view, desktop hover). */
export function registerBibleHovercards(plugin: Plugin): void {
    plugin.registerDomEvent(document, "mouseover", async (evt: MouseEvent) => {
        const t = evt.target as HTMLElement | null;
        if (!t || !(t instanceof HTMLElement)) return;
        const a = t.closest("a.lm-xref, a.lm-embed-vlink") as HTMLElement | null;   // cross-ref + embedding markers (not nav links)
        if (!a) return;
        if (!a.closest(".markdown-preview-view.bible, .markdown-reading-view.bible")) return;
        const target = a.getAttribute("data-href") || a.getAttribute("href") || "";
        await showBibleHovercard(plugin, a, target);
        a.addEventListener("mouseleave", hcScheduleHide, { once: true });
    });
}

export const pad2 = (n: number) => String(n).padStart(2, "0");
export const pad3 = (n: number) => String(n).padStart(3, "0");

/** book-slug → display name ("1-corinthians" → "1 Corinthians"). */
export function bookLabel(slug: string): string {
    return slug.split("-")
        .map(w => (w.length <= 2 && /^\d/.test(w)) ? w : w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
}

// ── Word-anchored cross-references ──────────────────────────────────────────
// By default a verse's cross-reference markers cluster at the END of the verse. You can instead pin a
// specific reference right AFTER the word it relates to: the association (verse + target → word index)
// is stored in the note's `bible-xref-anchors` frontmatter and the reader places that marker inline.

/** Find the DOM text-node + local offset at the leading ("before") or trailing ("after") edge of the
 *  (wordIndex)-th whitespace word inside a verse <p>, skipping the leading verse-number <strong> and any
 *  existing <sup> markers. Tokenises the CONCATENATION of the accepted text nodes — not each node
 *  separately — so word boundaries match readVerseText (which strips spans). Otherwise a <span>
 *  (Strong's tag / red-letter) splits a word and its trailing punctuation into two tokens and drifts. */
export function wordEdgeInsertPoint(p: HTMLElement, wordIndex: number,
                            edge: "before" | "after"): { node: Text; offset: number } | null {
    const nodes: Text[] = [];
    let combined = "";
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, {
        acceptNode: (node: Node) => {
            const el = (node as Text).parentElement;
            if (!el) return NodeFilter.FILTER_REJECT;
            if (el.closest("sup")) return NodeFilter.FILTER_REJECT;                       // existing markers
            if (el.tagName === "STRONG" && el === p.firstElementChild) return NodeFilter.FILTER_REJECT;  // verse number
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    for (let tn = walker.nextNode() as Text | null; tn; tn = walker.nextNode() as Text | null) {
        nodes.push(tn); combined += tn.nodeValue || "";
    }
    let target = -1, count = 0, m: RegExpExecArray | null;
    const re = /\S+/g;
    while ((m = re.exec(combined))) {
        if (count === wordIndex) { target = edge === "before" ? m.index : m.index + m[0].length; break; }
        count++;
    }
    if (target < 0) return null;
    let acc = 0;
    for (const node of nodes) {
        const len = (node.nodeValue || "").length;
        if (target <= acc + len) return { node, offset: target - acc };
        acc += len;
    }
    return null;
}

/** Insert `marker` right AFTER the (wordIndex)-th word. Returns false if the word isn't found. */
function placeMarkerAfterWord(p: HTMLElement, wordIndex: number, marker: HTMLElement): boolean {
    const pt = wordEdgeInsertPoint(p, wordIndex, "after");
    if (!pt) return false;
    const tail = pt.node.splitText(pt.offset);
    tail.parentNode!.insertBefore(marker, tail);
    return true;
}

/** Insert `marker` right BEFORE the (wordIndex)-th word (used for user-connected cross-references,
 *  which sit at the front of the word they explain). Returns false if the word isn't found. */
function placeMarkerBeforeWord(p: HTMLElement, wordIndex: number, marker: HTMLElement): boolean {
    const pt = wordEdgeInsertPoint(p, wordIndex, "before");
    if (!pt) return false;
    const tail = pt.node.splitText(pt.offset);
    tail.parentNode!.insertBefore(marker, tail);
    return true;
}

/** Split a stored anchor target ("john.3.16" / "1-john.4.7") into { b: slug, c, v }. */
function splitAnchorTarget(target: string): { b: string; c: number; v: number } | null {
    const m = target.match(/^(.+)\.(\d+)\.(\d+)$/);
    return m ? { b: m[1], c: parseInt(m[2], 10), v: parseInt(m[3], 10) } : null;
}

/** Parse a free-text reference the user types ("John 3:16", "1 John 4:7", "Song of Solomon 2:1")
 *  into { b: slug, c, v }. Returns null if the book isn't recognised or the chapter/verse is missing. */
function parseRefInput(text: string): { b: string; c: number; v: number } | null {
    const m = (text || "").trim().match(/^(.+?)\s+(\d+)\s*[:.]\s*(\d+)$/);
    if (!m) return null;
    const slug = m[1].trim().toLowerCase().replace(/\s+/g, "-");
    if (!BOOK_NUM[slug]) return null;
    return { b: slug, c: parseInt(m[2], 10), v: parseInt(m[3], 10) };
}

/** Group the word-connected cross-references by verse: verse-string → [{ target, wordIndex }] in order. */
function xrefAnchorsByVerse(fm: any): Map<string, { target: string; wordIndex: number }[]> {
    const out = new Map<string, { target: string; wordIndex: number }[]>();
    const raw = fm?.["bible-xref-anchors"];
    for (const s of Array.isArray(raw) ? raw : []) {
        const m = String(s).match(/^(\d+):(\d+):(.+)$/);
        if (!m) continue;
        const list = out.get(m[1]) ?? [];
        list.push({ target: m[3], wordIndex: parseInt(m[2], 10) });
        out.set(m[1], list);
    }
    return out;
}

async function writeXrefAnchor(plugin: Plugin, notePath: string, verse: number,
                               target: string, wordIndex: number | null): Promise<void> {
    const file = plugin.app.vault.getAbstractFileByPath(notePath);
    if (!(file instanceof TFile)) return;
    await plugin.app.fileManager.processFrontMatter(file, (fm: any) => {
        const arr: string[] = Array.isArray(fm["bible-xref-anchors"]) ? fm["bible-xref-anchors"].map(String) : [];
        // drop any existing placement for this verse+target, then (unless clearing) add the new one
        const kept = arr.filter(s => !(s.startsWith(`${verse}:`) && s.endsWith(`:${target}`)));
        if (wordIndex != null) kept.push(`${verse}:${wordIndex}:${target}`);
        if (kept.length) fm["bible-xref-anchors"] = kept;
        else delete fm["bible-xref-anchors"];
    });
}

/** Parse `bible-xref-hidden` (list of "verse:tb.tc.tv") into a Set of "verse:tb.tc.tv" keys. A hidden
 *  reference (auto cross-reference or related-by-meaning link) is dropped from the inline markers. */
function xrefHiddenSet(fm: any): Set<string> {
    const out = new Set<string>();
    for (const s of Array.isArray(fm?.["bible-xref-hidden"]) ? fm["bible-xref-hidden"] : []) out.add(String(s));
    return out;
}

/** Hide (or restore) a reference for a verse — writes/removes its "verse:tb.tc.tv" key in the note's
 *  `bible-xref-hidden` frontmatter. Used to remove auto cross-references and related-by-meaning links. */
async function writeXrefHidden(plugin: Plugin, notePath: string, key: string, hide: boolean): Promise<void> {
    const file = plugin.app.vault.getAbstractFileByPath(notePath);
    if (!(file instanceof TFile)) return;
    await plugin.app.fileManager.processFrontMatter(file, (fm: any) => {
        const arr: string[] = Array.isArray(fm["bible-xref-hidden"]) ? fm["bible-xref-hidden"].map(String) : [];
        const kept = arr.filter(s => s !== key);
        if (hide) kept.push(key);
        if (kept.length) fm["bible-xref-hidden"] = kept;
        else delete fm["bible-xref-hidden"];
    });
}

/** Force the active reading view to re-run post-processors so a placement change shows immediately. */
function rerenderActivePreview(plugin: Plugin): void {
    const view = plugin.app.workspace.getActiveViewOfType(MarkdownView);
    (view as any)?.previewMode?.rerender?.(true);
}

/** Re-render the reader AFTER the note's metadata cache reflects a frontmatter write, so anchor/hide
 *  changes show on the first render (writing frontmatter updates the cache asynchronously, so an
 *  immediate re-render would read the stale cache). Falls back to a short timeout if no event fires. */
export function rerenderAfterMetadata(plugin: Plugin, notePath: string): void {
    const file = plugin.app.vault.getAbstractFileByPath(notePath);
    if (!(file instanceof TFile)) { rerenderActivePreview(plugin); return; }
    let fired = false;
    const finish = () => { if (fired) return; fired = true; plugin.app.metadataCache.offref(ref); rerenderActivePreview(plugin); };
    const ref = plugin.app.metadataCache.on("changed", (f) => { if (f.path === file.path) finish(); });
    setTimeout(finish, 500);
}

/** Apply the user's per-type cross-reference styling (colour + relative size) as CSS variables on
 *  <body>, so the reader's markers pick them up. Empty colour → the theme default (CSS fallback). */
export function applyBibleXrefStyles(s: any): void {
    const body = document.body.style;
    const setCol = (name: string, v: any) => {
        if (typeof v === "string" && v.trim()) body.setProperty(name, v.trim());
        else body.removeProperty(name);
    };
    const setScale = (name: string, v: any) => body.setProperty(name, String((Number(v) || 100) / 100));
    setCol("--lm-xref-color", s?.bibleXrefColor);
    setCol("--lm-embed-color", s?.bibleEmbedColor);
    setCol("--lm-wordxref-color", s?.bibleWordXrefColor);
    setScale("--lm-xref-scale", s?.bibleXrefScale);
    setScale("--lm-embed-scale", s?.bibleEmbedScale);
    setScale("--lm-wordxref-scale", s?.bibleWordXrefScale);
}

/** Modal: pick (or change) which word of a verse a cross-reference is connected to — its marker sits
 *  at the front of that word. Also lets you remove the word connection. */
class WordAnchorModal extends Modal {
    constructor(private plugin: Plugin, private notePath: string, private verse: number,
                private verseText: string, private target: string, private targetLabel: string) {
        super(plugin.app);
    }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: `Connect “${this.targetLabel}” to a word` });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: `Verse ${this.verse}. Click the word this cross-reference relates to — its marker will sit at the front of it.` });
        const box = contentEl.createDiv("lm-wordpick");
        const words = this.verseText.split(/\s+/).filter(Boolean);
        words.forEach((w, i) => {
            const chip = box.createEl("button", { text: w, cls: "lm-wordpick-chip" });
            chip.addEventListener("click", async () => {
                await writeXrefAnchor(this.plugin, this.notePath, this.verse, this.target, i);
                new Notice(`Cross-reference placed at “${w}”.`);
                this.close();
                rerenderAfterMetadata(this.plugin, this.notePath);
            });
        });
        new Setting(contentEl).addButton(b => b.setButtonText("Remove this word connection").onClick(async () => {
            await writeXrefAnchor(this.plugin, this.notePath, this.verse, this.target, null);
            this.close();
            rerenderAfterMetadata(this.plugin, this.notePath);
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Modal: add YOUR OWN cross-reference — any reference, even one not in the list — and connect it to a
 *  word in the verse. Step 1: type the reference; step 2: click the word it belongs in front of. */
class AddWordXrefModal extends Modal {
    constructor(private plugin: Plugin, private notePath: string, private verse: number,
                private verseText: string) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Add your own cross-reference" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: `Verse ${this.verse}. Type the reference this points to (e.g. “John 3:16”, “1 John 4:7”), then choose the word.` });
        let ref = "";
        const refInput = new Setting(contentEl).setName("Reference")
            .addText(t => { t.setPlaceholder("Book chapter:verse").onChange(v => ref = v); });
        const status = contentEl.createEl("p", { cls: "setting-item-description" });
        const pickWrap = contentEl.createDiv();
        const toPick = () => {
            const parsed = parseRefInput(ref);
            if (!parsed) { status.setText("Couldn't read that — try like “John 3:16” or “1 John 4:7”."); return; }
            const target = `${parsed.b}.${parsed.c}.${parsed.v}`;
            status.setText(`${bookLabel(parsed.b)} ${parsed.c}:${parsed.v} — now click the word it belongs in front of:`);
            refInput.settingEl.hide();
            pickWrap.empty();
            const box = pickWrap.createDiv("lm-wordpick");
            this.verseText.split(/\s+/).filter(Boolean).forEach((w, i) => {
                box.createEl("button", { text: w, cls: "lm-wordpick-chip" }).addEventListener("click", async () => {
                    await writeXrefAnchor(this.plugin, this.notePath, this.verse, target, i);
                    new Notice(`Cross-reference to ${bookLabel(parsed.b)} ${parsed.c}:${parsed.v} added at “${w}”.`);
                    this.close(); rerenderAfterMetadata(this.plugin, this.notePath);
                });
            });
        };
        new Setting(contentEl).addButton(b => b.setButtonText("Next: choose the word").setCta().onClick(toPick));
    }
    onClose(): void { this.contentEl.empty(); }
}

// Textual variants (TR/KJV vs the SBLGNT critical text) — a small shared JSON, loaded once. Maps
// "book.ch.v" → "tr-only" (in the KJV/Textus Receptus, omitted by the critical text) or "crit-only".
let variantsCache: Promise<Record<string, string>> | null = null;
function loadVariants(plugin: Plugin): Promise<Record<string, string>> {
    if (!variantsCache) {
        variantsCache = plugin.app.vault.adapter.read("AI/bible-variants/_variants.json")
            .then(s => JSON.parse(s)).catch(() => ({}));
    }
    return variantsCache;
}
function variantNote(kind: string): string {
    return kind === "tr-only"
        ? "This verse is in the Textus Receptus (KJV) but omitted by the modern critical text (SBLGNT) — a known textual variant."
        : "This verse is in the modern critical text (SBLGNT) but not in the KJV/Textus Receptus versification.";
}

/** Click/tap a verse number → a "study" panel for that verse: at the TOP, a link to Matthew Henry's
 *  commentary for the chapter and links to YOUR personal commentary notes on the verse; below,
 *  ALL cross-references and all related-by-meaning links. Tapping a reference opens the same read-card
 *  as the inline markers. Has a close (×) button and dismisses on Escape or a tap/click outside. */
let allXrefPanel: HTMLElement | null = null;
async function showAllXrefs(plugin: Plugin, anchor: HTMLElement, label: string,
                      book: string, chapter: number, verse: number, version: string,
                      xrefs: any[], embeds: any[], hrefFor: (t: any) => string): Promise<void> {
    allXrefPanel?.remove();
    const panel = document.body.createDiv("loremaster-bible-allxref");
    allXrefPanel = panel;

    const close = () => {
        panel.remove(); if (allXrefPanel === panel) allXrefPanel = null;
        document.removeEventListener("pointerdown", dismiss, true);
        document.removeEventListener("click", dismiss, true);
        document.removeEventListener("keydown", dismiss, true);
    };
    const dismiss = (ev: Event) => {
        if (ev instanceof KeyboardEvent) { if (ev.key === "Escape") close(); return; }
        // ignore taps inside the panel or on the read-card the panel spawned
        const n = ev.target as Node;
        if (panel.contains(n) || (hcCard && hcCard.contains(n))) return;
        close();
    };
    const openNote = (path: string) => { plugin.app.workspace.openLinkText(path, "", false); close(); };

    const head = panel.createDiv("loremaster-bible-allxref-head");
    head.createSpan({ text: label });
    head.createEl("button", { text: "×", cls: "loremaster-bible-allxref-close", attr: { "aria-label": "Close" } })
        .addEventListener("click", (e) => { e.stopPropagation(); close(); });

    // ── Study section (top): Matthew Henry + your personal commentary notes ──
    const study = panel.createDiv("loremaster-bible-allxref-study");
    const myNotes = commentaryNotesForVerse(book, chapter, verse);
    if (myNotes.length) {
        study.createDiv("loremaster-bible-allxref-sub").setText("My commentary");
        const list = study.createDiv("loremaster-bible-allxref-list");
        for (const f of myNotes) {
            const a = list.createEl("a", { text: f.basename, cls: "loremaster-bible-allxref-item lm-allxref-note", attr: { href: f.path } });
            a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); openNote(f.path); });
        }
    }
    const mhcSlot = study.createDiv("loremaster-bible-allxref-mhc");   // filled async below
    // Textual note — flag verses that differ between the TR/KJV and the SBLGNT critical text.
    void loadVariants(plugin).then((vs) => {
        const kind = vs[`${book}.${chapter}.${verse}`];
        if (kind && allXrefPanel === panel) {
            const n = study.createDiv("loremaster-bible-allxref-variant");
            n.createSpan({ cls: "loremaster-bible-allxref-variant-tag", text: "†" });
            n.createSpan({ text: " " + variantNote(kind) });
        }
    });

    const booknum = BOOK_NUM[book];
    const notePath = booknum ? `bible/${pad2(booknum)}-${book}/${version}/${book}-${pad3(chapter)}.md` : "";
    const notePathNoExt = notePath.replace(/\.md$/, "");
    const hidden = xrefHiddenSet(notePath ? plugin.app.metadataCache.getCache(notePath)?.frontmatter : null);
    const section = (title: string, items: any[], anchorable: boolean) => {
        if (!items.length) return;
        panel.createDiv("loremaster-bible-allxref-sub").setText(title);
        const list = panel.createDiv("loremaster-bible-allxref-list");
        for (const t of items) {
            const href = hrefFor(t);
            const key = `${verse}:${t.b}.${t.c}.${t.v}`;
            const row = list.createDiv("loremaster-bible-allxref-row");
            const a = row.createEl("a", { text: t.n, cls: "loremaster-bible-allxref-item", attr: { href } });
            // Tap a listed reference → the same read-card (verse text + Open) as the inline markers.
            a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); void showBibleHovercard(plugin, a, href); });
            // Pin this reference's marker after a specific word in the verse.
            if (anchorable && notePath) {
                row.createEl("button", { text: "⚓", cls: "loremaster-bible-allxref-anchor",
                    attr: { "aria-label": "Place this reference after a word" } })
                    .addEventListener("click", async (ev) => {
                        ev.preventDefault(); ev.stopPropagation();
                        const vt = await readVerseText(plugin, notePathNoExt, `v${verse}`);
                        if (!vt) { new Notice("Couldn't read this verse's text to place the marker."); return; }
                        close();
                        new WordAnchorModal(plugin, notePath, verse, vt, `${t.b}.${t.c}.${t.v}`, t.n).open();
                    });
            }
            // Remove (hide) this reference from the reader — or restore it if already hidden.
            if (notePath) {
                let isHidden = hidden.has(key);
                const btn = row.createEl("button", { cls: "loremaster-bible-allxref-anchor" });
                const paint = () => {
                    btn.setText(isHidden ? "↺" : "×");
                    btn.setAttr("aria-label", isHidden ? "Restore this cross-reference" : "Remove this cross-reference");
                    row.toggleClass("lm-allxref-hidden", isHidden);
                };
                paint();
                btn.addEventListener("click", async (ev) => {
                    ev.preventDefault(); ev.stopPropagation();
                    isHidden = !isHidden;
                    await writeXrefHidden(plugin, notePath, key, isHidden);
                    paint(); rerenderAfterMetadata(plugin, notePath);
                });
            }
        }
    };
    section(`Cross-references (${xrefs.length})`, xrefs, true);
    section(`Related by meaning (${embeds.length})`, embeds, true);

    // ── Your cross-references (connected to a word) — move, remove, or add one of your own ──
    const yours = notePath
        ? (xrefAnchorsByVerse(plugin.app.metadataCache.getCache(notePath)?.frontmatter).get(String(verse)) || [])
        : [];
    if (!xrefs.length && !embeds.length && !yours.length)
        panel.createDiv("loremaster-bible-allxref-sub").setText("No cross-references for this verse.");
    if (notePath) {
        panel.createDiv("loremaster-bible-allxref-sub").setText(`Your cross-references (${yours.length})`);
        const ylist = panel.createDiv("loremaster-bible-allxref-list");
        for (const anc of yours) {
            const tr = splitAnchorTarget(anc.target);
            const lbl = tr ? `${bookLabel(tr.b)} ${tr.c}:${tr.v}` : anc.target;
            const href = tr ? hrefFor(tr) : "";
            const row = ylist.createDiv("loremaster-bible-allxref-row");
            const a = row.createEl("a", { text: lbl, cls: "loremaster-bible-allxref-item", attr: { href } });
            a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); if (href) void showBibleHovercard(plugin, a, href); });
            row.createEl("button", { text: "⚓", cls: "loremaster-bible-allxref-anchor", attr: { "aria-label": "Move to a different word" } })
                .addEventListener("click", async (ev) => {
                    ev.preventDefault(); ev.stopPropagation();
                    const vt = await readVerseText(plugin, notePathNoExt, `v${verse}`);
                    if (!vt) { new Notice("Couldn't read this verse's text."); return; }
                    close();
                    new WordAnchorModal(plugin, notePath, verse, vt, anc.target, lbl).open();
                });
            row.createEl("button", { text: "×", cls: "loremaster-bible-allxref-anchor", attr: { "aria-label": "Remove this cross-reference" } })
                .addEventListener("click", async (ev) => {
                    ev.preventDefault(); ev.stopPropagation();
                    await writeXrefAnchor(plugin, notePath, verse, anc.target, null);
                    close(); rerenderAfterMetadata(plugin, notePath);
                });
        }
        const addBtn = panel.createEl("button", { text: "＋ Add your own cross-reference", cls: "loremaster-bible-allxref-add" });
        addBtn.addEventListener("click", async (ev) => {
            ev.preventDefault(); ev.stopPropagation();
            const vt = await readVerseText(plugin, notePathNoExt, `v${verse}`);
            if (!vt) { new Notice("Couldn't read this verse's text."); return; }
            close();
            new AddWordXrefModal(plugin, notePath, verse, vt).open();
        });
    }

    const r = anchor.getBoundingClientRect();
    panel.style.top = `${window.scrollY + r.bottom + 4}px`;
    panel.style.left = `${Math.min(window.scrollX + r.left, window.scrollX + window.innerWidth - 260)}px`;
    // pointerdown covers touch + mouse; click as a backup (some mobile webviews). Delay so the
    // opening tap doesn't immediately dismiss it.
    setTimeout(() => {
        document.addEventListener("pointerdown", dismiss, true);
        document.addEventListener("click", dismiss, true);
        document.addEventListener("keydown", dismiss, true);
    }, 0);

    // Matthew Henry link — always offered so you can reach the chapter's commentary from any verse.
    const num = BOOK_NUM[book];
    if (num) {
        const mhcPath = await mhcNoteFor(plugin, num, chapter);
        if (mhcPath && allXrefPanel === panel) {
            const a = mhcSlot.createEl("a", { text: "📖 Matthew Henry", cls: "loremaster-bible-allxref-item lm-allxref-mhc", attr: { href: mhcPath } });
            a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); openNote(mhcPath); });
        }
    }
}

/** "Ask the Bible" — a natural-language question → the verses closest in MEANING (not keywords),
 *  from the verse-level embedding index on the service, each shown with its text + your notes. */
class AskBibleModal extends Modal {
    constructor(private plugin: Plugin) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Ask the Bible" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Ask in your own words — LoreMaster finds the verses closest in meaning (not just keyword matches)." });
        let q = "";
        let lastHits: any[] = [], lastQ = "";
        const status = contentEl.createEl("p", { cls: "setting-item-description" });
        const results = contentEl.createDiv("lm-askbible-results");
        const run = async () => {
            if (!q.trim()) return;
            status.setText("Searching…"); results.empty(); lastHits = [];
            const s = (this.plugin as any).settings;
            let data: any;
            try {
                const r = await fetch(`http://${s.host}:${s.port}/bible/search?q=${encodeURIComponent(q)}&k=15`,
                    { headers: s.apiToken ? { "X-API-Key": s.apiToken } : {}, signal: timeoutSignal(15000) });
                data = await r.json();
            } catch (e) { status.setText(`Service unreachable: ${e}. (Ask the Bible needs the running service.)`); return; }
            if (!data || !data.ready) { status.setText("The verse index isn't built yet — run “vault:bible-verse-index” on the service."); return; }
            const hits = (data.results || []).filter((t: any) => BOOK_NUM[t.b]);
            if (!hits.length) { status.setText("No verses matched."); return; }
            lastHits = hits; lastQ = q.trim();
            status.setText(`${hits.length} verses closest in meaning:`);
            for (const t of hits) {
                const num = BOOK_NUM[t.b];
                const linkbase = `bible/${pad2(num)}-${t.b}/web/${t.b}-${pad3(t.c)}`;
                const href = `${linkbase}#^v${t.v}`;
                const row = results.createDiv("lm-askbible-row");
                const head = row.createEl("a", { text: t.n, cls: "lm-askbible-ref", attr: { href } });
                head.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    this.plugin.app.workspace.openLinkText(href, "", ev.ctrlKey || ev.metaKey);
                    this.close();
                });
                const textEl = row.createDiv("lm-askbible-text");
                void readVerseText(this.plugin, linkbase, `v${t.v}`).then((vt) => textEl.setText(vt || ""));
                const notes = commentaryNotesForVerse(t.b, t.c, t.v);
                if (notes.length) {
                    const c = row.createEl("a", { text: `📝 your note${notes.length > 1 ? "s" : ""}`, cls: "lm-askbible-note" });
                    c.addEventListener("click", (ev) => {
                        ev.preventDefault();
                        this.plugin.app.workspace.openLinkText(notes[0].path, "", false);
                        this.close();
                    });
                }
            }
        };
        new Setting(contentEl).setName("Question")
            .addText((tc) => {
                tc.setPlaceholder("e.g. God's patience with sinners").onChange((v) => q = v);
                tc.inputEl.style.width = "100%";
                tc.inputEl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); void run(); } });
                setTimeout(() => tc.inputEl.focus(), 0);
            });
        new Setting(contentEl)
            .addButton((b) => b.setButtonText("Ask").setCta().onClick(() => void run()))
            // Save the results as a persistent topical study note (an auto-built Map-of-Content from the
            // embedding search) under bible/topical/.
            .addButton((b) => b.setButtonText("Save as study note").onClick(async () => {
                if (!lastHits.length) { new Notice("Search first, then save the results."); return; }
                const slug = lastQ.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "topic";
                const path = `bible/topical/${slug}.md`;
                const lines = ["---", "tags:", "  - bible", "  - topical-study", "---",
                    `# Topical study — ${lastQ}`, "",
                    "Verses closest in meaning (LoreMaster semantic search). Tick as you study.", ""];
                for (const t of lastHits) {
                    const num = BOOK_NUM[t.b];
                    const linkbase = `bible/${pad2(num)}-${t.b}/web/${t.b}-${pad3(t.c)}`;
                    const vt = await readVerseText(this.plugin, linkbase, `v${t.v}`);
                    lines.push(`- [ ] [[${linkbase}#^v${t.v}|${t.n}]] — ${vt || ""}`);
                }
                try { await this.plugin.app.vault.createFolder("bible/topical"); } catch { /* exists */ }
                const existing = this.plugin.app.vault.getAbstractFileByPath(path);
                if (existing instanceof TFile) await this.plugin.app.vault.modify(existing, lines.join("\n") + "\n");
                else await this.plugin.app.vault.create(path, lines.join("\n") + "\n");
                new Notice(`Saved ${path}`);
                this.close();
                this.plugin.app.workspace.openLinkText(path, "", false);
            }));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the "Bible: Ask the Bible" command (semantic verse search over the whole Bible). */
export function registerBibleSearch(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-ask",
        name: "Bible: Ask the Bible (semantic search)",
        callback: () => new AskBibleModal(plugin).open(),
    });
}

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
    // Per-verse embedding neighbours for a chapter (from the backend verse index), cached per chapter.
    const simCache = new Map<string, Promise<Record<string, any[]>>>();
    const loadSimilar = (book: string, chapter: number): Promise<Record<string, any[]>> => {
        const key = `${book}.${chapter}`;
        let p = simCache.get(key);
        if (!p) {
            // Build defensively: nothing here may THROW synchronously, or it would abort the
            // post-processor before cross-ref markers are injected (the phone bug — see timeoutSignal).
            p = (async () => {
                try {
                    const s = (plugin as any).settings;
                    const r = await fetch(`http://${s.host}:${s.port}/bible/chapter-similar?book=${book}&chapter=${chapter}&k=8`,
                        { headers: s.apiToken ? { "X-API-Key": s.apiToken } : {}, signal: timeoutSignal(5000) });
                    if (!r.ok) return {};
                    return (await r.json()).verses || {};
                } catch { return {}; }
            })();
            simCache.set(key, p);
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

        // Version switcher — a small dropdown at the top-right of the chapter, listing the translations of
        // THIS chapter you have in the vault. Selecting one opens that version's note.
        const h1 = el.querySelector("h1");
        const bnum = BOOK_NUM[book];
        if (h1 && bnum && !h1.querySelector(".lm-bible-version-switch")) {
            void plugin.app.vault.adapter.list(`bible/${pad2(bnum)}-${book}`).then((listing) => {
                const versions = (listing.folders || []).map(f => f.split("/").pop() || "")
                    .filter(v => v && plugin.app.vault.getAbstractFileByPath(`bible/${pad2(bnum)}-${book}/${v}/${book}-${pad3(chapter)}.md`));
                if (versions.length < 2 || h1.querySelector(".lm-bible-version-switch")) return;
                const sw = h1.createEl("select", { cls: "lm-bible-version-switch", attr: { "aria-label": "Switch translation" } });
                for (const v of versions) sw.createEl("option", { text: v.toUpperCase(), value: v });
                sw.value = version;
                sw.addEventListener("change", () =>
                    plugin.app.workspace.openLinkText(`bible/${pad2(bnum)}-${book}/${sw.value}/${book}-${pad3(chapter)}`, "", false));
            }).catch(() => { /* no listing — skip */ });
        }

        // Obsidian may hand us the container OR a bare <p>; collect both so we never miss a verse.
        const paras = Array.from(el.querySelectorAll("p")) as HTMLParagraphElement[];
        if (el.tagName === "P") paras.push(el as HTMLParagraphElement);
        const verses = paras.filter(p => {
            const s = p.firstElementChild;
            return s && s.tagName === "STRONG" && /^\d+$/.test((s.textContent || "").trim())
                && !p.hasAttribute("data-lm-xref");
        });
        if (!verses.length) return;
        // Paragraph starts (from the USFM \p boundaries) — mark them so flow layout can break there.
        const fm = plugin.app.metadataCache.getCache(ctx.sourcePath)?.frontmatter;
        const paraStarts = new Set(String(fm?.["bible-parastarts"] ?? "").split(",").filter(Boolean));
        const anchorsByVerse = xrefAnchorsByVerse(fm);   // verse → your word-connected cross-references
        const hidden = xrefHiddenSet(fm);                // "verse:tb.tc.tv" refs you've removed from this note
        const variants = await loadVariants(plugin);     // TR/KJV vs SBLGNT textual-variant verses
        const data = await loadBook(book);
        const sim = await loadSimilar(book, chapter);   // per-verse embedding neighbours

        const shown = Math.max(1, Math.min(20, (plugin as any).settings?.bibleXrefCount ?? 4));
        const S = (plugin as any).settings ?? {};
        const showXrefs = S.bibleShowXrefs !== false;    // default on
        const showEmbeds = S.bibleShowEmbeds !== false;  // default on
        const hrefFor = (t: any) => {
            const num = BOOK_NUM[t.b];
            return num ? `bible/${pad2(num)}-${t.b}/${version}/${t.b}-${pad3(t.c)}#^v${t.v}` : "";
        };
        const open = (href: string, ev: MouseEvent) => {
            ev.preventDefault();
            plugin.app.workspace.openLinkText(href, ctx.sourcePath, ev.ctrlKey || ev.metaKey);
        };
        // A marker tap: on mobile, open the read-card (with an Open button) instead of jumping away
        // — previously a phone tap both popped the card AND navigated. Desktop click still navigates.
        const onMarkerClick = (anchorEl: HTMLElement, href: string) => (ev: MouseEvent) => {
            if (markerTapOpensCard()) {
                ev.preventDefault(); ev.stopPropagation();
                void showBibleHovercard(plugin, anchorEl, href);
            } else {
                open(href, ev);
            }
        };
        for (const p of verses) {
            p.setAttribute("data-lm-xref", "1");
            const num = p.firstElementChild as HTMLElement;
            const vnum = (num.textContent || "").trim();
            if (paraStarts.has(vnum)) (p.closest(".el-p") || p).addClass("lm-para-start");
            // Poetry: a verse with hard-break stichs (multi-line). Give it a CSS hanging indent (works
            // in both reading + flowing modes, and doesn't depend on the fragile em-space characters
            // surviving the renderer) and strip any leading em-space indents so they don't double up.
            if (p.querySelector("br") || / /.test(p.textContent || "")) {
                p.addClass("lm-poetry");
                (p.closest(".el-p") || p).addClass("lm-poetry-block");
                const w = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
                for (let tn = w.nextNode() as Text | null; tn; tn = w.nextNode() as Text | null)
                    if (tn.nodeValue && tn.nodeValue.indexOf(" ") >= 0) tn.nodeValue = tn.nodeValue.replace(/ /g, "");
            }
            const targets = (data[`${book}.${chapter}.${vnum}`] || []).filter((t: any) => BOOK_NUM[t.b]);
            // ── Cross-references YOU connected to a word (bible-xref-anchors) — your deliberate links.
            // They render at the FRONT of the word as distinct dark-purple UPPERCASE superscripts, and
            // always show (independent of the general cross-reference toggle). A target may be a listed
            // cross-reference, a related-by-meaning passage, or one you typed in yourself.
            const connected = anchorsByVerse.get(vnum) || [];
            const anchoredKeys = new Set(connected.map(a => a.target));   // don't also draw these in the clusters
            // Group by the word they sit on: several references on one word collapse to a SINGLE letter
            // whose tap/hover opens the list, instead of a run of letters.
            const byWord = new Map<number, string[]>();
            for (const anc of connected) { const g = byWord.get(anc.wordIndex) ?? []; g.push(anc.target); byWord.set(anc.wordIndex, g); }
            let gi = 0;
            for (const [wordIndex, targets] of byWord) {
                const refs = targets.map(splitAnchorTarget).filter((t): t is { b: string; c: number; v: number } => !!t && !!BOOK_NUM[t.b]);
                if (!refs.length) continue;
                const label = UP_LETTERS[gi] || "*"; gi++;
                const sup = createEl("sup", { cls: "lm-xref-word" });
                if (refs.length === 1) {
                    const href = hrefFor(refs[0]);
                    const a = sup.createEl("a", { text: label, cls: "lm-xref-word-link",
                        attr: { "data-href": href, href, "aria-label": `${bookLabel(refs[0].b)} ${refs[0].c}:${refs[0].v}` } });
                    a.addEventListener("click", onMarkerClick(a, href));
                } else {
                    const a = sup.createEl("a", { text: label, cls: "lm-xref-word-link lm-xref-word-multi",
                        attr: { href: "#", "aria-label": `${refs.length} cross-references` } });
                    a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); showWordRefList(plugin, a, refs, hrefFor); });
                    a.addEventListener("mouseenter", () => showWordRefList(plugin, a, refs, hrefFor));
                }
                if (!placeMarkerBeforeWord(p, wordIndex, sup)) p.insertBefore(sup, num.nextSibling);
            }
            // Cross-reference markers (public-domain), quiet superscript letters clustered at the END of
            // the verse (toggle-gated, capped). Anything connected to a word above is skipped here.
            let endShown = 0;
            for (let i = 0; i < targets.length; i++) {
                const t = targets[i];
                if (anchoredKeys.has(`${t.b}.${t.c}.${t.v}`)) continue;
                if (hidden.has(`${vnum}:${t.b}.${t.c}.${t.v}`)) continue;   // you removed this one
                if (!showXrefs || endShown >= shown) continue;
                const href = hrefFor(t);
                const sup = createEl("sup");
                const a = sup.createEl("a", { text: SUP_LETTERS[i] || "*", cls: "lm-xref",
                    attr: { "data-href": href, href, "aria-label": t.n } });
                a.addEventListener("click", onMarkerClick(a, href));
                sup.insertBefore(document.createTextNode(" "), a); p.appendChild(sup); endShown++;
            }
            // Embedding-similarity markers (verse index), distinct "≈" group at the end, deduped against
            // the cross-references AND your word-connected links so nothing is shown twice. (Toggle: settings.)
            const xset = new Set(targets.map((t: any) => `${t.b}.${t.c}.${t.v}`));
            const sims = (sim[vnum] || []).filter((t: any) => BOOK_NUM[t.b]
                && !xset.has(`${t.b}.${t.c}.${t.v}`) && !anchoredKeys.has(`${t.b}.${t.c}.${t.v}`)
                && !hidden.has(`${vnum}:${t.b}.${t.c}.${t.v}`));
            let esup: HTMLElement | null = null, endSims = 0;
            for (let i = 0; i < sims.length; i++) {
                const t = sims[i], href = hrefFor(t);
                if (!showEmbeds || endSims >= 2) continue;              // end cluster: capped, toggle-gated
                if (!esup) esup = p.createEl("sup", { cls: "lm-embed-group" });
                esup.appendText(" ");
                const a = esup.createEl("a", { text: SUP_LETTERS[i] || "*", cls: "lm-embed-vlink",
                    attr: { "data-href": href, href, "aria-label": `Related: ${t.n}` } });
                a.addEventListener("click", onMarkerClick(a, href));
                endSims++;
            }
            // Tap the verse number → study panel: Matthew Henry + your notes at top, then ALL
            // cross-references + related-by-meaning. Always available (Matthew Henry is offered for
            // every verse), even if a verse has no cross-references or inline markers are toggled off.
            num.addClass("lm-verse-num");
            if (variants[`${book}.${chapter}.${vnum}`]) {   // textual-variant verse → a quiet † dagger
                const dag = createEl("sup", { cls: "lm-variant-dagger", text: "†", attr: { "aria-label": "Textual variant — tap the verse number" } });
                num.insertAdjacentElement("afterend", dag);
            }
            num.setAttribute("aria-label", `Study ${bookLabel(book)} ${chapter}:${vnum}`);
            num.addEventListener("click", (ev) => {
                ev.preventDefault(); ev.stopPropagation();
                void showAllXrefs(plugin, num, `${bookLabel(book)} ${chapter}:${vnum}`,
                    book, chapter, parseInt(vnum, 10), version, targets, sims, hrefFor);
            });
        }
        // Nav lines (prev · book · next) — wikilink-only paragraphs. Tag them so the bottom nav keeps to
        // its own line in flowing-paragraph mode (its block wrapper isn't inlined with the verses).
        for (const np of paras) {
            if (!np.querySelector("strong") && np.querySelectorAll("a.internal-link").length >= 2) {
                np.addClass("lm-bible-nav");
                (np.closest(".el-p") || np).addClass("lm-bible-nav-block");
            }
        }
    });
}

/** Register the EMBEDDING-similarity overlay: a "Related by meaning" section appended to a Bible
 *  chapter, distinct from the public-domain cross-references. Sourced live from the backend's
 *  `/relevant` (vector index), deduplicated against this chapter's cross-reference targets. */
export function registerBibleEmbeddingLinks(plugin: Plugin): void {
    const xrefCache = new Map<string, Promise<Record<string, any[]>>>();
    const loadBook = (book: string) => {
        let p = xrefCache.get(book);
        if (!p) { p = plugin.app.vault.adapter.read(`AI/bible-crossrefs/${book}.json`).then(s => JSON.parse(s)).catch(() => ({})); xrefCache.set(book, p); }
        return p;
    };
    const bibleRef = (path: string) => {
        const pp = path.split("/"); if (pp.length < 4) return null;
        const b = pp[pp.length - 3].replace(/^\d+-/, "");
        const c = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        return c ? { b, c } : null;
    };

    const inject = async (file: TFile) => {
        if (!file || !file.path.startsWith("bible/")) return;
        const self = bibleRef(file.path); if (!self) return;
        const book = self.b, chapter = self.c;
        // Retry until the reading view has rendered (a full app reload can take a couple seconds).
        let sizer: HTMLElement | null = null;
        for (let i = 0; i < 10; i++) {
            await sleep(400);
            const view = plugin.app.workspace.getActiveViewOfType(MarkdownView);
            if (!view || view.file !== file) continue;
            const c = view.contentEl.querySelector(
                ".markdown-preview-view.bible .markdown-preview-sizer, .markdown-reading-view.bible .markdown-preview-sizer") as HTMLElement | null;
            if (c && c.querySelector("p")) { sizer = c; break; }   // rendered content present
        }
        if (!sizer || sizer.querySelector(".lm-embed-section")) return;

        const s = (plugin as any).settings;
        let notes: { path: string }[] = [];
        try {
            const resp = await fetch(`http://${s.host}:${s.port}/relevant?path=${encodeURIComponent(file.path)}&k=12`,
                { headers: s.apiToken ? { "X-API-Key": s.apiToken } : {}, signal: timeoutSignal(5000) });
            if (resp.ok) notes = (await resp.json()).notes ?? [];
        } catch { return; }
        if (!notes.length) return;

        // dedup: collect the (book.chapter) already reachable via this chapter's cross-references
        const data = await loadBook(book);
        const xrefCh = new Set<string>();
        for (const k in data) if (k.startsWith(`${book}.${chapter}.`)) for (const t of data[k]) xrefCh.add(`${t.b}.${t.c}`);

        const items: { path: string; label: string; kind: string }[] = [];
        for (const n of notes) {
            if (n.path === file.path) continue;
            if (n.path.startsWith("bible/")) {
                const r = bibleRef(n.path); if (!r) continue;
                if (r.b === book && r.c === chapter) continue;
                if (xrefCh.has(`${r.b}.${r.c}`)) continue;                 // already a cross-reference → skip
                items.push({ path: n.path, label: `${bookLabel(r.b)} ${r.c}`, kind: "scripture" });
            } else if (n.path.startsWith("AI/Library/")) {
                items.push({ path: n.path, label: (n.path.split("/").pop() || "").replace(/\.md$/, ""), kind: "commentary" });
            }
            if (items.length >= 6) break;
        }
        if (!items.length) return;

        const sec = sizer.createDiv("lm-embed-section");
        sec.createDiv("lm-embed-head").setText("Related by meaning");
        const list = sec.createDiv("lm-embed-list");
        for (const it of items) {
            list.createEl("a", { text: it.label, cls: `lm-embed-link lm-embed-${it.kind}`, attr: { href: it.path } })
                .addEventListener("click", (ev) => { ev.preventDefault(); plugin.app.workspace.openLinkText(it.path, file.path, ev.ctrlKey || ev.metaKey); });
        }
    };

    plugin.registerEvent(plugin.app.workspace.on("file-open", (file) => { if (file) void inject(file); }));
}

// ── Paste-to-format: user pastes a chapter of a translation they're licensed to use; we reorganise
//    their text into the standard note format (we never supply the text). Self-contained + offline. ──
function cleanPaste(raw: string): string {
    return raw.replace(/ /g, " ").replace(/\[[a-z0-9]{1,3}\]/gi, "")
        .replace(/\(\s*\d+\s*\)/g, "").replace(/[ \t]+/g, " ").trim();
}
function splitVerses(raw: string, poetry = false): Map<number, string> {
    // In poetry mode keep newlines (they're the stich breaks); otherwise flatten all whitespace.
    const flat = poetry ? cleanPaste(raw).replace(/[ \t]+/g, " ") : cleanPaste(raw).replace(/\s+/g, " ");
    const out = new Map<number, string>();
    if (!flat) return out;
    const m1 = flat.match(/(?<![\d.])1\b/);
    if (!m1 || m1.index === undefined) return out;
    let cur = 1, start = m1.index + m1[0].length;
    while (true) {
        const nxt = cur + 1, rest = flat.slice(start);
        const strong = rest.match(new RegExp(`(?<![\\d.])\\b${nxt}\\b(?=\\s*[“"'A-Z])`));
        const loose = strong || rest.match(new RegExp(`(?<![\\d.])\\b${nxt}\\b`));
        if (loose && loose.index !== undefined) {
            out.set(cur, flat.slice(start, start + loose.index).replace(/^[\s.]+|[\s.]+$/g, ""));
            cur = nxt; start = start + loose.index + loose[0].length;
        } else { out.set(cur, rest.replace(/^[\s.]+|[\s.]+$/g, "")); break; }
        if (nxt > 250) break;
    }
    for (const [k, v] of out) if (!v.trim()) out.delete(k);
    return out;
}

/** Format a verse's text as poetry: each source line (stich) breaks (two trailing spaces) and
 *  continuation stichs are em-space-indented — the exact layout the reader renders as poetry. */
function poetryFormat(text: string): string {
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    if (lines.length <= 1) return text.replace(/\s*\n\s*/g, " ");
    return lines.map((l, i) => (i === 0 ? l : " " + l) + (i < lines.length - 1 ? "  " : "")).join("\n");
}
/** prev · book · next chapter nav as a wikilink line (targets may not exist yet — that's fine). */
function navLine(num: number, book: string, version: string, chapter: number): string {
    const base = (ch: number) => `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(ch)}`;
    const parts: string[] = [];
    if (chapter > 1) parts.push(`[[${base(chapter - 1)}|← ${bookLabel(book)} ${chapter - 1}]]`);
    parts.push(`[[bible/${pad2(num)}-${book}/${version}/${book}|${bookLabel(book)}]]`);
    parts.push(`[[${base(chapter + 1)}|${bookLabel(book)} ${chapter + 1} →]]`);
    return parts.join(" · ");
}

/** Paragraph starts (verse numbers) harvested from the pasted text's BLANK LINES: the first verse
 *  number in each blank-line-separated block (after the first) begins a new paragraph. Always includes 1. */
function harvestParaStarts(raw: string): number[] {
    const starts = new Set<number>([1]);
    const blocks = cleanPaste(raw ? raw.replace(/[ \t]+\n/g, "\n") : "").split(/\n\s*\n/);
    // cleanPaste flattens newlines; harvest from the RAW blank-line structure instead:
    const rawBlocks = (raw || "").split(/\r?\n[ \t]*\r?\n/);
    for (let i = 1; i < rawBlocks.length; i++) {
        const m = rawBlocks[i].match(/(?<![\d.])\b(\d{1,3})\b/);
        if (m) starts.add(parseInt(m[1], 10));
    }
    void blocks;
    return [...starts].sort((a, b) => a - b);
}

function formatPastedChapter(raw: string, bookSlug: string, chapter: number, version: string,
                            poetry = false, paraStartsInput = "", poetryVersesInput = "") {
    bookSlug = bookSlug.toLowerCase().trim();
    const num = BOOK_NUM[bookSlug];
    if (!num) return { error: `Unknown book slug "${bookSlug}" (use e.g. john, 1-corinthians, psalms).` };
    if (!chapter) return { error: "Enter a chapter number." };
    if (!version) return { error: "Enter a version (e.g. esv, nasb, nkjv)." };
    // Which verses are poetry: the whole-chapter toggle, or a specific list/range (e.g. "12-14"). Poetry
    // verses keep the pasted line breaks as stichs; prose verses flatten to one line. So always split
    // keeping the newlines, then decide per verse.
    const poetryVerses = new Set(poetry ? [] : parseVerseRange(poetryVersesInput));
    const verses = splitVerses(raw, poetry || poetryVerses.size > 0);
    if (!verses.size) return { error: "Couldn't find verse numbers in the pasted text." };
    // Paragraph starts: use the user's list if given, else harvest from the pasted blank lines.
    const typed = paraStartsInput.split(/[,\s]+/).map(s => parseInt(s, 10)).filter(n => n > 0);
    const paraStarts = (typed.length ? Array.from(new Set([1, ...typed])) : harvestParaStarts(raw)).sort((a, b) => a - b);
    const basename = `${bookSlug}-${pad3(chapter)}`;
    // Top nav carries a ^nav block id; the bottom nav TRANSCLUDES it, so editing the top updates the
    // bottom automatically (and the embed renders on its own line).
    const nav = navLine(num, bookSlug, version, chapter);
    const fm = ["---", "cssclasses:", "  - bible", `bible-version: ${version}`,
        `bible-book: ${bookSlug}`, `bible-booknum: ${num}`, `bible-chapter: ${chapter}`,
        // list form so Obsidian's property editor treats it as a LIST (add verse numbers as items).
        "bible-parastarts:", ...paraStarts.map(n => `  - ${n}`),
        "---", "", `# ${bookLabel(bookSlug)} ${chapter}`, "", `${nav} ^nav`, ""];
    const body = [...verses.keys()].sort((a, b) => a - b).map(n => {
        const isPoetry = poetry || poetryVerses.has(n);
        const vt = isPoetry ? poetryFormat(verses.get(n)!) : (verses.get(n) || "").replace(/\s*\n\s*/g, " ");
        return `**${n}** ${vt} ^v${n}`;
    });
    // Blank line BETWEEN verses (\n\n) so each renders as its own paragraph. Bottom nav = a transclusion
    // of the top's ^nav block (stays in sync when you edit the top).
    return { path: `bible/${pad2(num)}-${bookSlug}/${version}/${basename}.md`,
             note: fm.concat([body.join("\n\n"), "", `![[${basename}#^nav]]`]).join("\n") + "\n", verses: verses.size };
}

class BiblePasteModal extends Modal {
    constructor(private plugin: Plugin) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Paste a Bible chapter" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Paste a chapter from a translation you're licensed to use. It's saved in the standard " +
                  "format so cross-references and related-by-meaning appear automatically." });
        let book = "", version = "", chapter = "", poetry = false, paraStarts = "";
        new Setting(contentEl).setName("Book").setDesc("slug — e.g. john, 1-corinthians, psalms")
            .addText(t => t.onChange(v => book = v));
        new Setting(contentEl).setName("Chapter").addText(t => { t.inputEl.type = "number"; t.onChange(v => chapter = v); });
        new Setting(contentEl).setName("Version").setDesc("e.g. esv, nasb, nkjv").addText(t => t.onChange(v => version = v));
        let poetryVerses = "";
        new Setting(contentEl).setName("Poetry (whole chapter)").setDesc("keep ALL the pasted line breaks as poetic lines (for Psalms, Proverbs…)")
            .addToggle(t => t.setValue(false).onChange(v => poetry = v));
        new Setting(contentEl).setName("Poetry verses").setDesc("Or mark just a SECTION as poetry — verse numbers/ranges, e.g. “12-14”. Those verses keep the pasted line breaks; the rest flow as prose.")
            .addText(t => { t.setPlaceholder("e.g. 12-14").onChange(v => poetryVerses = v); });
        let paraInput: any = null;
        new Setting(contentEl).setName("Paragraph breaks")
            .setDesc("Verse numbers that start a new paragraph — auto-filled from blank lines in the paste; edit if needed.")
            .addText(t => { paraInput = t; t.setPlaceholder("e.g. 1, 5, 12").onChange(v => paraStarts = v); });
        const ta = contentEl.createEl("textarea", { attr: { rows: "12", placeholder: "Paste the chapter text here…" } });
        ta.style.cssText = "width:100%;font-family:var(--font-monospace);";
        // Auto-harvest paragraph breaks from the pasted text's blank lines (unless you've typed your own).
        ta.addEventListener("input", () => {
            if (paraStarts.trim()) return;
            const found = harvestParaStarts(ta.value);
            if (found.length && paraInput) paraInput.setValue(found.join(", "));
        });
        new Setting(contentEl).addButton(b => b.setButtonText("Format & save").setCta().onClick(async () => {
            const r = formatPastedChapter(ta.value, book, parseInt(chapter, 10), version.toLowerCase().trim(), poetry, paraStarts || (paraInput?.getValue() ?? ""), poetryVerses);
            if ("error" in r) { new Notice(r.error!); return; }
            if (this.plugin.app.vault.getAbstractFileByPath(r.path)) { new Notice(`Already exists: ${r.path}`); return; }
            const folder = r.path.split("/").slice(0, -1).join("/");
            try { await this.plugin.app.vault.createFolder(folder); } catch { /* exists */ }
            await this.plugin.app.vault.create(r.path, r.note);
            new Notice(`Saved ${r.verses} verses → ${r.path}`);
            this.close();
            this.plugin.app.workspace.openLinkText(r.path, "", false);
            // Auto-approximate the Strong's links for the freshly-pasted (untagged) chapter.
            alignAfterPaste(this.plugin, book.toLowerCase().trim(), version.toLowerCase().trim(), parseInt(chapter, 10));
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

// ── Manual annotation (works in ANY translation) ────────────────────────────
// Select text in a Bible note (edit / Live Preview) and right-click to: highlight it, mark it as the
// words of Christ (red), or tag a word with a Strong's number. These wrap the selection in the same
// markup the reader already renders (==highlight==, <span class="lm-wj">, <span class="lm-s" data-s>),
// so red-letter, highlighting and Strong's hover work in KJV, ESV, pasted chapters — anything.
export class StrongsInputModal extends Modal {
    constructor(private plugin: Plugin, private onSubmit: (n: string) => void) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Tag word with a Strong's number" });
        const input = contentEl.createEl("input", { type: "text", attr: { placeholder: "e.g. H430 or G26" } });
        input.style.width = "100%";
        const submit = () => {
            const v = input.value.trim().toUpperCase();
            this.close();
            if (/^[HG]\d+$/.test(v)) this.onSubmit(v);
            else new Notice("Enter a Strong's number like H430 (Hebrew) or G26 (Greek).");
        };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
        const row = contentEl.createDiv(); row.style.marginTop = "8px";
        row.createEl("button", { text: "Add", cls: "mod-cta" }).addEventListener("click", submit);
        setTimeout(() => input.focus(), 0);
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Right-click annotations on a Bible (or commentary) note's selected text. */
export function registerBibleAnnotations(plugin: Plugin): void {
    plugin.registerEvent(plugin.app.workspace.on("editor-menu", (menu: Menu, editor: Editor, view: any) => {
        const path = view?.file?.path as string | undefined;
        if (!path || !(path.startsWith("bible/") || path.startsWith("bible-commentary/"))) return;
        const sel = editor.getSelection();
        if (!sel) return;
        const wrap = (s: string) => editor.replaceSelection(s);
        menu.addItem((i) => i.setTitle("Bible: highlight").setIcon("highlighter")
            .onClick(() => wrap(`==${sel}==`)));
        menu.addItem((i) => i.setTitle("Bible: words of Christ (red)").setIcon("quote-glyph")
            .onClick(() => wrap(`<span class="lm-wj">${sel}</span>`)));
        menu.addItem((i) => i.setTitle("Bible: tag Strong's number…").setIcon("hash")
            .onClick(() => new StrongsInputModal(plugin, (n) => wrap(`<span class="lm-s" data-s="${n}">${sel}</span>`)).open()));
        if (/\n/.test(sel)) menu.addItem((i) => i.setTitle("Bible: format as poetry").setIcon("text-quote")
            .onClick(() => formatPoetry(editor)));
        if (path.startsWith("bible/")) menu.addItem((i) => i.setTitle("Bible: attach a note to selection").setIcon("pencil")
            .onClick(() => (plugin.app as any).commands.executeCommandById("loremaster:bible-attach-word-note")));
    }));

    // Same three as commands (hotkey-able + testable; work on the current selection in any note).
    const selWrap = (editor: Editor, fn: (s: string) => string) => {
        const s = editor.getSelection();
        if (!s) { new Notice("Select some text first."); return; }
        editor.replaceSelection(fn(s));
    };
    plugin.addCommand({ id: "bible-highlight", name: "Bible: highlight selection",
        editorCallback: (editor: Editor) => selWrap(editor, (s) => `==${s}==`) });
    plugin.addCommand({ id: "bible-words-of-christ", name: "Bible: mark selection as words of Christ (red)",
        editorCallback: (editor: Editor) => selWrap(editor, (s) => `<span class="lm-wj">${s}</span>`) });
    plugin.addCommand({ id: "bible-tag-strongs", name: "Bible: tag selection with a Strong's number",
        editorCallback: (editor: Editor) => {
            const s = editor.getSelection();
            if (!s) { new Notice("Select a word first."); return; }
            new StrongsInputModal(plugin, (n) => editor.replaceSelection(`<span class="lm-s" data-s="${n}">${s}</span>`)).open();
        } });

    // Poetry: turn a line-broken selection into indented poetry. Each poetic line (stich) becomes its
    // own line (two-space hard break) and continuation lines are indented with an em-space — the exact
    // format the reader renders as poetry. Break the verse into stich lines first, then run this.
    const formatPoetry = (editor: Editor) => {
        const sel = editor.getSelection();
        if (!sel) { new Notice("Select the verse lines (one stich per line) to format as poetry."); return; }
        const EM = " ";   // em-space — the reader's poetic indent
        const lines = sel.split("\n");
        const out = lines.map((line, i) => {
            let l = line.replace(/[ \t]+$/, "");                    // drop trailing whitespace
            if (!l.trim()) return l;                                // keep blank lines
            if (!/^\s*\*\*\d+\*\*/.test(l)) l = EM + l.replace(/^[ \t ]+/, "");   // indent continuations
            if (i < lines.length - 1) l += "  ";                    // hard break (all but the last line)
            return l;
        });
        editor.replaceSelection(out.join("\n"));
    };
    plugin.addCommand({ id: "bible-format-poetry", name: "Bible: format selection as poetry (indent stich lines)",
        editorCallback: formatPoetry });
}

// ── LoreMaster right-click menu ─────────────────────────────────────────────
/** A LoreMaster section in the right-click menu across views. Reading view has no native editor menu, so
 *  we build one on contextmenu (inside a Bible chapter, so we don't hijack right-click elsewhere); edit /
 *  Live-Preview gets the same section appended to the native editor menu. The Bible study commands appear
 *  in the submenu ONLY when a Bible chapter is open. */
export function registerBibleContextMenu(plugin: Plugin): void {
    const bibleFromPath = (path?: string): { book: string; chapter: number; version: string } | null => {
        if (!path || !path.startsWith("bible/")) return null;
        const pp = path.split("/");
        if (pp.length < 4) return null;
        const book = pp[pp.length - 3].replace(/^\d+-/, "");
        const version = pp[pp.length - 2];
        const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        return chapter && BOOK_NUM[book] ? { book, chapter, version } : null;
    };
    const run = (id: string) => (plugin.app as any).commands?.executeCommandById(`loremaster:${id}`);

    const fill = (m: Menu, bible: { book: string; chapter: number; version: string } | null, editMode: boolean) => {
        if (bible) {
            m.addItem(i => i.setTitle("Interlinear (this chapter)").setIcon("table-columns").onClick(() => run("bible-interlinear")));
            m.addItem(i => i.setTitle("Concordance…").setIcon("search").onClick(() => run("bible-concordance")));
            m.addItem(i => i.setTitle("Morphology search…").setIcon("scan-search").onClick(() => run("bible-morph-search")));
            if (!isNativelyTagged(bible.version)) {
                m.addItem(i => i.setTitle("Connect this version to the original (approximate)").setIcon("link").onClick(() => run("bible-align-version")));
                m.addItem(i => i.setTitle("Review Strong's guesses").setIcon("list-checks").onClick(() => run("bible-review-guesses")));
            }
            m.addItem(i => i.setTitle("Write a note on this verse").setIcon("pencil").onClick(() => run("bible-write-commentary")));
            m.addSeparator();
        }
        m.addItem(i => i.setTitle("Ask the Bible…").setIcon("sparkles").onClick(() => run("bible-ask")));
        m.addItem(i => i.setTitle("Paste a chapter (new translation)…").setIcon("clipboard-paste").onClick(() => run("bible-paste-chapter")));
        if (editMode) m.addItem(i => i.setTitle("Insert a passage…").setIcon("book-open").onClick(() => run("bible-insert-passage")));
        m.addItem(i => i.setTitle("Create a reading plan…").setIcon("calendar-days").onClick(() => run("bible-reading-plan")));
    };

    // Parent "LoreMaster" item with the commands as a SUBMENU; fall back to a flat section on Obsidian
    // builds without submenu support.
    const addLoreMasterMenu = (menu: Menu, bible: { book: string; chapter: number; version: string } | null, editMode: boolean) => {
        let parent: any = null;
        menu.addItem(i => { parent = i; i.setTitle("LoreMaster").setIcon("book-open"); });
        const sub = parent?.setSubmenu?.();
        if (sub) fill(sub as Menu, bible, editMode);
        else fill(menu, bible, editMode);
    };

    // Reading view — no native editor menu fires there, so build one ourselves (Bible chapters only).
    // Capture phase: Obsidian handles `contextmenu` on the preview element and stops it before it would
    // bubble to document, so we intercept first.
    plugin.registerDomEvent(document, "contextmenu", (evt: MouseEvent) => {
        const el = evt.target as HTMLElement;
        if (!el?.closest?.(".markdown-reading-view, .markdown-preview-view")) return;
        if (el.closest(".markdown-source-view")) return;                 // Live Preview → editor-menu handles it
        const bible = bibleFromPath(plugin.app.workspace.getActiveFile()?.path);
        if (!bible) return;                                              // only take over inside a Bible chapter
        evt.preventDefault();
        evt.stopPropagation();
        const menu = new Menu();
        const sel = window.getSelection()?.toString();
        if (sel) menu.addItem(i => i.setTitle("Copy").setIcon("copy").onClick(() => { void navigator.clipboard?.writeText(sel); }));
        addLoreMasterMenu(menu, bible, false);
        menu.showAtMouseEvent(evt);
    }, { capture: true });

    // Edit / Live-Preview — append the same LoreMaster section to the native editor menu (all notes; the
    // Bible commands only populate when the note is a Bible chapter).
    plugin.registerEvent(plugin.app.workspace.on("editor-menu", (menu: Menu, _editor: Editor, view: any) => {
        addLoreMasterMenu(menu, bibleFromPath(view?.file?.path), true);
    }));
}

// ── Mobile: keep a focused input above the on-screen keyboard ────────────────
/** On phones the on-screen keyboard covers the lower half of the screen, hiding a centered modal's text
 *  input (reported on "Ask the Bible", but it happens in every modal). While an input/textarea is focused,
 *  top-align its modal and scroll the field into view so the keyboard can't cover it. General (any modal),
 *  active only on mobile and only while typing. */
export function registerMobileModalKeyboardFix(plugin: Plugin): void {
    if (!Platform.isMobile) return;
    const isField = (el: any): boolean => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    plugin.registerDomEvent(document, "focusin", (e: FocusEvent) => {
        const el = e.target as HTMLElement;
        if (!isField(el)) return;
        el.closest(".modal-container")?.addClass("lm-modal-kbd");
        window.setTimeout(() => el.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
    });
    plugin.registerDomEvent(document, "focusout", (e: FocusEvent) => {
        (e.target as HTMLElement)?.closest?.(".modal-container")?.removeClass("lm-modal-kbd");
    });
}

// ── Insert a passage into the current note ──────────────────────────────────
/** Parse "1-5", "1,3,5", or "3" (within one chapter) into an ascending, de-duplicated verse list. */
function parseVerseRange(spec: string): number[] {
    const out = new Set<number>();
    for (const part of (spec || "").split(",")) {
        const p = part.trim();
        const m = p.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
        if (m) {
            const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
            const lo = Math.min(a, b), hi = Math.max(a, b);
            for (let v = lo; v <= hi && v < lo + 200; v++) out.add(v);
        } else if (/^\d+$/.test(p)) {
            out.add(parseInt(p, 10));
        }
    }
    return [...out].sort((a, b) => a - b);
}

/** Read a verse range from the vault's Bible notes and format it as a quoted passage (blockquote with
 *  bold verse numbers, like the reader) plus a linked reference footer. */
async function buildPassageMarkdown(plugin: Plugin, book: string, chapter: number,
                                    versesSpec: string, version: string):
                                    Promise<{ text?: string; error?: string }> {
    const num = BOOK_NUM[book];
    if (!num) return { error: `Unknown book slug "${book}" (use e.g. john, 1-corinthians, psalms).` };
    if (!chapter) return { error: "Enter a chapter number." };
    const nums = parseVerseRange(versesSpec);
    if (!nums.length) return { error: "Enter verses like 1-5, 1,3,5, or 3." };
    const linkbase = `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(chapter)}`;
    // Confirm the passage exists so we don't insert a block that renders "not found".
    const exists = await readVerseText(plugin, linkbase, `v${nums[0]}`);
    if (!exists) return { error: `No verses found for ${bookLabel(book)} ${chapter} in "${version}". `
        + `Add that chapter first with "Bible: paste a chapter".` };
    // Emit a fenced block the plugin renders as ONE flowing paragraph, read live from the chapter note
    // each render (a link that displays the passage — not a copy) with the reader's paragraph look.
    const body = ["```bible-passage", `book: ${book}`, `chapter: ${chapter}`,
                  `verses: ${versesSpec.trim()}`, `version: ${version}`, "```", ""];
    return { text: body.join("\n") };
}

class InsertPassageModal extends Modal {
    constructor(private plugin: Plugin, private editor: Editor) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Insert a passage" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Embeds several verses here as a live transclusion from your Bible notes (a link that "
                + "displays the passage, not a copy), with a reference link back to the chapter." });
        let book = "", version = "web", chapter = "", verses = "";
        new Setting(contentEl).setName("Book").setDesc("slug — e.g. john, 1-corinthians, psalms")
            .addText(t => t.onChange(v => book = v));
        new Setting(contentEl).setName("Chapter").addText(t => { t.inputEl.type = "number"; t.onChange(v => chapter = v); });
        new Setting(contentEl).setName("Verses").setDesc("e.g. 1-5, or 1,3,5, or 3")
            .addText(t => t.onChange(v => verses = v));
        new Setting(contentEl).setName("Version").setDesc("web, kjv, esv, … (must be in your vault)")
            .addText(t => { t.setValue("web"); t.onChange(v => version = v); });
        new Setting(contentEl).addButton(b => b.setButtonText("Insert").setCta().onClick(async () => {
            const md = await buildPassageMarkdown(this.plugin, book.toLowerCase().trim(),
                parseInt(chapter, 10), verses, (version || "web").toLowerCase().trim());
            if ("error" in md) { new Notice(md.error!); return; }
            this.editor.replaceSelection(md.text!);
            this.close();
        }));
        setTimeout(() => (contentEl.querySelector("input") as HTMLInputElement | null)?.focus(), 0);
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the "paste a chapter" + "insert a passage" authoring commands. */
export function registerBiblePaste(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-paste-chapter",
        name: "Bible: paste a chapter (new translation)",
        callback: () => new BiblePasteModal(plugin).open(),
    });
    plugin.addCommand({
        id: "bible-insert-passage",
        name: "Bible: insert a passage (into this note)",
        editorCallback: (editor: Editor) => new InsertPassageModal(plugin, editor).open(),
    });
}

// ── Reading plans ────────────────────────────────────────────────────────────
// Chapters per book (canonical, 66 books) — used to build an evenly-divided reading plan.
const CHAPTERS: Record<string, number> = {
    genesis: 50, exodus: 40, leviticus: 27, numbers: 36, deuteronomy: 34, joshua: 24, judges: 21, ruth: 4,
    "1-samuel": 31, "2-samuel": 24, "1-kings": 22, "2-kings": 25, "1-chronicles": 29, "2-chronicles": 36,
    ezra: 10, nehemiah: 13, esther: 10, job: 42, psalms: 150, proverbs: 31, ecclesiastes: 12, "song-of-solomon": 8,
    isaiah: 66, jeremiah: 52, lamentations: 5, ezekiel: 48, daniel: 12, hosea: 14, joel: 3, amos: 9, obadiah: 1,
    jonah: 4, micah: 7, nahum: 3, habakkuk: 3, zephaniah: 3, haggai: 2, zechariah: 14, malachi: 4,
    matthew: 28, mark: 16, luke: 24, john: 21, acts: 28, romans: 16, "1-corinthians": 16, "2-corinthians": 13,
    galatians: 6, ephesians: 6, philippians: 4, colossians: 4, "1-thessalonians": 5, "2-thessalonians": 3,
    "1-timothy": 6, "2-timothy": 4, titus: 3, philemon: 1, hebrews: 13, james: 5, "1-peter": 5, "2-peter": 3,
    "1-john": 5, "2-john": 1, "3-john": 1, jude: 1, revelation: 22,
};
const PLAN_SCOPES: Record<string, (num: number) => boolean> = {
    "Whole Bible": () => true,
    "Old Testament": (n) => n < 40,
    "New Testament": (n) => n >= 40,
    "Gospels": (n) => n >= 40 && n <= 43,
    "Psalms & Proverbs": (n) => n === 19 || n === 20,
};

/** Ordered [book, chapter] list for a scope, in canonical order. */
function scopeChapters(scope: string): [string, number][] {
    const inScope = PLAN_SCOPES[scope] || (() => true);
    const out: [string, number][] = [];
    for (const slug of Object.keys(CHAPTERS)) {
        const num = BOOK_NUM[slug];
        if (!num || !inScope(num)) continue;
        for (let c = 1; c <= CHAPTERS[slug]; c++) out.push([slug, c]);
    }
    return out;
}

/** Build a dated, checkbox reading-plan note that divides a scope evenly across `days` days. */
function buildReadingPlan(scope: string, days: number, start: Date): { path: string; note: string } {
    const chapters = scopeChapters(scope);
    const perDay = chapters.length / days;
    const slugName = scope.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "");
    const fmt = (d: Date) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    const lines: string[] = ["---", "tags:", "  - bible", "  - reading-plan", "---",
        `# Reading plan — ${scope} (${days} days)`, "",
        `Started ${start.toLocaleDateString()}. Tick a day as you finish it.`, ""];
    let idx = 0;
    for (let d = 0; d < days; d++) {
        const upto = Math.round((d + 1) * perDay);
        const todays = chapters.slice(idx, upto);
        idx = upto;
        if (!todays.length) continue;
        const date = new Date(start); date.setDate(start.getDate() + d);
        const links = todays.map(([slug, c]) => {
            const n = BOOK_NUM[slug];
            return `[[bible/${pad2(n)}-${slug}/web/${slug}-${pad3(c)}|${bookLabel(slug)} ${c}]]`;
        });
        lines.push(`- [ ] **Day ${d + 1}** · ${fmt(date)} — ${links.join(", ")}`);
    }
    return { path: `bible/reading-plans/${slugName}-${days}day.md`, note: lines.join("\n") + "\n" };
}

class ReadingPlanModal extends Modal {
    constructor(private plugin: Plugin) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Create a Bible reading plan" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "A dated, tick-as-you-go plan that divides your chosen scope evenly across the days you pick." });
        let scope = "Whole Bible", days = 365;
        new Setting(contentEl).setName("Scope")
            .addDropdown(d => { for (const k of Object.keys(PLAN_SCOPES)) d.addOption(k, k); d.setValue(scope).onChange(v => scope = v); });
        new Setting(contentEl).setName("Days")
            .setDesc("How many days to spread it over (e.g. 365 for a year, 90 for a season).")
            .addText(t => { t.inputEl.type = "number"; t.setValue("365").onChange(v => days = Math.max(1, parseInt(v, 10) || 365)); });
        new Setting(contentEl).addButton(b => b.setButtonText("Create plan").setCta().onClick(async () => {
            const { path, note } = buildReadingPlan(scope, days, new Date());
            if (this.plugin.app.vault.getAbstractFileByPath(path)) { new Notice(`Already exists: ${path}`); return; }
            try { await this.plugin.app.vault.createFolder("bible/reading-plans"); } catch { /* exists */ }
            await this.plugin.app.vault.create(path, note);
            new Notice(`Created ${path}`);
            this.close();
            this.plugin.app.workspace.openLinkText(path, "", false);
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the "Bible: create a reading plan" command. */
export function registerBibleReadingPlan(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-reading-plan",
        name: "Bible: create a reading plan",
        callback: () => new ReadingPlanModal(plugin).open(),
    });
}

/** Append a verse's inline content to `p`, rebuilding red-letter/Strong's `<span>`s via DOM (never
 *  innerHTML — so vault content can't inject markup). */
function appendVerseInline(p: HTMLElement, raw: string): void {
    // Render text, turning \n (a poetic stich break) into <br>; leading em-spaces render as the indent.
    const emit = (parent: HTMLElement, text: string) => {
        text.split("\n").forEach((seg, i) => {
            if (i > 0) parent.createEl("br");
            // A continuation stich (after a <br>) gets its leading indent from the CSS hanging indent, so
            // drop any leading spaces/em-spaces in the source so they don't add a stray gap.
            const s = i > 0 ? seg.replace(/^\s+/, "") : seg;
            if (s) parent.appendText(s);
        });
    };
    const re = /<span class="(lm-wj|lm-s)"(?:\s+data-s="([^"]*)")?>([\s\S]*?)<\/span>/g;
    let last = 0, m: RegExpExecArray | null;
    while ((m = re.exec(raw))) {
        if (m.index > last) emit(p, raw.slice(last, m.index));
        const span = p.createEl("span", { cls: m[1] });
        if (m[2]) span.setAttr("data-s", m[2]);
        emit(span, m[3]);
        last = m.index + m[0].length;
    }
    if (last < raw.length) emit(p, raw.slice(last));
}

/** Render a ```bible-passage``` code block as ONE flowing quoted paragraph, read LIVE from the chapter
 *  note (so it tracks edits) — the reader's paragraph look, not stacked Obsidian block embeds. Body is
 *  key:value lines: book / chapter / verses / version. Inserted by "Bible: insert a passage". */
export function registerBiblePassageEmbed(plugin: Plugin): void {
    plugin.registerMarkdownCodeBlockProcessor("bible-passage", async (source, el, ctx) => {
        const cfg: Record<string, string> = {};
        for (const line of source.split(/\r?\n/)) {
            const m = line.match(/^\s*([a-z]+)\s*:\s*(.+?)\s*$/i);
            if (m) cfg[m[1].toLowerCase()] = m[2];
        }
        const book = (cfg.book || "").toLowerCase().trim();
        const chapter = parseInt(cfg.chapter || "", 10);
        const version = (cfg.version || "web").toLowerCase().trim();
        const num = BOOK_NUM[book];
        const box = el.createDiv("lm-passage");
        if (!num || !chapter || !cfg.verses) {
            box.createDiv("lm-passage-err").setText("Bible passage: set book, chapter and verses."); return;
        }
        const nums = parseVerseRange(cfg.verses);
        const linkbase = `bible/${pad2(num)}-${book}/${version}/${book}-${pad3(chapter)}`;
        // Read every verse first, so we can tell POETRY (a verse carries stich line-breaks) from prose.
        const verses: { v: number; raw: string }[] = [];
        for (const v of nums) {
            const raw = await readVerseRaw(plugin, linkbase, `v${v}`);
            if (raw) verses.push({ v, raw });
        }
        const got = verses.length;
        if (verses.some(x => x.raw.includes("\n"))) {
            // Poetry — each verse is its OWN hanging-indent block (verse number + first stich at the
            // margin, continuation stichs indented), like the reader; not one flowing blob.
            for (const { v, raw } of verses) {
                const line = box.createEl("p", { cls: "lm-passage-text lm-passage-poetry" });
                line.createEl("sup", { cls: "lm-passage-vnum", text: String(v) });
                line.appendText(" ");
                appendVerseInline(line, raw);
            }
        } else {
            // Prose — one flowing quoted paragraph with inline superscript verse numbers.
            const para = box.createEl("p", { cls: "lm-passage-text" });
            for (const { v, raw } of verses) {
                para.createEl("sup", { cls: "lm-passage-vnum", text: String(v) });
                para.appendText(" ");
                appendVerseInline(para, raw);
                para.appendText(" ");
            }
        }
        if (!got) {
            box.empty();
            box.createDiv("lm-passage-err").setText(
                `Passage not found: ${bookLabel(book)} ${chapter} (${version.toUpperCase()}). Add that chapter first.`);
            return;
        }
        const first = nums[0], last = nums[nums.length - 1];
        const range = first === last ? `${first}` : `${first}–${last}`;
        const href = `${linkbase}#^v${first}`;
        const cap = box.createDiv("lm-passage-ref");
        cap.createEl("a", { text: `— ${bookLabel(book)} ${chapter}:${range} (${version.toUpperCase()})`, attr: { href } })
            .addEventListener("click", (e) => {
                e.preventDefault();
                plugin.app.workspace.openLinkText(href, ctx.sourcePath, (e as MouseEvent).ctrlKey || (e as MouseEvent).metaKey);
            });
    });
}

// (The bottom nav is now BAKED into the note markdown — by formatPastedChapter for pasted chapters and
//  by the generator / a one-time migration for the rest — so it renders as a real block after the last
//  verse with no reading-view virtualization gap. The old file-open injector was removed.)

