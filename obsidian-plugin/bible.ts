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
        // The verse isn't in this translation (e.g. only some chapters pasted) — fall back to the
        // World English Bible, which ships complete, and say so.
        const parts = ref.linkpath.split("/");
        if (parts.length >= 4) {
            parts[parts.length - 2] = "web";
            const webPath = parts.join("/");
            const webText = await readVerseText(plugin, webPath, ref.block);
            if (webText) {
                text = webText;
                openTarget = ref.block ? `${webPath}#^${ref.block}` : webPath;
                note = "Shown from the World English Bible — not in this translation.";
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

    const section = (title: string, items: any[]) => {
        if (!items.length) return;
        panel.createDiv("loremaster-bible-allxref-sub").setText(title);
        const list = panel.createDiv("loremaster-bible-allxref-list");
        for (const t of items) {
            const href = hrefFor(t);
            const a = list.createEl("a", { text: t.n, cls: "loremaster-bible-allxref-item", attr: { href } });
            // Tap a listed reference → the same read-card (verse text + Open) as the inline markers.
            a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); void showBibleHovercard(plugin, a, href); });
        }
    };
    section(`Cross-references (${xrefs.length})`, xrefs);
    section(`Related by meaning (${embeds.length})`, embeds);
    if (!xrefs.length && !embeds.length) panel.createDiv("loremaster-bible-allxref-sub").setText("No cross-references for this verse.");

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
            const targets = (data[`${book}.${chapter}.${vnum}`] || []).filter((t: any) => BOOK_NUM[t.b]);
            // Cross-reference markers (public-domain), quiet superscript letters. (Toggle: settings.)
            if (showXrefs) for (let i = 0; i < Math.min(targets.length, shown); i++) {
                const t = targets[i], href = hrefFor(t);
                const sup = p.createEl("sup");
                sup.appendText(" ");
                const a = sup.createEl("a", { text: SUP_LETTERS[i] || "*", cls: "lm-xref",
                    attr: { "data-href": href, href, "aria-label": t.n } });
                a.addEventListener("click", onMarkerClick(a, href));
            }
            // Embedding-similarity markers (verse index), distinct "≈" group, deduped against the
            // cross-references so a passage already cross-referenced isn't shown twice. (Toggle: settings.)
            const xset = new Set(targets.map((t: any) => `${t.b}.${t.c}.${t.v}`));
            const sims = (sim[vnum] || []).filter((t: any) => BOOK_NUM[t.b] && !xset.has(`${t.b}.${t.c}.${t.v}`));
            if (showEmbeds && sims.length) {
                const esup = p.createEl("sup", { cls: "lm-embed-group" });
                esup.appendText(" ≈");
                for (let i = 0; i < Math.min(sims.length, 2); i++) {
                    const t = sims[i], href = hrefFor(t);
                    esup.appendText(" ");   // space the ≈ markers apart (they used to run together)
                    const a = esup.createEl("a", { text: SUP_LETTERS[i] || "*", cls: "lm-embed-vlink",
                        attr: { "data-href": href, href, "aria-label": `≈ ${t.n}` } });
                    a.addEventListener("click", onMarkerClick(a, href));
                }
            }
            // Tap the verse number → study panel: Matthew Henry + your notes at top, then ALL
            // cross-references + related-by-meaning. Always available (Matthew Henry is offered for
            // every verse), even if a verse has no cross-references or inline markers are toggled off.
            num.addClass("lm-verse-num");
            num.setAttribute("aria-label", `Study ${bookLabel(book)} ${chapter}:${vnum}`);
            num.addEventListener("click", (ev) => {
                ev.preventDefault(); ev.stopPropagation();
                void showAllXrefs(plugin, num, `${bookLabel(book)} ${chapter}:${vnum}`,
                    book, chapter, parseInt(vnum, 10), version, targets, sims, hrefFor);
            });
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
function splitVerses(raw: string): Map<number, string> {
    const flat = cleanPaste(raw).replace(/\s+/g, " ");
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
            out.set(cur, flat.slice(start, start + loose.index).replace(/^[ .]+|[ .]+$/g, ""));
            cur = nxt; start = start + loose.index + loose[0].length;
        } else { out.set(cur, rest.replace(/^[ .]+|[ .]+$/g, "")); break; }
        if (nxt > 250) break;
    }
    for (const [k, v] of out) if (!v.trim()) out.delete(k);
    return out;
}
function formatPastedChapter(raw: string, bookSlug: string, chapter: number, version: string) {
    bookSlug = bookSlug.toLowerCase().trim();
    const num = BOOK_NUM[bookSlug];
    if (!num) return { error: `Unknown book slug "${bookSlug}" (use e.g. john, 1-corinthians, psalms).` };
    if (!chapter) return { error: "Enter a chapter number." };
    if (!version) return { error: "Enter a version (e.g. esv, nasb, nkjv)." };
    const verses = splitVerses(raw);
    if (!verses.size) return { error: "Couldn't find verse numbers in the pasted text." };
    const fm = ["---", "cssclasses:", "  - bible", `bible-version: ${version}`,
        `bible-book: ${bookSlug}`, `bible-booknum: ${num}`, `bible-chapter: ${chapter}`,
        // list form so Obsidian's property editor treats it as a LIST (add verse numbers as items)
        // rather than a number field that rejects commas.
        "bible-parastarts:", "  - 1", "---", "", `# ${bookLabel(bookSlug)} ${chapter}`, ""];
    const body = [...verses.keys()].sort((a, b) => a - b).map(n => `**${n}** ${verses.get(n)} ^v${n}`);
    return { path: `bible/${pad2(num)}-${bookSlug}/${version}/${bookSlug}-${pad3(chapter)}.md`,
             note: fm.concat(body).join("\n") + "\n", verses: verses.size };
}

