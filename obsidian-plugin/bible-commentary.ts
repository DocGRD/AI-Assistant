// LoreMaster — personal Bible commentary. You write your own notes over time; each note declares the
// scripture it comments on via frontmatter `commentary-ref` (a string or a list):
//   commentary-ref: john.3.16          one verse
//   commentary-ref: john.3.16-18       a passage (same chapter)
//   commentary-ref: john.3             a whole chapter
// The reader marks annotated verses with a ✎ and lists your notes under the chapter. Notes can live
// anywhere; the "write a note" command puts them in bible-commentary/{book}/.

import { Plugin, TFile, MarkdownView, MarkdownPostProcessorContext, Modal, Setting, Notice, Menu, Editor } from "obsidian";
import { BOOK_NUM, pad2, pad3, bookLabel, readVerseText } from "./bible";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** Parse a commentary-ref value into the canonical verse keys ("book.ch.v") + chapter key it covers. */
function expandRef(raw: string): { verses: string[]; chapter: string | null } {
    const s = String(raw).trim().toLowerCase();
    let m = s.match(/^([a-z0-9-]+)\.(\d+)\.(\d+)(?:-(\d+))?$/);   // book.ch.v or book.ch.v-v2
    if (m && BOOK_NUM[m[1]]) {
        const book = m[1], ch = parseInt(m[2], 10);
        const a = parseInt(m[3], 10), b = m[4] ? parseInt(m[4], 10) : a;
        const verses: string[] = [];
        for (let v = a; v <= b && v < a + 200; v++) verses.push(`${book}.${ch}.${v}`);
        return { verses, chapter: `${book}.${ch}` };
    }
    m = s.match(/^([a-z0-9-]+)\.(\d+)$/);                          // whole chapter
    if (m && BOOK_NUM[m[1]]) return { verses: [], chapter: `${m[1]}.${parseInt(m[2], 10)}` };
    return { verses: [], chapter: null };
}

/** Index of commentary notes, keyed by verse ("book.ch.v") and by chapter ("book.ch"). */
class CommentaryIndex {
    byVerse = new Map<string, TFile[]>();
    byChapter = new Map<string, TFile[]>();
    private timer: number | null = null;
    private dirty = true;   // needs a (re)build — set whenever a note's metadata changes
    constructor(private plugin: Plugin) {}

    markDirty(): void { this.dirty = true; }
    /** Rebuild only if something changed since the last build — so the NEXT reader render always
     *  reflects a just-created/edited commentary note (fixes the stale-index race across versions). */
    ensureBuilt(): void { if (this.dirty) this.build(); }

    build(): void {
        this.dirty = false;
        this.byVerse.clear(); this.byChapter.clear();
        for (const f of this.plugin.app.vault.getMarkdownFiles()) {
            const fm = this.plugin.app.metadataCache.getFileCache(f)?.frontmatter;
            const raw = fm?.["commentary-ref"] ?? fm?.["commentary-refs"];
            if (!raw) continue;
            for (const one of Array.isArray(raw) ? raw : [raw]) {
                const { verses, chapter } = expandRef(one);
                for (const vk of verses) this.push(this.byVerse, vk, f);
                if (chapter) this.push(this.byChapter, chapter, f);
            }
        }
    }
    private push(map: Map<string, TFile[]>, key: string, f: TFile): void {
        const arr = map.get(key) || [];
        if (!arr.includes(f)) { arr.push(f); map.set(key, arr); }
    }
    schedule(): void {
        if (this.timer) window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => this.build(), 800);
    }
}

// The active index, shared so the verse-number "study" popup (bible.ts) can list your commentary
// notes for a verse without owning its own index.
let sharedIndex: CommentaryIndex | null = null;
/** Your commentary notes that comment on a specific verse ("book" slug + chapter + verse). */
export function commentaryNotesForVerse(book: string, chapter: number, verse: number): TFile[] {
    if (!sharedIndex) return [];
    sharedIndex.ensureBuilt();
    return (sharedIndex.byVerse.get(`${book}.${chapter}.${verse}`) || []).slice();
}

// ── Matthew Henry lookup (shared: the reader header link AND the verse-number study popup) ──
const MHC_DIR = "AI/Library/matthew-henry";
let mhcIdxPromise: Promise<Record<string, string>> | null = null;
function loadMhcIndex(plugin: Plugin): Promise<Record<string, string>> {
    return (mhcIdxPromise ??= plugin.app.vault.adapter.read("AI/bible-mhc.json")
        .then(s => JSON.parse(s) as Record<string, string>).catch(() => ({})));
}
/** Vault path (no extension) of the Matthew Henry note for a book number + chapter, or null. */
export async function mhcNoteFor(plugin: Plugin, booknum: number, chapter: number): Promise<string | null> {
    const id = (await loadMhcIndex(plugin))[`${booknum}:${chapter}`];
    return id ? `${MHC_DIR}/${id}` : null;
}

