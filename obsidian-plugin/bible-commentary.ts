// LoreMaster — personal Bible commentary. You write your own notes over time; each note declares the
// scripture it comments on via frontmatter `commentary-ref` (a string or a list):
//   commentary-ref: john.3.16          one verse
//   commentary-ref: john.3.16-18       a passage (same chapter)
//   commentary-ref: john.3             a whole chapter
// The reader marks annotated verses with a ✎ and lists your notes under the chapter. Notes can live
// anywhere; the "write a note" command puts them in bible-commentary/{book}/.

import { Plugin, TFile, MarkdownView, MarkdownPostProcessorContext, Modal, Setting, Notice, Menu } from "obsidian";
import { BOOK_NUM, pad3, bookLabel } from "./bible";

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
    private built = false;
    constructor(private plugin: Plugin) {}

    ensureBuilt(): void { if (!this.built) this.build(); }

    build(): void {
        this.built = true;
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
            const sup = p.createEl("sup");
            sup.appendText(" ");
            sup.createEl("a", { text: "✎", cls: "lm-comm-mark", href: "#",
                attr: { "aria-label": `${notes.length} note${notes.length === 1 ? "" : "s"}` } })
                .addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openNotes(plugin, notes, e as MouseEvent); });
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
    constructor(private plugin: Plugin, private book: string, private chapter: number) { super(plugin.app); }
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
                const body = `---\ncommentary-ref: ${ref}\ntags: [bible-commentary]\n---\n# ${title}\n\n`;
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
    plugin.app.workspace.onLayoutReady(() => index.build());
    plugin.registerEvent(plugin.app.metadataCache.on("resolved", () => index.schedule()));
    plugin.registerEvent(plugin.app.metadataCache.on("changed", () => index.schedule()));

    registerCommentaryMarkers(plugin, index);
    registerCommentarySection(plugin, index);

    plugin.addCommand({
        id: "bible-write-commentary",
        name: "Bible: write a note on this verse",
        checkCallback: (checking: boolean) => {
            const file = plugin.app.workspace.getActiveFile();
            if (!file || !file.path.startsWith("bible/")) return false;
            const pp = file.path.split("/");
            const book = pp[pp.length - 3]?.replace(/^\d+-/, "");
            const chapter = parseInt((pp[pp.length - 1].match(/-(\d+)\.md$/) || [])[1] || "", 10);
            if (!book || !chapter || !BOOK_NUM[book]) return false;
            if (!checking) new WriteCommentaryModal(plugin, book, chapter).open();
            return true;
        },
    });
}