class BiblePasteModal extends Modal {
    constructor(private plugin: Plugin) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Paste a Bible chapter" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Paste a chapter from a translation you're licensed to use. It's saved in the standard " +
                  "format so cross-references and related-by-meaning appear automatically." });
        let book = "", version = "", chapter = "";
        new Setting(contentEl).setName("Book").setDesc("slug — e.g. john, 1-corinthians, psalms")
            .addText(t => t.onChange(v => book = v));
        new Setting(contentEl).setName("Chapter").addText(t => { t.inputEl.type = "number"; t.onChange(v => chapter = v); });
        new Setting(contentEl).setName("Version").setDesc("e.g. esv, nasb, nkjv").addText(t => t.onChange(v => version = v));
        const ta = contentEl.createEl("textarea", { attr: { rows: "12", placeholder: "Paste the chapter text here…" } });
        ta.style.cssText = "width:100%;font-family:var(--font-monospace);";
        new Setting(contentEl).addButton(b => b.setButtonText("Format & save").setCta().onClick(async () => {
            const r = formatPastedChapter(ta.value, book, parseInt(chapter, 10), version.toLowerCase().trim());
            if ("error" in r) { new Notice(r.error!); return; }
            if (this.plugin.app.vault.getAbstractFileByPath(r.path)) { new Notice(`Already exists: ${r.path}`); return; }
            const folder = r.path.split("/").slice(0, -1).join("/");
            try { await this.plugin.app.vault.createFolder(folder); } catch { /* exists */ }
            await this.plugin.app.vault.create(r.path, r.note);
            new Notice(`Saved ${r.verses} verses → ${r.path}`);
            this.close();
            this.plugin.app.workspace.openLinkText(r.path, "", false);
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

// ── Manual annotation (works in ANY translation) ────────────────────────────
// Select text in a Bible note (edit / Live Preview) and right-click to: highlight it, mark it as the
// words of Christ (red), or tag a word with a Strong's number. These wrap the selection in the same
// markup the reader already renders (==highlight==, <span class="lm-wj">, <span class="lm-s" data-s>),
// so red-letter, highlighting and Strong's hover work in KJV, ESV, pasted chapters — anything.
class StrongsInputModal extends Modal {
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
}

/** Register the "paste a chapter from another translation" command. */
export function registerBiblePaste(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-paste-chapter",
        name: "Bible: paste a chapter (new translation)",
        callback: () => new BiblePasteModal(plugin).open(),
    });
}

// ── Licensed online versions (ESV / NASB / NKJV) — fetched via the backend proxy, cached in the
//    vault as normal bible notes so they're only ever fetched once and get the full reader treatment.
const VERSION_LABELS: Record<string, string> = { esv: "ESV", nasb: "NASB", nkjv: "NKJV" };

function versionCachePath(bookSlug: string, chapter: number, version: string): string | null {
    const num = BOOK_NUM[bookSlug];
    if (!num) return null;
    return `bible/${pad2(num)}-${bookSlug}/${version}/${bookSlug}-${pad3(chapter)}.md`;
}

/** Build a standard bible note from fetched verses (+ a visible copyright footer, which the
 *  licenses require). Paragraph metadata isn't available from the text APIs, so the whole chapter
 *  is one paragraph (flow layout still works; cross-refs/red-letter come from the reader). */
function formatVersionChapter(verses: Record<string, string>, bookSlug: string, chapter: number,
                              version: string, copyright: string): { path: string; note: string; verses: number } | { error: string } {
    const num = BOOK_NUM[bookSlug];
    if (!num) return { error: `Unknown book slug "${bookSlug}".` };
    const nums = Object.keys(verses).map(n => parseInt(n, 10)).filter(n => n > 0).sort((a, b) => a - b);
    if (!nums.length) return { error: "No verses returned." };
    const fm = ["---", "cssclasses:", "  - bible", `bible-version: ${version}`,
        `bible-book: ${bookSlug}`, `bible-booknum: ${num}`, `bible-chapter: ${chapter}`,
        "bible-parastarts: 1"];
    if (copyright) fm.push(`bible-copyright: ${JSON.stringify(copyright)}`);
    fm.push("---", "", `# ${bookLabel(bookSlug)} ${chapter}`, "");
    const body = nums.map(n => `**${n}** ${verses[String(n)]} ^v${n}`);
    const footer = copyright ? ["", "---", "", `*${copyright}*`] : [];
    return { path: versionCachePath(bookSlug, chapter, version)!,
             note: fm.concat(body, footer).join("\n") + "\n", verses: nums.length };
}

/** ESV's API terms cap cached verses at 500. Before adding an ESV chapter, trash the oldest cached
 *  ESV chapter notes (vault-local trash, recoverable) until the new one fits. */
async function enforceEsvCap(plugin: Plugin, adding: number): Promise<number> {
    const CAP = 500;
    const files = plugin.app.vault.getFiles().filter(f =>
        f.path.startsWith("bible/") && f.path.includes("/esv/")
        && f.path.endsWith(".md") && !f.path.endsWith("/esv.md"));
    const infos: { f: TFile; n: number; mtime: number }[] = [];
    let total = 0;
    for (const f of files) {
        const c = await plugin.app.vault.cachedRead(f);
        const n = (c.match(/\^v\d+/g) || []).length;
        infos.push({ f, n, mtime: f.stat.mtime });
        total += n;
    }
    infos.sort((a, b) => a.mtime - b.mtime);   // oldest first
    let evicted = 0, i = 0;
    while (total + adding > CAP && i < infos.length) {
        try { await plugin.app.vault.trash(infos[i].f, false); total -= infos[i].n; evicted++; } catch { /* skip */ }
        i++;
    }
    return evicted;
}

class BibleVersionModal extends Modal {
    constructor(private plugin: Plugin) { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: "Get a Bible chapter (online version)" });
        contentEl.createEl("p", { cls: "setting-item-description",
            text: "Fetches from a licensed version via your local service and saves it in the vault, " +
                  "so it's only fetched once. Requires the version's API key in the service settings." });
        let book = "", version = "esv", chapter = "";
        new Setting(contentEl).setName("Version")
            .addDropdown(d => d.addOption("esv", "ESV").addOption("nasb", "NASB").addOption("nkjv", "NKJV")
                .setValue("esv").onChange(v => version = v));
        new Setting(contentEl).setName("Book").setDesc("slug — e.g. john, 1-corinthians, psalms")
            .addText(t => t.onChange(v => book = v));
        new Setting(contentEl).setName("Chapter")
            .addText(t => { t.inputEl.type = "number"; t.onChange(v => chapter = v); });
        const status = contentEl.createEl("p", { cls: "setting-item-description" });
        new Setting(contentEl).addButton(b => b.setButtonText("Get & open").setCta().onClick(async () => {
            const slug = book.toLowerCase().trim(), ch = parseInt(chapter, 10), ver = version.toLowerCase().trim();
            const path = versionCachePath(slug, ch, ver);
            if (!path) { status.setText(`Unknown book slug "${slug}".`); return; }
            // Already cached → just open it (no fetch).
            if (this.plugin.app.vault.getAbstractFileByPath(path)) {
                this.close();
                this.plugin.app.workspace.openLinkText(path, "", false);
                return;
            }
            status.setText(`Fetching ${VERSION_LABELS[ver] || ver} ${bookLabel(slug)} ${ch}…`);
            const s = (this.plugin as any).settings;
            let data: any;
            try {
                const r = await fetch(`http://${s.host}:${s.port}/bible/passage?version=${ver}&book=${slug}&chapter=${ch}`,
                    { headers: s.apiToken ? { "X-API-Key": s.apiToken } : {}, signal: timeoutSignal(20000) });
                data = await r.json();
            } catch (e) { status.setText(`Service unreachable: ${e}`); return; }
            if (!data || data.error || !data.ok) { status.setText(data?.error || "Fetch failed."); return; }
            const built = formatVersionChapter(data.verses || {}, slug, ch, ver, data.copyright || "");
            if ("error" in built) { status.setText(built.error); return; }
            if (ver === "esv") {
                const evicted = await enforceEsvCap(this.plugin, built.verses);
                if (evicted) new Notice(`Removed ${evicted} older ESV chapter(s) to stay within the 500-verse cache limit.`);
            }
            const folder = built.path.split("/").slice(0, -1).join("/");
            try { await this.plugin.app.vault.createFolder(folder); } catch { /* exists */ }
            await this.plugin.app.vault.create(built.path, built.note);
            new Notice(`Saved ${built.verses} verses → ${built.path}`);
            this.close();
            this.plugin.app.workspace.openLinkText(built.path, "", false);
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the "get a chapter from a licensed online version (ESV/NASB/NKJV)" command. */
export function registerBibleVersions(plugin: Plugin): void {
    plugin.addCommand({
        id: "bible-get-version-chapter",
        name: "Bible: get a chapter (ESV / NASB / NKJV)",
        callback: () => new BibleVersionModal(plugin).open(),
    });
}