/** Reader overlay: a link to Matthew Henry's Complete Commentary for the open chapter.
 *  The mapping "<booknum>:<chapter>" -> mhc note id lives in AI/bible-mhc.json (built by
 *  assistant_core/bible/tools/gen_mhc_index.py). We inject the link right under the chapter title
 *  so it works on every existing note without rewriting any files. */
export function registerMatthewHenryLink(plugin: Plugin): void {
    plugin.registerMarkdownPostProcessor(async (el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        const path = ctx.sourcePath || "";
        if (!path.startsWith("bible/")) return;
        const h1 = (el.tagName === "H1" ? el : el.querySelector("h1")) as HTMLElement | null;
        if (!h1) return;
        if (h1.nextElementSibling?.classList?.contains("lm-mhc-link")) return;   // already injected
        const pp = path.split("/");
        if (pp.length < 4) return;
        const book = pp[pp.length - 3].replace(/^\d+-/, "");
        const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        const num = BOOK_NUM[book];
        if (!num || !chapter) return;

        const target = await mhcNoteFor(plugin, num, chapter);
        if (!target) return;                                 // no commentary for this chapter
        const div = createDiv("lm-mhc-link");
        div.createEl("a", { text: `📖 Matthew Henry on ${bookLabel(book)} ${chapter}`, href: target })
            .addEventListener("click", (e) => {
                e.preventDefault();
                plugin.app.workspace.openLinkText(target, ctx.sourcePath, (e as MouseEvent).ctrlKey || (e as MouseEvent).metaKey);
            });
        h1.insertAdjacentElement("afterend", div);
    });
}

/** Open a commentary note (or a menu if a verse has several). */
function openNotes(plugin: Plugin, notes: TFile[], evt: MouseEvent): void {
    if (notes.length === 1) { plugin.app.workspace.openLinkText(notes[0].path, "", evt.ctrlKey || evt.metaKey); return; }
    const menu = new Menu();
    for (const n of notes) menu.addItem(i => i.setTitle(n.basename).setIcon("pencil")
        .onClick(() => plugin.app.workspace.openLinkText(n.path, "", false)));
    menu.showAtMouseEvent(evt);
}

/** Reader overlay: a ✎ marker after any verse you've written on. */
export function registerCommentaryMarkers(plugin: Plugin, index: CommentaryIndex): void {
    plugin.registerMarkdownPostProcessor((el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        const path = ctx.sourcePath || "";
        if (!path.startsWith("bible/")) return;
        const pp = path.split("/");
        if (pp.length < 4) return;
        const book = pp[pp.length - 3].replace(/^\d+-/, "");
        const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        if (!book || !chapter) return;
        index.ensureBuilt();

        const paras = Array.from(el.querySelectorAll("p")) as HTMLParagraphElement[];
        if (el.tagName === "P") paras.push(el as HTMLParagraphElement);
        for (const p of paras) {
            const s = p.firstElementChild;
            if (!s || s.tagName !== "STRONG" || !/^\d+$/.test((s.textContent || "").trim())) continue;
            if (p.hasAttribute("data-lm-comm")) continue;
            const vnum = (s.textContent || "").trim();
            const notes = index.byVerse.get(`${book}.${chapter}.${vnum}`);
            if (!notes || !notes.length) continue;
            p.setAttribute("data-lm-comm", "1");
            // Marker sits right after the verse NUMBER (not at the end of the verse) so it reads as
            // "this verse has a note", next to what it annotates.
            const sup = createEl("sup", { cls: "lm-comm-sup" });
            sup.createEl("a", { text: "✎", cls: "lm-comm-mark", href: "#",
                attr: { "aria-label": `${notes.length} note${notes.length === 1 ? "" : "s"}` } })
                .addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openNotes(plugin, notes, e as MouseEvent); });
            s.insertAdjacentElement("afterend", sup);
        }
    });
}

/** Reader overlay: a "Commentary" section at the chapter foot listing your notes for the chapter. */
export function registerCommentarySection(plugin: Plugin, index: CommentaryIndex): void {
    const inject = async (file: TFile) => {
        if (!file || !file.path.startsWith("bible/")) return;
        const pp = file.path.split("/");
        if (pp.length < 4) return;
        const book = pp[pp.length - 3].replace(/^\d+-/, "");
        const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
        if (!book || !chapter) return;

        let sizer: HTMLElement | null = null;
        for (let i = 0; i < 10; i++) {
            await sleep(400);
            const view = plugin.app.workspace.getActiveViewOfType(MarkdownView);
            if (!view || view.file !== file) continue;
            const c = view.contentEl.querySelector(
                ".markdown-preview-view.bible .markdown-preview-sizer, .markdown-reading-view.bible .markdown-preview-sizer") as HTMLElement | null;
            if (c && c.querySelector("p")) { sizer = c; break; }
        }
        if (!sizer || sizer.querySelector(".lm-comm-section")) return;
        index.build();   // fresh at render time — the debounced rebuild may not have run yet

        // gather notes for this chapter (chapter-level + any verse-level), de-duplicated
        const seen = new Set<string>();
        const items: { file: TFile; label: string }[] = [];
        const add = (f: TFile, label: string) => { if (!seen.has(f.path)) { seen.add(f.path); items.push({ file: f, label }); } };
        for (const f of index.byChapter.get(`${book}.${chapter}`) || []) add(f, f.basename);
        for (let v = 1; v < 400; v++)
            for (const f of index.byVerse.get(`${book}.${chapter}.${v}`) || []) add(f, `${v}: ${f.basename}`);
        if (!items.length) return;

        const sec = sizer.createDiv("lm-comm-section");
        sec.createDiv("lm-comm-head").setText("Commentary");
        const list = sec.createDiv("lm-comm-list");
        for (const it of items)
            list.createEl("a", { text: it.label, cls: "lm-comm-link", href: it.file.path })
                .addEventListener("click", (e) => { e.preventDefault(); plugin.app.workspace.openLinkText(it.file.path, "", (e as MouseEvent).ctrlKey || (e as MouseEvent).metaKey); });
    };
    plugin.registerEvent(plugin.app.workspace.on("file-open", (file) => { if (file) void inject(file); }));
}

/** Modal: create/open a commentary note for a verse (or passage) of the active chapter. */
class WriteCommentaryModal extends Modal {
    constructor(private plugin: Plugin, private book: string, private chapter: number,
                private version: string = "web") { super(plugin.app); }
    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: `Write a note — ${bookLabel(this.book)} ${this.chapter}` });
        let from = "", to = "";
        new Setting(contentEl).setName("Verse").setDesc("the verse you're commenting on")
            .addText(t => { t.inputEl.type = "number"; t.onChange(v => from = v); });
        new Setting(contentEl).setName("Through (optional)").setDesc("for a passage, the last verse")
            .addText(t => { t.inputEl.type = "number"; t.onChange(v => to = v); });
        new Setting(contentEl).addButton(b => b.setButtonText("Create / open note").setCta().onClick(async () => {
            const a = parseInt(from, 10);
            if (!a) { new Notice("Enter a verse number."); return; }
            const b2 = parseInt(to, 10);
            const ref = b2 && b2 > a ? `${this.book}.${this.chapter}.${a}-${b2}` : `${this.book}.${this.chapter}.${a}`;
            const suffix = b2 && b2 > a ? `${a}-${b2}` : `${a}`;
            const path = `bible-commentary/${this.book}/${this.book}-${pad3(this.chapter)}-${suffix}.md`;
            let file = this.plugin.app.vault.getAbstractFileByPath(path);
            if (!(file instanceof TFile)) {
                const folder = `bible-commentary/${this.book}`;
                try { await this.plugin.app.vault.createFolder(folder); } catch { /* exists */ }
                const title = `${bookLabel(this.book)} ${this.chapter}:${suffix}`;
                // Embed the verse as a LIVE bible-passage block (a link that displays it from the chapter
                // note) rather than copying the text — so if the source changes, the quote here updates.
                // Then just a "Commentary" heading for YOU to write under. No AI-generated content.
                const passage = ["```bible-passage", `book: ${this.book}`, `chapter: ${this.chapter}`,
                    `verses: ${suffix}`, `version: ${this.version}`, "```", "", ""].join("\n");
                const body = `---\ncommentary-ref: ${ref}\ntags: [bible-commentary]\n---\n# ${title}\n\n${passage}## Commentary\n\n`;
                file = await this.plugin.app.vault.create(path, body);
            }
            this.close();
            this.plugin.app.workspace.openLinkText((file as TFile).path, "", false);
        }));
    }
    onClose(): void { this.contentEl.empty(); }
}

/** Register the commentary index, overlays, and the "write a note" command. */
export function registerBibleCommentary(plugin: Plugin): void {
    const index = new CommentaryIndex(plugin);
    sharedIndex = index;   // let the verse-number study popup (bible.ts) read it
    plugin.app.workspace.onLayoutReady(() => index.build());
    // Mark dirty immediately (so the next reader render rebuilds) AND schedule a debounced rebuild.
    plugin.registerEvent(plugin.app.metadataCache.on("resolved", () => { index.markDirty(); index.schedule(); }));
    plugin.registerEvent(plugin.app.metadataCache.on("changed", () => { index.markDirty(); index.schedule(); }));

    registerCommentaryMarkers(plugin, index);
    registerCommentarySection(plugin, index);
    // Matthew Henry is reachable from the verse-number study popup (mhcNoteFor); the per-chapter
    // header link is intentionally NOT injected (removed per feedback — it cluttered the chapter top).

    plugin.addCommand({
        id: "bible-write-commentary",
        name: "Bible: write a note on this verse",
        checkCallback: (checking: boolean) => {
            const file = plugin.app.workspace.getActiveFile();
            if (!file || !file.path.startsWith("bible/")) return false;
            const pp = file.path.split("/");
            const book = pp[pp.length - 3]?.replace(/^\d+-/, "");
            const version = pp[pp.length - 2] || "web";
            const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
            if (!book || !chapter || !BOOK_NUM[book]) return false;
            if (!checking) new WriteCommentaryModal(plugin, book, chapter, version).open();
            return true;
        },
    });

    registerWordNotes(plugin);
}

/** Word-level notes: select a word or phrase in a Bible chapter and attach a note to it. The selection
 *  is wrapped in a `<span class="lm-wnote" data-note="…">` and the reader shows a 📝 at the FRONT of it
 *  that opens the note. The note itself is a normal commentary note (carries `commentary-ref`, so it
 *  also appears in the verse's ✎ list). */
export function registerWordNotes(plugin: Plugin): void {
    // Reader: decorate each lm-wnote span with a leading 📝 icon (once).
    plugin.registerMarkdownPostProcessor((el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        if (!ctx.sourcePath?.startsWith("bible/")) return;
        el.querySelectorAll("span.lm-wnote").forEach((span) => {
            if ((span as HTMLElement).querySelector(".lm-wnote-icon")) return;
            span.prepend(createSpan({ cls: "lm-wnote-icon", text: "📝" }));
        });
    });
    // Reader: tapping a word-note (icon or text) opens its note. Delegated so it survives re-renders.
    plugin.registerDomEvent(document, "click", (evt: MouseEvent) => {
        const t = evt.target as HTMLElement | null;
        const span = t?.closest?.("span.lm-wnote") as HTMLElement | null;
        if (!span || !span.closest(".markdown-preview-view.bible, .markdown-reading-view.bible")) return;
        const path = span.getAttribute("data-note");
        if (!path) return;
        evt.preventDefault(); evt.stopPropagation();
        plugin.app.workspace.openLinkText(path, "", evt.ctrlKey || evt.metaKey);
    });

    plugin.addCommand({
        id: "bible-attach-word-note",
        name: "Bible: attach a note to selection",
        editorCallback: async (editor: Editor) => {
            const file = plugin.app.workspace.getActiveFile();
            if (!file || !file.path.startsWith("bible/")) { new Notice("Open a Bible chapter first."); return; }
            const sel = editor.getSelection().trim();
            if (!sel) { new Notice("Select the word(s) the note should attach to."); return; }
            const pp = file.path.split("/");
            const book = pp[pp.length - 3].replace(/^\d+-/, "");
            const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
            if (!BOOK_NUM[book] || !chapter) { new Notice("This doesn't look like a Bible chapter."); return; }
            // Derive the verse: walk up from the selection start to the nearest **N** line.
            let verse = 0;
            for (let ln = editor.getCursor("from").line; ln >= 0; ln--) {
                const m = editor.getLine(ln).match(/^\*\*(\d+)\*\*/);
                if (m) { verse = parseInt(m[1], 10); break; }
            }
            const slug = sel.toLowerCase().replace(/<[^>]*>/g, "").replace(/[^a-z0-9]+/g, "-")
                .replace(/^-|-$/g, "").slice(0, 24) || "words";
            const stamp = Date.now().toString(36).slice(-4);
            const notePath = `bible-commentary/${book}/${book}-${pad3(chapter)}-${verse || "x"}-${slug}-${stamp}.md`;
            const label = `${bookLabel(book)} ${chapter}${verse ? `:${verse}` : ""}`;
            const clean = sel.replace(/<[^>]*>/g, "");
            const ref = verse ? `commentary-ref: ${book}.${chapter}.${verse}\n` : "";
            const bodyNote = `---\n${ref}tags: [bible-commentary, word-note]\n---\n# ${label} — “${clean}”\n\n> ${clean}\n\n## Note\n\n`;
            try { await plugin.app.vault.createFolder(`bible-commentary/${book}`); } catch { /* exists */ }
            if (plugin.app.vault.getAbstractFileByPath(notePath)) { new Notice("A note for that already exists."); return; }
            await plugin.app.vault.create(notePath, bodyNote);
            editor.replaceSelection(`<span class="lm-wnote" data-note="${notePath}">${sel}</span>`);
            plugin.app.workspace.openLinkText(notePath, file.path, false);
        },
    });
}
