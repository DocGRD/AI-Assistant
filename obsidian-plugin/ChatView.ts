import { ItemView, WorkspaceLeaf, MarkdownRenderer, MarkdownView, Menu, Modal, Notice, TFile, FuzzySuggestModal } from "obsidian";
import type { App, Editor, EditorPosition } from "obsidian";
import type AIAssistantPlugin from "./main";

// M12 — fuzzy note picker for @-mentions (robust; no fragile textarea autocomplete).
class NotePickerModal extends FuzzySuggestModal<TFile> {
    private onPick: (file: TFile) => void;
    constructor(app: App, onPick: (file: TFile) => void) {
        super(app);
        this.onPick = onPick;
        this.setPlaceholder("Add a note as context…");
    }
    getItems(): TFile[] { return this.app.vault.getMarkdownFiles(); }
    getItemText(file: TFile): string { return file.path; }
    onChooseItem(file: TFile): void { this.onPick(file); }
}

// M13 — picker over saved prompts in AI/Prompts/.
class PromptPickerModal extends FuzzySuggestModal<TFile> {
    private onPick: (file: TFile) => void;
    constructor(app: App, onPick: (file: TFile) => void) {
        super(app);
        this.onPick = onPick;
        this.setPlaceholder("Run a saved prompt…");
    }
    getItems(): TFile[] {
        return this.app.vault.getMarkdownFiles().filter(f => f.path.startsWith("AI/Prompts/"));
    }
    getItemText(file: TFile): string { return file.basename; }
    onChooseItem(file: TFile): void { this.onPick(file); }
}

// M18 — knowledge-graph subgraph viewer. Fetches GET /graph and draws a radial SVG
// (centre entity + neighbours); click a neighbour to recentre, or open a source note.
interface GraphNode { id: string; type: string; sources: string[]; }
interface GraphEdge { source: string; target: string; rel: string; }

class GraphViewerModal extends Modal {
    private host: string; private port: number; private token: string;
    private node: string;
    private inputEl!: HTMLInputElement;
    private svgWrap!: HTMLElement;
    private entitiesEl!: HTMLElement;

    constructor(app: App, host: string, port: number, token: string, startNode: string) {
        super(app);
        this.host = host; this.port = port; this.token = token; this.node = startNode;
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.createEl("h3", { text: "Knowledge graph" });
        const bar = contentEl.createDiv();
        bar.style.display = "flex"; bar.style.gap = "6px"; bar.style.marginBottom = "8px";
        this.inputEl = bar.createEl("input", { type: "text", value: this.node });
        this.inputEl.style.flex = "1";
        this.inputEl.placeholder = "Entity name (e.g. Rocket Mass Heater)";
        const go = bar.createEl("button", { text: "Show" });
        go.addEventListener("click", () => { this.node = this.inputEl.value.trim(); void this.load(); });
        const browse = bar.createEl("button", { text: "Browse all" });
        browse.addEventListener("click", () => { this.node = ""; this.inputEl.value = ""; void this.load(); });
        this.inputEl.addEventListener("keydown", (e) => {
            if (e.key === "Enter") { this.node = this.inputEl.value.trim(); void this.load(); }
        });
        this.svgWrap = contentEl.createDiv();
        this.entitiesEl = contentEl.createDiv();
        void this.load();
    }

    private headers(): Record<string, string> {
        return this.token ? { "X-API-Key": this.token } : {};
    }

    private async load(): Promise<void> {
        this.svgWrap.empty();
        this.entitiesEl.empty();
        if (!this.node) { await this.loadEntities(); return; }   // no node → browse the list
        try {
            const url = `http://${this.host}:${this.port}/graph?node=${encodeURIComponent(this.node)}&depth=1`;
            const resp = await fetch(url, { headers: this.headers(), signal: AbortSignal.timeout(4000) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json() as { nodes: GraphNode[]; edges: GraphEdge[] };
            if (data.nodes.length === 0) {                        // unknown node → offer the list
                this.svgWrap.setText(`No graph node named "${this.node}". Pick one below, or build ` +
                    `the graph with vault:graph <note>.`);
                await this.loadEntities();
                return;
            }
            this.render(data);
        } catch (e) {
            this.svgWrap.setText(`Could not load graph (${e instanceof Error ? e.message : e}). ` +
                `Is the service running and the graph built (vault:graph)?`);
        }
    }

    private async loadEntities(): Promise<void> {
        this.entitiesEl.empty();
        try {
            const resp = await fetch(`http://${this.host}:${this.port}/graph/entities?limit=200`,
                { headers: this.headers(), signal: AbortSignal.timeout(4000) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json() as { entities: { id: string; degree: number; type: string }[] };
            if (!data.entities.length) {
                this.entitiesEl.setText("No entities yet. Build the graph with vault:graph <note> " +
                    "(or the nightly build), then reopen.");
                return;
            }
            this.entitiesEl.createEl("div", {
                text: `Entities (${data.entities.length}) — most-connected first; click to explore:`,
            }).style.cssText = "font-size:12px;color:var(--text-muted);margin:8px 0 4px;";
            const wrap = this.entitiesEl.createDiv();
            wrap.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;max-height:220px;overflow:auto;";
            for (const e of data.entities) {
                const chip = wrap.createEl("button", { text: `${e.id} (${e.degree})` });
                chip.style.cssText = "font-size:12px;padding:2px 8px;";
                chip.addEventListener("click", () => { this.node = e.id; this.inputEl.value = e.id; void this.load(); });
            }
        } catch (e) {
            this.entitiesEl.setText(`Could not load entities (${e instanceof Error ? e.message : e}).`);
        }
    }

    private render(data: { nodes: GraphNode[]; edges: GraphEdge[] }): void {
        this.svgWrap.empty();
        if (data.nodes.length === 0) {
            this.svgWrap.setText(`No graph node named "${this.node}". Build it with vault:graph <note>.`);
            return;
        }
        const W = 520, H = 380, cx = W / 2, cy = H / 2, R = 130;
        const NS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(NS, "svg");
        svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
        svg.setAttribute("width", "100%"); svg.setAttribute("height", `${H}`);

        const others = data.nodes.filter(n => n.id !== this.node);
        const pos: Record<string, { x: number; y: number }> = { [this.node]: { x: cx, y: cy } };
        others.forEach((n, i) => {
            const a = (2 * Math.PI * i) / Math.max(1, others.length);
            pos[n.id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) };
        });

        for (const e of data.edges) {
            const a = pos[e.source], b = pos[e.target];
            if (!a || !b) continue;
            const line = document.createElementNS(NS, "line");
            line.setAttribute("x1", `${a.x}`); line.setAttribute("y1", `${a.y}`);
            line.setAttribute("x2", `${b.x}`); line.setAttribute("y2", `${b.y}`);
            line.setAttribute("stroke", "var(--background-modifier-border)");
            line.setAttribute("stroke-width", "1.5");
            svg.appendChild(line);
            const lbl = document.createElementNS(NS, "text");
            lbl.setAttribute("x", `${(a.x + b.x) / 2}`); lbl.setAttribute("y", `${(a.y + b.y) / 2 - 3}`);
            lbl.setAttribute("font-size", "9"); lbl.setAttribute("text-anchor", "middle");
            lbl.setAttribute("fill", "var(--text-muted)");
            lbl.textContent = e.rel;
            svg.appendChild(lbl);
        }

        for (const n of data.nodes) {
            const p = pos[n.id]; if (!p) continue;
            const isCentre = n.id === this.node;
            const g = document.createElementNS(NS, "g");
            g.style.cursor = "pointer";
            const c = document.createElementNS(NS, "circle");
            c.setAttribute("cx", `${p.x}`); c.setAttribute("cy", `${p.y}`);
            c.setAttribute("r", isCentre ? "9" : "6");
            c.setAttribute("fill", isCentre ? "var(--interactive-accent)" : "var(--text-accent)");
            g.appendChild(c);
            const t = document.createElementNS(NS, "text");
            t.setAttribute("x", `${p.x + 11}`); t.setAttribute("y", `${p.y + 4}`);
            t.setAttribute("font-size", "11"); t.setAttribute("fill", "var(--text-normal)");
            t.textContent = n.id;
            g.appendChild(t);
            g.addEventListener("click", () => {
                if (isCentre && n.sources.length) {
                    this.app.workspace.openLinkText(n.sources[0], "", false);
                    this.close();
                } else {
                    this.node = n.id; this.inputEl.value = n.id; void this.load();   // recentre
                }
            });
            svg.appendChild(g);
        }
        this.svgWrap.appendChild(svg);
        const hint = this.svgWrap.createEl("div", {
            text: "Click a neighbour to recentre; click the centre node to open its source note.",
        });
        hint.style.fontSize = "11px"; hint.style.color = "var(--text-muted)"; hint.style.marginTop = "6px";
    }

    onClose(): void { this.contentEl.empty(); }
}

// 📎 attach — file types the paperclip handles.
const DOC_EXT = ["pdf", "epub", "docx", "txt", "md", "markdown"];
const IMG_EXT = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"];

// 📎 — pick a vault file to ingest (document) or analyse (image).
class AttachPickerModal extends FuzzySuggestModal<TFile> {
    private onPick: (file: TFile) => void;
    constructor(app: App, onPick: (file: TFile) => void) {
        super(app);
        this.onPick = onPick;
        this.setPlaceholder("Attach a document to ingest, or an image to analyse…");
    }
    getItems(): TFile[] {
        return this.app.vault.getFiles().filter(f => {
            const e = f.extension.toLowerCase();
            return DOC_EXT.includes(e) || IMG_EXT.includes(e);
        });
    }
    getItemText(f: TFile): string { return f.path; }
    onChooseItem(f: TFile): void { this.onPick(f); }
}

// M9 — markers for a staged (Vault-mode) edit proposal inside a note.
const PROPOSAL_BEGIN   = "<!-- AI-EDIT-PROPOSAL";
const PROPOSAL_END     = "AI-EDIT-PROPOSAL-END -->";
const PROPOSAL_HEADING = "## Assistant Proposed Edit";

// M9 — a captured editor selection queued as context for the next message.
interface PendingSelection {
    text:     string;
    from:     EditorPosition;
    to:       EditorPosition;
    scope:    "word" | "paragraph" | "section" | "whole-note";
    notePath?: string;      // the note the selection came from (stable target for apply)
}

export const CHAT_VIEW_TYPE = "ai-assistant-chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type ChatMode      = "normal" | "handoff-awaiting-response" | "edit-handoff-awaiting";

// M9 — an edit proposal (mirrors the server EditProposal; Live mode here).
interface EditProposal {
    id:            string;
    note_path:     string | null;
    scope:         string;
    intent:        string;
    original_text: string;
    replacement:   string;
    options?:      string[];
    offsets?:      { from: EditorPosition; to: EditorPosition } | null;
    anchor?:       { heading?: string | null; snippet?: string; occurrence?: number } | null;
    source:        string;
    status:        string;
    provider?:     string;
}
// M29 — a vault restructuring proposal (copy/move/trash/mkdir) awaiting user approval.
interface RestructureProposal {
    kind:     "restructure";
    op:       string;                 // copy | move | trash | mkdir
    command:  string;                 // exact `vault:` command run verbatim on approval
    summary:  string;                 // human-readable description of the change
    src?:     string | null;
    dst?:     string | null;
    id:       string;
}

// Provider keys are no longer a fixed union — the dropdown is populated from the
// service's /status endpoint, which is itself driven by Provider-Registry.md.
// "auto" means smart routing (no override).

interface HandoffResponse {
    status:               "ok" | "handoff_required" | "edit_handoff_required";
    reply:                string;
    provider_used:        string;
    actual_provider:      string;
    timestamp:            string;
    prompt_to_copy?:      string;
    vault_actions_taken?: string[];   // commands executed from web AI suggestions
    proposal?:            EditProposal | RestructureProposal;   // M9 edit / M29 restructure
    sources?:             string[];       // M11 — Vault QA source notes
    source_kinds?:        string[];       // M16 — "vector"|"graph" per source
}

interface StatusResponse {
    online:            boolean;
    providers:         Record<string, boolean>;
    active_provider:   string | null;
    provider_override: string | null;
    session_started:   string;
    message_count:     number;
}

interface HistoryMessage { role: string; content: string; }
interface HistoryResponse { messages: HistoryMessage[]; count: number; }

// M39 — running-goals panel
interface Goal {
    slug: string; description: string; status: string;
    done: number; total: number; recurring: string; template: string;
}

// M36 — unified Approvals inbox (organize + memory + goals)
interface ApprovalItem { itemkind: string; value: string; label: string; }
interface Approval {
    id: string;
    kind: string;          // "organize" | "memory" | "goal"
    note: string;          // openable vault path
    summary: string;
    detail: string;
    items: ApprovalItem[];
    whole_only: boolean;
}

// ---------------------------------------------------------------------------
// ChatView
// ---------------------------------------------------------------------------
export class ChatView extends ItemView {
    private plugin:       AIAssistantPlugin;
    private messagesEl!:  HTMLElement;
    private inputEl!:     HTMLTextAreaElement;
    private sendBtn!:     HTMLButtonElement;
    private statusEl!:    HTMLElement;
    private modeEl!:      HTMLElement;
    private providerEl!:  HTMLElement;

    private isLoading    = false;
    private chatMode:    ChatMode       = "normal";
    private selectedProvider            = "auto";
    // M9 — selected-region context queued for the next send (null = none).
    private pendingSelection: PendingSelection | null = null;
    private selectionBadgeEl!: HTMLElement;
    // M9 — edit intent + the region snapshot used to build a proposal on a webui edit return.
    private editMode = false;
    private shownProposalIds = new Set<string>();   // M9 — avoid re-showing a staged proposal
    private pendingEditContext: {
        offsets: { from: EditorPosition; to: EditorPosition };
        original_text: string;
        scope: string;
        note_path: string | null;
        intent: string;
    } | null = null;
    // Registry-driven list, refreshed from /status. Fallback used while offline.
    private availableProviders: string[] = ["auto", "groq", "google", "cerebras", "webui"];
    private pendingHandoffUserMessage   = "";
    private serviceOnline               = false;

    // Display names for known provider keys. Unknown keys (new registry rows) are
    // shown capitalised, so a new provider appears automatically with no code change.
    private static readonly PROVIDER_LABELS: Record<string, string> = {
        auto: "Auto (smart routing)",
        groq: "Groq",
        google: "Gemini",
        cerebras: "Cerebras",
        nvidia: "NVIDIA",
        openrouter: "OpenRouter",
        webui: "Web UI (handoff)",
    };
    // M10 — privacy routing. When private, the service routes only to providers
    // that do not train on data, and will not hand off to a web AI unless the
    // user opts in (allowWebuiOnPrivate).
    private isPrivate            = false;
    private allowWebuiOnPrivate  = false;
    // M11 — Vault QA mode: answer from the whole-vault RAG index (cited sources).
    private vaultQa              = false;
    private qaScope             = "";   // M12 — "folder/" or "#tag" to scope Vault QA
    // M12 — @-mentioned notes (paths) queued as context for the next message.
    private mentions: string[]  = [];
    private mentionsEl!: HTMLElement;
    private relatedEl!: HTMLElement;   // M12 — related-notes dropdown row
    private relatedPaths: string[] = []; // paths currently offered by the Related dropdown
    private qaScopeEl!: HTMLElement;   // Vault QA scope row (shown when Vault QA is on)
    private proactiveEl!: HTMLElement; // M36 — unified Approvals inbox + briefing
    private goalsEl!: HTMLElement;     // M39 — running-goals panel

    constructor(leaf: WorkspaceLeaf, plugin: AIAssistantPlugin) {
        super(leaf);
        this.plugin = plugin;
    }

    getViewType():    string { return CHAT_VIEW_TYPE; }
    getDisplayText(): string { return "Loremaster"; }
    getIcon():        string { return "bot"; }

    async onOpen(): Promise<void> {
        this.buildUI();
        await this.loadStatus();
        await this.loadHistory();
        void this.refreshProactive();          // M36 — unified Approvals inbox + today's briefing
        void this.refreshGoals();              // M39 — running goals panel
        // M9 — surface staged edit proposals; M12 — refresh related notes, on file open.
        this.registerEvent(this.app.workspace.on("file-open", (f) => {
            if (f) { void this.checkNoteForProposal(f); void this.refreshRelated(f); }
        }));
        const active = this.app.workspace.getActiveFile();
        if (active) { void this.checkNoteForProposal(active); void this.refreshRelated(active); }
        // BUG-005: focus input on open
        this.focusInput();
    }

    async onClose(): Promise<void> {}

    // ------------------------------------------------------------------
    // UI construction
    // ------------------------------------------------------------------
    private buildUI(): void {
        const container = this.containerEl.children[1] as HTMLElement;
        container.empty();
        container.addClass("ai-assistant-container");

        // Header line: title + Live badge on the left; Provider dropdown, Private
        // toggle, and the settings gear on the right (all on one row).
        const header = container.createDiv("ai-assistant-header");
        const headLeft = header.createDiv("ai-assistant-head-left");
        headLeft.createEl("span", { text: "Loremaster", cls: "ai-assistant-title" });
        this.modeEl = headLeft.createEl("span", { cls: "ai-assistant-mode" });

        const headRight = header.createDiv("ai-assistant-head-right");
        this.providerEl = headRight.createDiv("ai-assistant-provider-bar");
        this.buildProviderBar();   // provider select + Private toggle only
        const gear = headRight.createEl("button", { text: "⚙", cls: "ai-assistant-gear", attr: { "aria-label": "Settings" } });
        gear.addEventListener("click", () => this.openSettings());

        // M12 — related notes offered as a dropdown you can add to context (hidden until populated).
        this.relatedEl = container.createDiv("ai-assistant-related");
        this.updateRelated([]);

        // M36 — unified Approvals inbox (organize + memory + goals) + briefing (hidden until any).
        this.proactiveEl = container.createDiv("ai-assistant-proactive");
        this.proactiveEl.style.display = "none";

        // M39 — running goals with progress + pause/resume/cancel (hidden until any).
        this.goalsEl = container.createDiv("ai-assistant-proactive");
        this.goalsEl.style.display = "none";

        this.statusEl = container.createDiv("ai-assistant-status");
        this.statusEl.setText("Connecting...");

        this.messagesEl = container.createDiv("ai-assistant-messages");

        const inputArea = container.createDiv("ai-assistant-input-area");

        // M12 — @-mention chips (hidden until a note is attached).
        this.mentionsEl = inputArea.createDiv("ai-assistant-mentions");
        this.renderMentions();

        // M9 — selected-region context badge (hidden until a selection is attached).
        this.selectionBadgeEl = inputArea.createDiv("ai-assistant-selection-badge");
        this.renderSelectionBadge();

        // Vault QA scope row — only shown while Vault QA is on (toggled from Actions).
        this.qaScopeEl = inputArea.createDiv("ai-assistant-qa-scope-row");
        this.renderQaScope();

        this.inputEl    = inputArea.createEl("textarea", {
            attr: { rows: "3" },
            cls:  "ai-assistant-input",
        });
        this.updateInputPlaceholder();
        this.inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            } else if (e.key === "@") {
                // M12 — typing @ opens the note picker instead of inserting the char.
                e.preventDefault();
                this.openNotePicker();
            }
        });

        const btnRow    = inputArea.createDiv("ai-assistant-btn-row");
        this.sendBtn    = btnRow.createEl("button", { cls: "ai-assistant-send-btn" });
        this.updateSendButton();
        this.sendBtn.addEventListener("click", () => this.handleSend());

        // Actions ▾ — Vault QA toggle + quick actions (Summarize / Key points / … / Graph).
        const actionsBtn = btnRow.createEl("button", {
            text: "Actions ▾", cls: "ai-assistant-actions-btn",
            attr: { title: "Vault QA, summarize, edits, prompts, graph…" },
        });
        actionsBtn.addEventListener("click", (evt) => this.openActionsMenu(evt));

        // M12 — attach a named note as context (or type @ in the input).
        const noteBtn = btnRow.createEl("button", {
            text: "+ Note",
            cls:  "ai-assistant-selection-btn",
            attr: { title: "Add a note as context (or type @ in the message)" },
        });
        noteBtn.addEventListener("click", () => this.openNotePicker());

        // M9 — attach the current editor selection as context for the next message.
        const selBtn = btnRow.createEl("button", {
            text: "+ Selection",
            cls:  "ai-assistant-selection-btn",
            attr: { title: "Attach the text currently selected in your note as context" },
        });
        selBtn.addEventListener("click", () => this.captureSelection());

        // 📎 — attach a vault file: ingest a document, or analyse an image.
        const clipBtn = btnRow.createEl("button", {
            text: "📎",
            cls:  "ai-assistant-attach-btn",
            attr: { title: "Attach a file — ingest a PDF/EPUB/Word/text document, or analyse an image" },
        });
        clipBtn.addEventListener("click", () => this.openAttachPicker());

        const clearBtn = btnRow.createEl("button", { text: "Clear", cls: "ai-assistant-clear-btn" });
        clearBtn.addEventListener("click", () => this.clearMessages());

        const refreshBtn = btnRow.createEl("button", {
            text: "↻",
            cls:  "ai-assistant-refresh-btn",
            attr: { title: "Refresh status" },
        });
        refreshBtn.addEventListener("click", () => this.loadStatus());
    }

    /** Human label for a provider key. Composite keys ("groq:model") show "Groq · model". */
    private providerLabel(key: string): string {
        if (ChatView.PROVIDER_LABELS[key]) return ChatView.PROVIDER_LABELS[key];
        if (key.includes(":")) {
            const [p, model] = key.split(":");
            const base = (ChatView.PROVIDER_LABELS[p] ?? this.capitalise(p)).replace(/ \(.*\)$/, "");
            return `${base} · ${model}`;
        }
        return this.capitalise(key);
    }

    private capitalise(s: string): string {
        return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s;
    }

    /**
     * Provider selector (registry-driven) + privacy toggle.
     * The dropdown options come from `availableProviders`, which `loadStatus()`
     * refreshes from the service's /status endpoint (driven by Provider-Registry.md).
     * Adding a provider row therefore makes it appear here with no plugin edit.
     */
    private buildProviderBar(): void {
        this.providerEl.empty();

        const select = this.providerEl.createEl("select", {
            cls: "ai-assistant-provider-select", attr: { title: "Provider / model routing" },
        });
        for (const key of this.availableProviders) {
            const opt = select.createEl("option", { text: this.providerLabel(key), value: key });
            if (key === this.selectedProvider) opt.selected = true;
        }
        select.addEventListener("change", () => {
            this.selectedProvider = select.value;
            this.updateInputPlaceholder();
            this.focusInput();
        });

        // M10 — privacy toggle. Routes only to providers that don't train on data
        // (excludes Gemini) and blocks the web handoff unless the user opts in.
        const privBtn = this.providerEl.createEl("button", {
            text: this.isPrivate ? "🔒 Private" : "🔓 Private",
            cls:  `ai-assistant-provider-btn ai-assistant-private-btn${this.isPrivate ? " active" : ""}`,
            attr: {
                "data-private": String(this.isPrivate),
                title: "Private: route only to providers that do not train on your data " +
                       "(no Gemini); no web handoff unless you allow it.",
            },
        });
        privBtn.addEventListener("click", () => {
            this.isPrivate = !this.isPrivate;
            if (!this.isPrivate) this.allowWebuiOnPrivate = false;
            this.buildProviderBar();
            this.updateInputPlaceholder();
            this.focusInput();
        });
        // Vault QA + quick actions now live in the Actions ▾ menu on the Send line.
    }

    /** Vault QA scope row (folder/ or #tag) — visible only while Vault QA is on. */
    private renderQaScope(): void {
        if (!this.qaScopeEl) return;
        this.qaScopeEl.empty();
        if (!this.vaultQa) { this.qaScopeEl.style.display = "none"; return; }
        this.qaScopeEl.style.display = "flex";
        this.qaScopeEl.createEl("span", { text: "📚", cls: "ai-assistant-qa-scope-icon" });
        const inp = this.qaScopeEl.createEl("input", {
            cls: "ai-assistant-qa-scope",
            attr: { type: "text", placeholder: "Vault QA scope: folder/ or #tag (optional)", value: this.qaScope },
        });
        inp.addEventListener("change", () => { this.qaScope = inp.value.trim(); });
    }

    /** Actions ▾ menu on the Send line: Vault QA toggle + quick chat/edit actions. */
    private openActionsMenu(evt: MouseEvent): void {
        const menu = new Menu();
        menu.addItem((i) => i
            .setTitle(this.vaultQa ? "Vault QA: on" : "Vault QA")
            .setChecked(this.vaultQa)
            .onClick(() => {
                this.vaultQa = !this.vaultQa;
                this.renderQaScope();
                this.updateInputPlaceholder();
                this.focusInput();
            }));
        menu.addSeparator();
        menu.addItem((i) => i.setTitle("Summarize").onClick(() =>
            void this.runQuickChat("Summarize the active note concisely.")));
        menu.addItem((i) => i.setTitle("Key points").onClick(() =>
            void this.runQuickChat("List the key points of the active note as bullets.")));
        menu.addItem((i) => i.setTitle("Action items").onClick(() =>
            void this.runQuickChat("List the action items and open questions in the active note as a checklist.")));
        menu.addSeparator();
        menu.addItem((i) => i.setTitle("Fix grammar").onClick(() =>
            void this.runQuickEdit("Fix grammar and spelling, preserving meaning.")));
        menu.addItem((i) => i.setTitle("Improve").onClick(() =>
            void this.runQuickEdit("Improve clarity and flow, preserving meaning.")));
        menu.addSeparator();
        menu.addItem((i) => i.setTitle("Prompts…").onClick(() => this.openPromptPicker()));
        menu.addItem((i) => i.setTitle("Graph").onClick(() => this.openGraphViewer()));
        menu.showAtMouseEvent(evt);
    }

    /** Refresh the dropdown options from the service's live provider map. */
    private updateAvailableProviders(providers: Record<string, boolean>): void {
        const built    = Object.keys(providers).filter(k => providers[k]);
        const nonWebui = built.filter(k => k !== "webui");
        // Auto first, then every built provider in service order, Web UI last.
        this.availableProviders = ["auto", ...nonWebui, ...(built.indexOf("webui") !== -1 ? ["webui"] : [])];
        // If the pinned provider vanished (e.g. went unhealthy / key removed), fall back to Auto.
        if (this.selectedProvider !== "auto" && this.availableProviders.indexOf(this.selectedProvider) === -1) {
            this.selectedProvider = "auto";
        }
        this.buildProviderBar();
    }

    // ------------------------------------------------------------------
    // Status and history loading
    // ------------------------------------------------------------------
    /** Headers for service requests, adding the LAN API token when one is set. */
    private apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
        const t = this.plugin.settings.apiToken?.trim();
        return t ? { ...extra, "X-API-Key": t } : extra;
    }

    private async loadStatus(): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/status`, {
                signal: AbortSignal.timeout(3000),
                headers: this.apiHeaders(),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data: StatusResponse = await resp.json();
            const provider = data.active_provider ?? "none";
            this.statusEl.setText(`✓ Connected — ${provider.toUpperCase()} — ${data.message_count} messages`);
            this.statusEl.className = "ai-assistant-status ai-assistant-status-online";
            this.serviceOnline      = true;
            // Registry-driven: rebuild the provider dropdown from the live service list.
            if (data.providers) this.updateAvailableProviders(data.providers);
            this.setConnectMode("http");
        } catch {
            this.statusEl.setText("⚡ Service offline — vault mode active");
            this.statusEl.className = "ai-assistant-status ai-assistant-status-offline";
            this.serviceOnline      = false;
            this.setConnectMode("vault");
        }
    }

    private async loadHistory(): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/history`, {
                signal: AbortSignal.timeout(3000),
                headers: this.apiHeaders(),
            });
            if (!resp.ok) return;
            const data: HistoryResponse = await resp.json();
            if (data.messages.length === 0) return;

            const histDiv = this.messagesEl.createDiv("ai-assistant-history-header");
            histDiv.setText(`— ${data.messages.length} messages from this session —`);

            for (const msg of data.messages) {
                if (msg.content.startsWith("[") && msg.content.endsWith("]")) continue;
                await this.appendMessage(msg.role as "user" | "assistant", msg.content, true);
            }
            this.scrollToBottom();
        } catch {
            // Service offline — fine
        }
    }

    // ------------------------------------------------------------------
    // Send
    // ------------------------------------------------------------------
    private async handleSend(): Promise<void> {
        if (this.isLoading) return;
        const text = this.inputEl.value.trim();
        if (!text) return;

        // Local slash commands (/settings, /help) — handled in the plugin, never sent to the AI.
        if (text.startsWith("/") && await this.handleSlashCommand(text)) {
            this.inputEl.value = "";
            return;
        }

        this.inputEl.value = "";
        this.setLoading(true);

        if (this.chatMode === "edit-handoff-awaiting") {
            await this.submitEditHandoffReturn(text);
        } else if (this.chatMode === "handoff-awaiting-response") {
            await this.submitHandoffReturn(text);
        } else {
            // normal mode — edit intent via the toggle or an `/edit ` prefix
            const hasEditPrefix = text.toLowerCase().startsWith("/edit ");
            const editFlag = this.editMode || hasEditPrefix;
            const message  = hasEditPrefix ? text.slice(6).trim() : text;

            if (editFlag) {
                if (!this.serviceOnline) {
                    new Notice("Editing needs the live service — vault-mode editing comes later.");
                } else if (!this.pendingSelection) {
                    new Notice("Attach a selection (+ Selection) before proposing an edit.");
                } else {
                    await this.appendMessage("user", `✎ ${message}`);
                    await this.sendViaHTTP(message, false, true);
                    // Keep the selection until the proposal is resolved (Replace / Keep editing).
                }
            } else {
                await this.appendMessage("user", text);
                if (this.serviceOnline) {
                    await this.sendViaHTTP(text);
                } else {
                    await this.sendViaVault(text);
                }
                // M9/M12 — selection + mentions are one-shot context; detach them.
                this.clearSelection();
                this.clearMentions();
            }
        }

        this.setLoading(false);
        // BUG-005: restore focus after every send cycle completes
        this.focusInput();
    }

    /** Local slash commands handled by the plugin (not sent to the AI).
     *  Returns true if the command was handled. Unknown slashes (e.g. /edit) pass through. */
    private async handleSlashCommand(text: string): Promise<boolean> {
        const sp = text.indexOf(" ");
        const cmd = (sp === -1 ? text : text.slice(0, sp)).toLowerCase();
        const arg = (sp === -1 ? "" : text.slice(sp + 1)).trim();
        const GUIDE = "AI/System/User-Guide.md";

        if (cmd === "/settings" || cmd === "/config") {
            const setting = (this.app as any).setting;
            if (setting) { setting.open(); setting.openTabById?.("ai-assistant"); }
            new Notice("Control panel: Settings → Loremaster → 'Service settings (control panel)' → Load.");
            return true;
        }
        if (cmd === "/help") {
            if (!arg) {
                this.app.workspace.openLinkText(GUIDE, "", true);   // open the User Guide note
                new Notice("Opened the User Guide. Tip: type '/help <question>' to ask using it as context.");
                return true;
            }
            // /help <question> → answer it with the User Guide injected as context
            this.setLoading(true);
            this.mentions = [GUIDE];
            await this.appendMessage("user", `/help ${arg}`);
            if (this.serviceOnline) await this.sendViaHTTP(arg); else await this.sendViaVault(arg);
            this.clearMentions();
            this.setLoading(false);
            this.focusInput();
            return true;
        }
        return false;   // /edit and anything else flows through normally
    }

    // ------------------------------------------------------------------
    // HTTP send
    // ------------------------------------------------------------------
    private async sendViaHTTP(text: string, forceAllowWebui = false, edit = false): Promise<void> {
        const { host, port } = this.plugin.settings;
        const activePath = this.app.workspace.getActiveFile()?.path ?? null;

        // M9 — snapshot the region so a webui edit-handoff return can build the proposal.
        if (edit && this.pendingSelection) {
            this.pendingEditContext = {
                offsets:       { from: this.pendingSelection.from, to: this.pendingSelection.to },
                original_text: this.pendingSelection.text,
                scope:         this.pendingSelection.scope,
                note_path:     activePath,
                intent:        text,
            };
        }

        try {
            const resp = await fetch(`http://${host}:${port}/chat`, {
                method:  "POST",
                headers: this.apiHeaders({ "Content-Type": "application/json" }),
                body:    JSON.stringify({
                    message:           text,
                    provider_override: this.selectedProvider === "auto" ? null : this.selectedProvider,
                    private:                 this.isPrivate,
                    allow_webui_on_private:  this.isPrivate && (this.allowWebuiOnPrivate || forceAllowWebui),
                    // M9 — active-note + selected-region context, and edit intent.
                    active_note_path:  activePath,
                    selection:         this.pendingSelection,
                    scope:             this.pendingSelection?.scope ?? null,
                    edit,
                    vault_qa:          this.vaultQa,
                    mentions:          this.mentions,
                    scope_folder:      (this.vaultQa && this.qaScope && !this.qaScope.startsWith("#")) ? this.qaScope : null,
                    scope_tag:         (this.vaultQa && this.qaScope.startsWith("#")) ? this.qaScope.slice(1) : null,
                }),
                signal: AbortSignal.timeout(60000),
            });

            if (!resp.ok) {
                const err    = await resp.json().catch(() => ({ detail: "Unknown error" }));
                const detail = (err.detail ?? `HTTP ${resp.status}`) as string;
                // M10 — private request exhausted all no-train providers. Offer the
                // web-AI handoff as an explicit choice rather than just erroring.
                if (resp.status === 503 && this.isPrivate && !forceAllowWebui
                        && /allow_webui_on_private/i.test(detail)) {
                    this.appendPrivateHandoffChoice(text);
                    return;
                }
                throw new Error(detail);
            }

            const data: HandoffResponse = await resp.json();

            // M9 — an edit proposal, or a request to fetch the edit from a web AI.
            if (data.status === "edit_handoff_required" && data.prompt_to_copy) {
                this.enterEditHandoffMode(data.prompt_to_copy);
                return;
            }
            if (data.proposal) {
                this.pendingEditContext = null;
                // M29 — a vault restructuring proposal (copy/move/trash/mkdir).
                if ((data.proposal as RestructureProposal).kind === "restructure") {
                    if (data.reply) await this.appendMessage("assistant", data.reply);
                    this.renderRestructureProposal(data.proposal as RestructureProposal);
                    return;
                }
                const edit = data.proposal as EditProposal;
                // Remember which note this Live proposal targets, so Replace can find the
                // pane by path even after the region drifts (T9.07) or the sidebar steals focus.
                if (!edit.note_path) {
                    edit.note_path = this.pendingSelection?.notePath
                        ?? this.app.workspace.getActiveFile()?.path ?? null;
                }
                void this.renderEditProposal(edit);
                return;
            }

            if (data.status === "handoff_required" && data.prompt_to_copy) {
                this.enterHandoffMode(text, data.prompt_to_copy);
                return;
            }

            await this.appendMessage("assistant", data.reply);
            if (data.sources && data.sources.length) this.renderSources(data.sources, data.source_kinds);
            const provider = data.actual_provider ?? data.provider_used;
            this.statusEl.setText(`✓ ${provider.toUpperCase()} — ${data.timestamp}`);

        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("timeout")) {
                this.setConnectMode("vault");
                this.serviceOnline = false;
                await this.loadStatus();
                await this.sendViaVault(text);
            } else {
                await this.appendErrorMessage(`Error: ${msg}`);
            }
        }
    }

    // ------------------------------------------------------------------
    // Vault-file send
    // ------------------------------------------------------------------
    private async sendViaVault(text: string): Promise<void> {
        const vault   = this.app.vault;
        const { handshakeDir } = this.plugin.settings;
        const ts      = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const notePath = `${handshakeDir}/chat-${ts}.md`;

        // M9 — carry the selected region into the watcher path as quoted context.
        const sel = this.pendingSelection;
        const selectionBlock = sel
            ? `\n[Selected text — ${sel.scope}]\n> ${sel.text.replace(/\n/g, "\n> ")}\n`
            : "";
        const activePath = this.app.workspace.getActiveFile()?.path;

        const noteContent = [
            "---",
            `assistant-status: pending`,
            `assistant-request: "${text.replace(/"/g, '\\"')}"`,
            // M10 — carry the privacy flags into the watcher path.
            ...(this.isPrivate ? [`private: true`] : []),
            ...(this.isPrivate && this.allowWebuiOnPrivate ? [`allow-webui: true`] : []),
            // M9 — record which note was active when the message was sent.
            ...(activePath ? [`active-note: "${activePath.replace(/"/g, '\\"')}"`] : []),
            "---",
            "",
            `**Sent:** ${new Date().toLocaleString()}`,
            selectionBlock,
            text,
        ].join("\n");

        try {
            if (!vault.getFolderByPath(handshakeDir)) {
                await vault.createFolder(handshakeDir);
            }
            await vault.create(notePath, noteContent);
            const waitMsg = await this.appendWaitingMessage();
            this.pollVaultResponse(notePath, waitMsg);
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            await this.appendErrorMessage(`Vault error: ${msg}`);
        }
    }

    private pollVaultResponse(notePath: string, waitMsg: HTMLElement): void {
        const MAX_MS   = 5 * 60 * 1000;
        const INTERVAL = 3000;
        const start    = Date.now();

        const poll = async () => {
            if (Date.now() - start > MAX_MS) {
                waitMsg.remove();
                await this.appendErrorMessage("No response after 5 minutes. Is the watcher running?");
                this.focusInput();    // BUG-005
                return;
            }

            const file = this.app.vault.getFileByPath(notePath);
            if (!file) { setTimeout(poll, INTERVAL); return; }

            const content = await this.app.vault.read(file);

            if (
                content.includes('assistant-status: "done"') ||
                content.includes("assistant-status: done") ||
                content.includes("## Assistant Response")
            ) {
                const match = content.match(
                    /## Assistant Response\s*\n+(?:\*\*Generated:\*\*[^\n]*\n+)?([\s\S]+?)(?:---|$)/
                );
                const reply = match ? match[1].trim() : "Response received (see vault note).";
                waitMsg.remove();
                await this.appendMessage("assistant", reply);
                this.focusInput();    // BUG-005
                return;
            }

            if (
                content.includes('assistant-status: "error"') ||
                content.includes("assistant-status: error")
            ) {
                waitMsg.remove();
                await this.appendErrorMessage("Watcher returned an error. Check the vault note.");
                this.focusInput();    // BUG-005
                return;
            }

            if (
                content.includes('assistant-status: "handoff-pending"') ||
                content.includes("assistant-status: handoff-pending")
            ) {
                waitMsg.remove();
                await this.appendErrorMessage(
                    "API providers exhausted. Open the vault note, paste the web AI response " +
                    "under '## User Web Handoff Return', then set assistant-status back to pending."
                );
                this.focusInput();    // BUG-005
                return;
            }

            setTimeout(poll, INTERVAL);
        };

        setTimeout(poll, INTERVAL);
    }

    // ------------------------------------------------------------------
    // Handoff mode
    // ------------------------------------------------------------------
    private enterHandoffMode(userMessage: string, promptToCopy: string): void {
        this.chatMode                   = "handoff-awaiting-response";
        this.pendingHandoffUserMessage  = userMessage;
        this.updateSendButton();
        this.updateInputPlaceholder();
        this.containerEl.setAttribute("data-chat-mode", "handoff-awaiting-response");

        const handoffEl = this.messagesEl.createDiv("ai-assistant-message ai-assistant-handoff");
        handoffEl.createEl("span", { text: "Web Handoff", cls: "ai-assistant-label" });

        const body = handoffEl.createDiv("ai-assistant-body");
        body.createEl("p", {
            text: "All API providers are unavailable. Copy the prompt below and paste it into any web AI (ChatGPT, Claude, Gemini, DeepSeek), then paste the response in the input box.",
        });

        const controls = body.createDiv("ai-assistant-handoff-controls");
        const copyBtn = controls.createEl("button", { text: "📋 Copy Prompt", cls: "ai-assistant-copy-btn" });
        copyBtn.addEventListener("click", async () => {
            await navigator.clipboard.writeText(promptToCopy);
            copyBtn.setText("✓ Copied!");
            setTimeout(() => copyBtn.setText("📋 Copy Prompt"), 2000);
            // BUG-005: return focus after clicking copy
            this.focusInput();
        });
        // Cancel — dismiss the handoff and go back to normal (no paste required).
        const cancelBtn = controls.createEl("button", { text: "Cancel", cls: "ai-assistant-proposal-cancel" });
        cancelBtn.addEventListener("click", () => {
            handoffEl.remove();
            this.chatMode = "normal";
            this.pendingHandoffUserMessage = "";
            this.containerEl.setAttribute("data-chat-mode", "normal");
            this.updateSendButton();
            this.updateInputPlaceholder();
            this.focusInput();
        });

        // Show the FULL prompt (scrollable) so the Question and every section are visible —
        // and match exactly what "Copy Prompt" puts on the clipboard.
        const preview = body.createEl("pre", { cls: "ai-assistant-handoff-preview" });
        preview.setText(promptToCopy);

        this.scrollToBottom();
        // BUG-005: move focus to input so user can immediately paste
        this.focusInput();
    }

    private async submitHandoffReturn(pastedText: string): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/chat/handoff-return`, {
                method: "POST",
                headers: this.apiHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({
                    response_text: pastedText,
                    original_message: this.pendingHandoffUserMessage || undefined,
                }),
                signal: AbortSignal.timeout(10000),
            });

            if (!resp.ok) {
                let detail = `HTTP ${resp.status}`;
                try {
                    const errData = await resp.json();
                    if (errData?.detail) detail = errData.detail;
                } catch {
                    // ignore JSON parse failure for error body
                }
                throw new Error(detail);
            }

            const data: HandoffResponse = await resp.json();

            // Render first, then reset mode
            await this.appendMessage("assistant", data.reply);

            if (data.vault_actions_taken && data.vault_actions_taken.length > 0) {
                const actionsEl = this.messagesEl.createDiv("ai-assistant-vault-actions");
                actionsEl.createEl("span", {
                    text: `⚡ Auto-executed: ${data.vault_actions_taken.join(", ")}`,
                    cls: "ai-assistant-vault-action-notice",
                });
            }

            this.chatMode = "normal";
            this.pendingHandoffUserMessage = "";
            this.containerEl.setAttribute("data-chat-mode", "normal");
            this.updateSendButton();
            this.updateInputPlaceholder();
            this.statusEl.setText("✓ Web handoff complete — vault searches executed automatically");

        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            await this.appendErrorMessage(`Handoff return failed: ${msg}`);
        }
    }

    // ------------------------------------------------------------------
    // Message rendering
    // ------------------------------------------------------------------
    private async appendMessage(
        role:      "user" | "assistant",
        content:   string,
        isHistory = false,
    ): Promise<HTMLElement> {
        const msgEl = this.messagesEl.createDiv(
            `ai-assistant-message ai-assistant-${role}${isHistory ? " ai-assistant-history" : ""}`
        );
        msgEl.createEl("span", {
            text: role === "user" ? "You" : "Assistant",
            cls:  "ai-assistant-label",
        });
        const bodyEl = msgEl.createDiv("ai-assistant-body");

        if (role === "assistant") {
            // Render markdown the way Obsidian shows it (headings, bold, lists, code).
            try {
                await MarkdownRenderer.render(this.app, content, bodyEl, "", this);
            } catch {
                bodyEl.setText(content);   // never leave an empty bubble
            }
        } else {
            bodyEl.setText(content);       // user text shown as typed
        }

        this.scrollToBottom();
        // BUG-005: re-focus input after every message render
        if (!isHistory) {
            this.focusInput();
        }
        return msgEl;
    }

    /** M11 — Vault QA source notes as clickable chips. M16 — a · graph marker
     *  flags sources surfaced via the link/tag graph rather than vector similarity. */
    private renderSources(sources: string[], kinds?: string[]): void {
        const el = this.messagesEl.createDiv("ai-assistant-sources");
        el.createEl("span", { text: "Sources:", cls: "ai-assistant-sources-label" });
        sources.forEach((s, i) => {
            const isGraph = kinds && kinds[i] === "graph";
            const chip = el.createEl("button", {
                text: isGraph ? `${s} · graph` : s,
                cls: "ai-assistant-source-chip" + (isGraph ? " ai-assistant-source-graph" : ""),
                attr: isGraph ? { title: "Surfaced via a [[link]] or shared #tag" } : {},
            });
            chip.addEventListener("click", () => { this.app.workspace.openLinkText(s, "", false); });
        });
        this.scrollToBottom();
    }

    private async appendErrorMessage(text: string): Promise<void> {
        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-error");
        el.createEl("span", { text: "⚠ Error", cls: "ai-assistant-label" });
        el.createDiv("ai-assistant-body").setText(text);
        this.scrollToBottom();
    }

    private async appendWaitingMessage(): Promise<HTMLElement> {
        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-waiting");
        el.createEl("span", { text: "Assistant", cls: "ai-assistant-label" });
        const body = el.createDiv("ai-assistant-body");
        body.createEl("span", { text: "Waiting for vault watcher" });
        body.createEl("span", { cls: "ai-assistant-dots", text: "..." });
        this.scrollToBottom();
        return el;
    }

    /** M10 — a private turn exhausted all no-train providers. Offer the web handoff as a choice. */
    private appendPrivateHandoffChoice(text: string): void {
        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-error");
        el.createEl("span", { text: "🔒 Private — providers unavailable", cls: "ai-assistant-label" });
        const body = el.createDiv("ai-assistant-body");
        body.createEl("p", {
            text: "All privacy-safe providers (those that do not train on your data) are unavailable. " +
                  "You can send this to a web AI instead, but that would expose the content to an external service.",
        });
        const btn = body.createEl("button", { text: "Send via Web AI anyway", cls: "ai-assistant-copy-btn" });
        btn.addEventListener("click", async () => {
            btn.disabled = true;
            this.setLoading(true);
            await this.sendViaHTTP(text, true);   // one-shot opt-in
            this.setLoading(false);
            this.focusInput();
        });
        this.scrollToBottom();
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    // ------------------------------------------------------------------
    // M9 — selection context
    // ------------------------------------------------------------------

    /** Capture the text currently selected in the active note as context for the next send. */
    private captureSelection(): void {
        // Clicking this sidebar button makes the sidebar the "active" editor, so
        // activeEditor no longer points at the note. CodeMirror keeps the note's
        // selection though, so scan the open markdown panes for a live selection.
        let editor: Editor | undefined = this.app.workspace.activeEditor?.editor;
        let notePath: string | undefined = this.app.workspace.activeEditor?.file?.path;
        let text = editor?.getSelection() ?? "";
        if (!text.trim()) {
            for (const leaf of this.app.workspace.getLeavesOfType("markdown")) {
                const view = leaf.view as MarkdownView;
                const sel = view?.editor?.getSelection?.() ?? "";
                if (sel.trim()) { editor = view.editor; text = sel; notePath = view.file?.path; break; }
            }
        }
        if (!editor || !text.trim()) {
            new Notice("Select some text in a note first, then click + Selection.");
            return;
        }
        this.pendingSelection = {
            text,
            from:  editor.getCursor("from"),
            to:    editor.getCursor("to"),
            scope: this.inferScope(text),
            notePath,
        };
        this.renderSelectionBadge();
        this.focusInput();
    }

    private clearSelection(): void {
        this.pendingSelection = null;
        this.editMode = false;          // no selection → no edit intent
        this.renderSelectionBadge();
        this.updateInputPlaceholder();
    }

    private renderSelectionBadge(): void {
        if (!this.selectionBadgeEl) return;
        this.selectionBadgeEl.empty();
        if (!this.pendingSelection) {
            this.selectionBadgeEl.style.display = "none";
            return;
        }
        this.selectionBadgeEl.style.display = "flex";
        const { text, scope } = this.pendingSelection;
        this.selectionBadgeEl.createEl("span", {
            text: `📎 ${text.length} chars (${scope})`,
            cls:  "ai-assistant-selection-badge-text",
        });

        // M9 — "Propose edit" toggle (only meaningful with a selection attached).
        const editToggle = this.selectionBadgeEl.createEl("button", {
            text: this.editMode ? "✎ Edit: on" : "✎ Edit: off",
            cls:  `ai-assistant-edit-toggle${this.editMode ? " active" : ""}`,
            attr: { title: "When on, your message proposes an edit to the selected region" },
        });
        editToggle.addEventListener("click", () => {
            this.editMode = !this.editMode;
            this.renderSelectionBadge();
            this.updateInputPlaceholder();
            this.focusInput();
        });

        const x = this.selectionBadgeEl.createEl("button", {
            text: "✕",
            cls:  "ai-assistant-selection-badge-clear",
            attr: { title: "Detach selection" },
        });
        x.addEventListener("click", () => this.clearSelection());
    }

    // ------------------------------------------------------------------
    // M12 — @-note mentions
    // ------------------------------------------------------------------

    private openNotePicker(): void {
        new NotePickerModal(this.app, (file) => this.addMention(file.path)).open();
    }

    // 📎 — attach a vault file: ingest a document, or analyse an image.
    private openAttachPicker(): void {
        if (!this.serviceOnline) {
            new Notice("Attaching files needs the live service (Live mode).");
            return;
        }
        new AttachPickerModal(this.app, (file) => {
            const ext = file.extension.toLowerCase();
            if (IMG_EXT.includes(ext))      void this.runQuickChat(`vault:analyze ${file.path}`);
            else if (DOC_EXT.includes(ext)) void this.runQuickChat(`vault:ingest ${file.path}`);
            else new Notice("Unsupported file type.");
        }).open();
    }

    // ------------------------------------------------------------------
    // M13 — quick actions + saved prompts
    // ------------------------------------------------------------------

    private async runQuickChat(message: string): Promise<void> {
        if (this.isLoading) return;
        this.setLoading(true);
        await this.appendMessage("user", message);
        if (this.serviceOnline) await this.sendViaHTTP(message);
        else                    await this.sendViaVault(message);
        this.clearSelection();
        this.clearMentions();
        this.setLoading(false);
        this.focusInput();
    }

    private async runQuickEdit(instruction: string): Promise<void> {
        if (this.isLoading) return;
        this.captureSelection();                       // shows a notice if nothing is selected
        if (!this.pendingSelection) return;
        if (!this.serviceOnline) { new Notice("Editing needs the live service."); return; }
        this.setLoading(true);
        await this.appendMessage("user", `✎ ${instruction}`);
        await this.sendViaHTTP(instruction, false, true);
        this.setLoading(false);
        this.focusInput();
    }

    private openPromptPicker(): void {
        new PromptPickerModal(this.app, (file) => void this.runPrompt(file)).open();
    }

    // Open this plugin's settings tab from the sidebar (gear icon).
    private openSettings(): void {
        const setting = (this.app as unknown as { setting?: { open(): void; openTabById(id: string): void } }).setting;
        if (setting) {
            setting.open();
            setting.openTabById(this.plugin.manifest.id);
        } else {
            new Notice("Open Settings → Loremaster.");
        }
    }

    // M18 — open the knowledge-graph viewer, seeded with the active note's name.
    private openGraphViewer(): void {
        const { host, port, apiToken } = this.plugin.settings;
        const start = this.app.workspace.getActiveFile()?.basename ?? "";
        new GraphViewerModal(this.app, host, port, apiToken ?? "", start).open();
    }

    private async runPrompt(file: TFile): Promise<void> {
        let body: string;
        try { body = await this.app.vault.read(file); } catch { return; }
        body = body.replace(/^---[\s\S]*?---\s*/, "");   // strip frontmatter
        const sel  = this.app.workspace.activeEditor?.editor?.getSelection() ?? "";
        const note = this.app.workspace.getActiveFile()?.basename ?? "";
        const msg  = body
            .replace(/\{\{selection\}\}/g, sel)
            .replace(/\{\{note\}\}/g, note)
            .replace(/\{\{input\}\}/g, "")
            .trim();
        if (!msg) { new Notice("That prompt produced no text."); return; }
        await this.runQuickChat(msg);
    }

    /** Command-palette entry points (called from main.ts). */
    public commandSummarize(): void { void this.runQuickChat("Summarize the active note concisely."); }
    public commandPrompts(): void { this.openPromptPicker(); }

    /** M40 — web clipper: save a URL as a sourced, indexed note. */
    public commandClip(url: string): void {
        if (!/^https?:\/\//i.test(url.trim())) { new Notice("Enter a valid http(s) URL."); return; }
        void this.runQuickChat("vault:clip " + url.trim());
    }

    /** M40 — inline authoring: continue writing at the cursor (private routing — the note
     *  text is only sent to no-train/local providers, never the web). */
    public async commandContinue(editor: Editor): Promise<void> {
        const cursor = editor.getCursor();
        const before = editor.getRange({ line: Math.max(0, cursor.line - 40), ch: 0 }, cursor);
        if (!before.trim()) { new Notice("Nothing to continue from."); return; }
        const { host, port } = this.plugin.settings;
        new Notice("Loremaster is writing…");
        try {
            const resp = await fetch(`http://${host}:${port}/chat`, {
                method: "POST",
                headers: this.apiHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({
                    message: "Continue the following text naturally in the same voice. Output ONLY the "
                        + "continuation — no preamble, no repetition of the given text:\n\n" + before,
                    private: true,
                }),
                signal: AbortSignal.timeout(30000),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const cont = ((await resp.json() as { reply?: string }).reply || "").trim();
            if (!cont) { new Notice("No continuation returned."); return; }
            const sep = /\s$/.test(before) ? "" : " ";
            editor.replaceSelection(sep + cont);
        } catch (e) {
            new Notice(`Continue failed: ${e instanceof Error ? e.message : e}`);
        }
    }

    /** M12 — fetch + show notes related to the active note. */
    private async refreshRelated(file: TFile): Promise<void> {
        if (!this.relatedEl || !file || file.extension !== "md" || !this.serviceOnline) {
            this.updateRelated([]);
            return;
        }
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/relevant?path=${encodeURIComponent(file.path)}&k=5`, {
                signal: AbortSignal.timeout(4000),
                headers: this.apiHeaders(),
            });
            if (!resp.ok) { this.updateRelated([]); return; }
            const data = await resp.json();
            this.updateRelated((data.notes ?? []).map((n: { path: string }) => n.path));
        } catch {
            this.updateRelated([]);
        }
    }

    private updateRelated(paths: string[]): void {
        this.relatedPaths = paths;
        if (!this.relatedEl) return;
        this.relatedEl.empty();
        if (paths.length === 0) { this.relatedEl.style.display = "none"; return; }
        this.relatedEl.style.display = "flex";
        this.relatedEl.createEl("span", { text: "Add context:", cls: "ai-assistant-related-label" });
        const btn = this.relatedEl.createEl("button", {
            text: `Related notes (${paths.length}) ▾`,
            cls:  "ai-assistant-related-dropdown",
            attr: { title: "Pick related notes to add to this conversation's context" },
        });
        btn.addEventListener("click", (evt) => this.openRelatedMenu(evt));
    }

    /** Dropdown of related notes; clicking one toggles it in/out of context (@mentions).
     *  Reopen to add more — each pick is added to context. */
    private openRelatedMenu(evt: MouseEvent): void {
        const menu = new Menu();
        for (const p of this.relatedPaths) {
            const name  = p.split("/").pop()?.replace(/\.md$/, "") ?? p;
            const added = this.mentions.indexOf(p) !== -1;
            menu.addItem((item) => item
                .setTitle(name)
                .setChecked(added)
                .onClick(() => { if (added) this.removeMention(p); else this.addMention(p); }));
        }
        menu.showAtMouseEvent(evt);
    }

    // ------------------------------------------------------------------
    // M17 — Memory review (nightly consolidation proposals)
    // ------------------------------------------------------------------
    // ------------------------------------------------------------------
    // M36 — unified Approvals inbox: organize + memory + goals, + today's briefing
    // ------------------------------------------------------------------
    private async refreshProactive(): Promise<void> {
        if (!this.proactiveEl) return;
        const { host, port } = this.plugin.settings;
        try {
            // briefing lives on /proactive; the unified approvals list on /approvals
            const [pr, ap] = await Promise.all([
                fetch(`http://${host}:${port}/proactive`, { signal: AbortSignal.timeout(3000), headers: this.apiHeaders() }),
                fetch(`http://${host}:${port}/approvals`, { signal: AbortSignal.timeout(3000), headers: this.apiHeaders() }),
            ]);
            if (!pr.ok || !ap.ok) throw new Error(`HTTP ${pr.status}/${ap.status}`);
            const briefing = (await pr.json() as { briefing: { path: string; exists: boolean } }).briefing;
            const approvals = (await ap.json() as { approvals: Approval[] }).approvals ?? [];
            this.renderProactive(briefing, approvals);
        } catch {
            this.proactiveEl.style.display = "none";
        }
    }

    private renderProactive(briefing: { path: string; exists: boolean }, approvals: Approval[]): void {
        this.proactiveEl.empty();
        if (!briefing.exists && approvals.length === 0) {
            this.proactiveEl.style.display = "none";
            return;
        }
        this.proactiveEl.style.display = "block";
        const title = approvals.length
            ? `🗂️ Approvals — ${approvals.length} pending`
            : "🗞️ Proactive";
        this.proactiveEl.createEl("div", { text: title, cls: "ai-assistant-memory-title" });

        if (briefing.exists) {
            const row = this.proactiveEl.createDiv("ai-assistant-proactive-briefing");
            const open = row.createEl("button", { text: "Open today's briefing", cls: "ai-assistant-quick-btn" });
            open.addEventListener("click", () => void this.app.workspace.openLinkText(briefing.path, "", false));
        }

        const kindIcon: Record<string, string> = { organize: "🏷️", memory: "🧠", goal: "🎯" };
        for (const a of approvals) {
            const box = this.proactiveEl.createDiv("ai-assistant-proactive-item");
            const head = box.createDiv("ai-assistant-proactive-head");
            head.createEl("span", {
                text: `${kindIcon[a.kind] ?? "•"} ${a.summary}`,
                cls: "ai-assistant-proactive-note",
            });
            const openBtn = head.createEl("button", { text: "Open note", cls: "ai-assistant-quick-btn" });
            openBtn.addEventListener("click", () => void this.app.workspace.openLinkText(a.note, "", false));

            if (a.whole_only) {
                // goals: show the steps read-only, approve/reject the whole thing
                for (const it of a.items) box.createEl("div", { text: "• " + it.label, cls: "ai-assistant-proactive-chiplabel" });
            } else {
                for (const it of a.items) this.approvalChip(box, a.id, it);
            }

            const btns = box.createDiv("ai-assistant-memory-btns");
            const applyLbl = a.kind === "goal" ? "Approve" : "Apply all";
            const rejectLbl = a.kind === "goal" ? "Reject" : "Dismiss all";
            btns.createEl("button", { text: applyLbl, cls: "ai-assistant-quick-btn" })
                .addEventListener("click", () => void this.resolveApproval("apply", a.id));
            btns.createEl("button", { text: rejectLbl, cls: "ai-assistant-quick-btn" })
                .addEventListener("click", () => void this.resolveApproval("reject", a.id));
        }
    }

    private approvalChip(box: HTMLElement, id: string, item: ApprovalItem): void {
        const chip = box.createDiv("ai-assistant-proactive-chip");
        chip.createEl("span", { text: item.label, cls: "ai-assistant-proactive-chiplabel" });
        const ok = chip.createEl("button", { text: "✓", cls: "ai-assistant-quick-btn" });
        ok.setAttribute("aria-label", "Apply");
        ok.addEventListener("click", () => void this.resolveApproval("apply", id, item));
        const no = chip.createEl("button", { text: "✕", cls: "ai-assistant-quick-btn" });
        no.setAttribute("aria-label", "Dismiss");
        no.addEventListener("click", () => void this.resolveApproval("reject", id, item));
    }

    private async resolveApproval(action: "apply" | "reject", id: string, item?: ApprovalItem): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const body: { id: string; item?: ApprovalItem } = { id };
            if (item) body.item = item;
            const resp = await fetch(`http://${host}:${port}/approvals/${action}`, {
                method: "POST",
                headers: this.apiHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify(body),
                signal: AbortSignal.timeout(8000),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const what = item ? item.label : "all";
            new Notice(action === "apply" ? `Applied ${what}` : `Dismissed ${what}`);
        } catch (e) {
            new Notice(`Approval ${action} failed: ${e instanceof Error ? e.message : e}`);
        }
        void this.refreshProactive();
    }

    // ------------------------------------------------------------------
    // M39 — Goals panel: running goals with progress + pause/resume/cancel
    // ------------------------------------------------------------------
    private async refreshGoals(): Promise<void> {
        if (!this.goalsEl) return;
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/goals`, {
                signal: AbortSignal.timeout(3000), headers: this.apiHeaders(),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const goals = (await resp.json() as { goals: Goal[] }).goals ?? [];
            this.renderGoals(goals.filter(g => g.status === "running" || g.status === "paused"));
        } catch {
            this.goalsEl.style.display = "none";
        }
    }

    private renderGoals(goals: Goal[]): void {
        this.goalsEl.empty();
        if (goals.length === 0) { this.goalsEl.style.display = "none"; return; }
        this.goalsEl.style.display = "block";
        this.goalsEl.createEl("div", { text: `🎯 Goals — ${goals.length} active`, cls: "ai-assistant-memory-title" });

        for (const g of goals) {
            const box = this.goalsEl.createDiv("ai-assistant-proactive-item");
            const head = box.createDiv("ai-assistant-proactive-head");
            const tags = [g.recurring && `↻ ${g.recurring}`, g.template && `⚙ ${g.template}`].filter(Boolean).join(" · ");
            head.createEl("span", {
                text: `${g.description}  (${g.done}/${g.total})${tags ? " · " + tags : ""}`,
                cls: "ai-assistant-proactive-note",
            });
            const openBtn = head.createEl("button", { text: "Open", cls: "ai-assistant-quick-btn" });
            openBtn.addEventListener("click", () => void this.app.workspace.openLinkText(`AI/System/Goals/${g.slug}.md`, "", false));

            const btns = box.createDiv("ai-assistant-memory-btns");
            if (g.status === "running")
                btns.createEl("button", { text: "Pause", cls: "ai-assistant-quick-btn" })
                    .addEventListener("click", () => void this.goalControl(g.slug, "pause"));
            else
                btns.createEl("button", { text: "Resume", cls: "ai-assistant-quick-btn" })
                    .addEventListener("click", () => void this.goalControl(g.slug, "resume"));
            btns.createEl("button", { text: "Cancel", cls: "ai-assistant-quick-btn" })
                .addEventListener("click", () => void this.goalControl(g.slug, "cancel"));
        }
    }

    private async goalControl(slug: string, action: "pause" | "resume" | "cancel"): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/goals/control`, {
                method: "POST",
                headers: this.apiHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({ slug, action }),
                signal: AbortSignal.timeout(6000),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            new Notice(`Goal ${action}d: ${slug}`);
        } catch (e) {
            new Notice(`Goal ${action} failed: ${e instanceof Error ? e.message : e}`);
        }
        void this.refreshGoals();
    }

    private addMention(path: string): void {
        if (path && this.mentions.indexOf(path) === -1) {
            this.mentions.push(path);
            this.renderMentions();
        }
        this.focusInput();
    }

    private removeMention(path: string): void {
        this.mentions = this.mentions.filter(p => p !== path);
        this.renderMentions();
    }

    private clearMentions(): void {
        this.mentions = [];
        this.renderMentions();
    }

    private renderMentions(): void {
        if (!this.mentionsEl) return;
        this.mentionsEl.empty();
        if (this.mentions.length === 0) {
            this.mentionsEl.style.display = "none";
            return;
        }
        this.mentionsEl.style.display = "flex";
        for (const p of this.mentions) {
            const chip = this.mentionsEl.createEl("span", { cls: "ai-assistant-mention-chip" });
            const name = p.split("/").pop() ?? p;
            chip.createEl("span", { text: `@${name}`, attr: { title: p } });
            const x = chip.createEl("button", { text: "✕", cls: "ai-assistant-mention-remove" });
            x.addEventListener("click", () => this.removeMention(p));
        }
    }

    /** Best-effort scope from the shape of the selected text (informational in this slice). */
    private inferScope(text: string): PendingSelection["scope"] {
        const t = text.trim();
        if (!/\s/.test(t)) return "word";
        if (t.indexOf("\n\n") === -1 && !/^#{1,6}\s/.test(t)) return "paragraph";
        return "section";
    }

    // ------------------------------------------------------------------
    // M29 — vault restructuring proposal (copy/move/trash/mkdir): one-click approval.
    // ------------------------------------------------------------------
    private renderRestructureProposal(p: RestructureProposal): void {
        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-proposal");
        const icon = p.op === "trash" ? "🗑" : p.op === "mkdir" ? "📁" : "🗂";
        el.createEl("span", { text: `${icon} Proposed vault change — ${p.op}`, cls: "ai-assistant-label" });
        const body = el.createDiv("ai-assistant-body");
        body.createEl("p", { text: p.summary, cls: "ai-assistant-proposal-intent" });
        body.createEl("pre", { text: p.command, cls: "ai-assistant-proposal-word-original" });

        const controls = body.createDiv("ai-assistant-proposal-controls");
        const done = (text: string) => {
            el.addClass("ai-assistant-proposal-applied");
            controls.empty();
            controls.createEl("span", { text, cls: "ai-assistant-proposal-done" });
        };
        controls.createEl("button", { text: "Approve", cls: "ai-assistant-proposal-replace" })
            .addEventListener("click", () => {
                done("✓ Approved — running…");
                this.runApprovedCommand(p.command);
            });
        controls.createEl("button", { text: "Reject", cls: "ai-assistant-proposal-keep" })
            .addEventListener("click", () => done("✕ Rejected — nothing changed"));

        this.scrollToBottom();
        this.focusInput();
    }

    /** Run an approved restructuring command — sent verbatim so the service executes it
     *  directly (the same path as a user-typed `vault:` command). */
    private runApprovedCommand(command: string): void {
        this.editMode = false;
        this.pendingSelection = null;
        this.inputEl.value = command;
        void this.handleSend();
    }

    // M9 — edit proposal dialog (single commit point) + apply
    // ------------------------------------------------------------------

    /** Render Markdown into `el` the way Obsidian shows it; fall back to plain text. */
    private async renderMarkdownInto(el: HTMLElement, text: string): Promise<void> {
        try { await MarkdownRenderer.render(this.app, text, el, "", this); }
        catch { el.setText(text); }
    }

    /**
     * Render a proposal through the single dialog code path. A word proposal with
     * several `options` shows pickable chips; otherwise an original/proposed diff.
     */
    private async renderEditProposal(proposal: EditProposal): Promise<void> {
        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-proposal");
        el.createEl("span", { text: `✎ Proposed edit — ${proposal.scope}`, cls: "ai-assistant-label" });
        const body = el.createDiv("ai-assistant-body");
        if (proposal.intent) {
            body.createEl("p", { text: `Instruction: ${proposal.intent}`, cls: "ai-assistant-proposal-intent" });
        }

        const options = Array.isArray(proposal.options) ? proposal.options : [];

        // ── content: original & proposed rendered as MARKDOWN (as Obsidian shows it),
        //    not raw code blocks, so headings/bold/lists/links look right. ──────────
        if (options.length > 1) {
            const orig = body.createDiv("ai-assistant-proposal-word-original ai-assistant-proposal-md");
            await this.renderMarkdownInto(orig, proposal.original_text);
            body.createEl("span", { text: "Pick a replacement:", cls: "ai-assistant-proposal-tag" });
        } else {
            const diff   = body.createDiv("ai-assistant-proposal-diff");
            const before = diff.createDiv("ai-assistant-proposal-before");
            before.createEl("span", { text: "− Original", cls: "ai-assistant-proposal-tag" });
            await this.renderMarkdownInto(before.createDiv("ai-assistant-proposal-md"), proposal.original_text);
            const after  = diff.createDiv("ai-assistant-proposal-after");
            after.createEl("span", { text: "+ Proposed", cls: "ai-assistant-proposal-tag" });
            await this.renderMarkdownInto(after.createDiv("ai-assistant-proposal-md"), proposal.replacement);
        }

        const controls = body.createDiv("ai-assistant-proposal-controls");

        const markApplied = () => {
            el.addClass("ai-assistant-proposal-applied");
            controls.empty();
            controls.createEl("span", { text: "✓ Applied", cls: "ai-assistant-proposal-done" });
            this.clearSelection();
        };
        const keepEditing = () => {
            // Restore the region so the user can refine the instruction and resend.
            if (proposal.offsets) {
                this.pendingSelection = {
                    text:  proposal.original_text,
                    from:  proposal.offsets.from,
                    to:    proposal.offsets.to,
                    scope: (proposal.scope as PendingSelection["scope"]) ?? "paragraph",
                };
                this.editMode = true;
                this.renderSelectionBadge();
            }
            el.remove();
            this.updateInputPlaceholder();
            this.focusInput();
        };
        const cancel = () => {
            // Discard the proposal entirely — no re-edit, drop the attached selection.
            el.remove();
            this.clearSelection();
            this.updateInputPlaceholder();
            this.focusInput();
        };

        if (options.length > 1) {
            const chips = controls.createDiv("ai-assistant-proposal-options");
            for (const opt of options) {
                const chip = chips.createEl("button", { text: opt, cls: "ai-assistant-option-chip" });
                chip.addEventListener("click", async () => { if (await this.applyProposalReplacement(proposal, opt)) markApplied(); });
            }
        } else {
            controls.createEl("button", { text: "Replace", cls: "ai-assistant-proposal-replace" })
                .addEventListener("click", async () => { if (await this.applyProposalReplacement(proposal, proposal.replacement)) markApplied(); });
        }
        controls.createEl("button", { text: "Keep editing", cls: "ai-assistant-proposal-keep" })
            .addEventListener("click", keepEditing);
        controls.createEl("button", { text: "Cancel", cls: "ai-assistant-proposal-cancel" })
            .addEventListener("click", cancel);

        this.scrollToBottom();
        this.focusInput();
    }

    /**
     * Find the editor a Live proposal applies to. Clicking the sidebar makes IT the
     * "active" editor, so we can't rely on activeEditor — instead scan the open markdown
     * panes for the one whose text at the proposal's offsets still matches the original.
     */
    private findEditorForProposal(proposal: EditProposal): Editor | undefined {
        const wantPath = proposal.note_path ? proposal.note_path.replace(/\\/g, "/") : null;
        const leaves = this.app.workspace.getLeavesOfType("markdown");
        // 1) Best: the pane for the note this proposal targets (stable even if the text
        //    drifted — that lets the drift guard fire correctly instead of "note not found").
        if (wantPath) {
            for (const leaf of leaves) {
                const view = leaf.view as MarkdownView;
                if (view?.file?.path === wantPath && view.editor) return view.editor;
            }
        }
        // 2) A pane whose text at the offsets still matches the original.
        const off = proposal.offsets;
        if (off && off.from && off.to) {
            for (const leaf of leaves) {
                const ed = (leaf.view as MarkdownView)?.editor;
                if (!ed) continue;
                try {
                    if (ed.getRange(off.from, off.to) === proposal.original_text) return ed;
                } catch { /* offsets out of range for this document — not the target */ }
            }
        }
        return this.app.workspace.activeEditor?.editor ?? undefined;   // last resort
    }

    /** Commit `replacement` at the proposal's offsets, guarding against drift. */
    private applyReplacement(proposal: EditProposal, replacement: string): boolean {
        const off = proposal.offsets;
        if (!off || !off.from || !off.to) { new Notice("This proposal has no location to apply to."); return false; }

        const editor = this.findEditorForProposal(proposal);
        if (!editor) {
            new Notice("Open the note you selected from (keep it visible in a pane), then click Replace.");
            return false;
        }
        const current = editor.getRange(off.from, off.to);
        if (current !== proposal.original_text) {
            new Notice("Couldn't find the exact original text (the note changed, or its pane isn't open) — "
                     + "re-select the region and try again.");
            return false;
        }
        editor.replaceRange(replacement, off.from, off.to);
        new Notice("Edit applied.");
        return true;
    }

    /** Commit a proposal: Live (offsets) applies in the editor; Vault resolves the anchor in the file. */
    private async applyProposalReplacement(proposal: EditProposal, replacement: string): Promise<boolean> {
        if (proposal.offsets) return this.applyReplacement(proposal, replacement);
        return this.applyVaultProposal(proposal, replacement);
    }

    // ------------------------------------------------------------------
    // M9 — Vault-mode proposals: detect, resolve the anchor, commit
    // ------------------------------------------------------------------

    /** When a note opens, surface any staged edit proposal through the same dialog. */
    private async checkNoteForProposal(file: TFile): Promise<void> {
        if (!file || file.extension !== "md") return;
        let content: string;
        try { content = await this.app.vault.read(file); } catch { return; }
        const proposal = this.extractProposalFromContent(content);
        if (!proposal || this.shownProposalIds.has(proposal.id)) return;
        this.shownProposalIds.add(proposal.id);
        proposal.offsets = null;        // force the vault (anchor) apply path
        if (!proposal.note_path) proposal.note_path = file.path;
        this.renderEditProposal(proposal);
        new Notice("A staged edit proposal is ready to review in the Loremaster panel.");
    }

    private extractProposalFromContent(content: string): EditProposal | null {
        const bi = content.indexOf(PROPOSAL_BEGIN);
        const ei = content.indexOf(PROPOSAL_END);
        if (bi < 0 || ei < 0 || ei < bi) return null;
        try {
            return JSON.parse(content.slice(bi + PROPOSAL_BEGIN.length, ei).trim()) as EditProposal;
        } catch {
            return null;
        }
    }

    /** Resolve + apply a staged proposal at the file level, then strip the block and clear status. */
    private async applyVaultProposal(proposal: EditProposal, replacement: string): Promise<boolean> {
        // note_path may have OS backslashes or be missing; normalise, then fall back to the
        // note currently open (this apply path is entered from checkNoteForProposal on that note).
        const wantPath = proposal.note_path ? proposal.note_path.replace(/\\/g, "/") : null;
        let file = wantPath ? this.app.vault.getAbstractFileByPath(wantPath) : null;
        if (!(file instanceof TFile)) file = this.app.workspace.getActiveFile();
        if (!(file instanceof TFile)) { new Notice("Could not find the target note — open it, then click Replace."); return false; }

        let raw = await this.app.vault.read(file);
        raw = this.stripProposalSection(raw);          // drop the proposal block first
        const region = this.resolveAnchor(raw, proposal);
        if (!region) {
            new Notice("Couldn't locate the region — open the note and select it manually.");
            return false;
        }
        raw = raw.slice(0, region.start) + replacement + raw.slice(region.end);
        raw = this.setStatusDone(raw);
        await this.app.vault.modify(file, raw);
        new Notice("Edit applied to " + file.name);
        return true;
    }

    /** End index of the frontmatter block (0 if none), so a whole-note replace keeps it. */
    private frontmatterEnd(content: string): number {
        if (!content.startsWith("---")) return 0;
        const m = content.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/);
        return m ? m[0].length : 0;
    }

    /** Exact-match the original region (by occurrence), so a changed note fails safe to "select manually". */
    private resolveAnchor(content: string, proposal: EditProposal): { start: number; end: number } | null {
        // Whole-note edits replace the entire body (after any frontmatter) — no fragile
        // exact-match of the whole original, which broke on trailing-whitespace drift.
        if (proposal.scope === "whole-note") {
            return { start: this.frontmatterEnd(content), end: content.length };
        }
        const needle = proposal.original_text;
        if (!needle) return null;
        const occ = (proposal.anchor && proposal.anchor.occurrence) ? proposal.anchor.occurrence : 1;
        let from = 0, idx = -1, count = 0;
        for (;;) {
            const i = content.indexOf(needle, from);
            if (i < 0) break;
            if (++count === occ) { idx = i; break; }
            from = i + 1;
        }
        if (idx < 0) idx = content.indexOf(needle);    // fall back to the first occurrence
        if (idx < 0) return null;
        return { start: idx, end: idx + needle.length };
    }

    private stripProposalSection(content: string): string {
        const i = content.indexOf(PROPOSAL_HEADING);
        return i < 0 ? content : content.slice(0, i).replace(/\s+$/, "") + "\n";
    }

    private setStatusDone(content: string): string {
        return /^assistant-status:.*$/m.test(content)
            ? content.replace(/^assistant-status:.*$/m, 'assistant-status: "done"')
            : content;
    }

    /** Web edit handoff: package shown for paste; the returned text becomes the proposal. */
    private enterEditHandoffMode(promptToCopy: string): void {
        this.chatMode = "edit-handoff-awaiting";
        this.updateSendButton();
        this.updateInputPlaceholder();
        this.containerEl.setAttribute("data-chat-mode", "edit-handoff-awaiting");

        const el = this.messagesEl.createDiv("ai-assistant-message ai-assistant-handoff");
        el.createEl("span", { text: "✎ Web Edit Handoff", cls: "ai-assistant-label" });
        const body = el.createDiv("ai-assistant-body");
        body.createEl("p", {
            text: "No provider was available for this edit. Copy the prompt into any web AI, then paste " +
                  "its revised text in the input box — it becomes a proposal you can Replace.",
        });
        const controls = body.createDiv("ai-assistant-handoff-controls");
        const copyBtn = controls.createEl("button", { text: "📋 Copy Prompt", cls: "ai-assistant-copy-btn" });
        copyBtn.addEventListener("click", async () => {
            await navigator.clipboard.writeText(promptToCopy);
            copyBtn.setText("✓ Copied!");
            setTimeout(() => copyBtn.setText("📋 Copy Prompt"), 2000);
            this.focusInput();
        });
        controls.createEl("button", { text: "Cancel", cls: "ai-assistant-proposal-cancel" })
            .addEventListener("click", () => {
                el.remove();
                this.chatMode = "normal";
                this.containerEl.setAttribute("data-chat-mode", "normal");
                this.updateSendButton();
                this.updateInputPlaceholder();
                this.focusInput();
            });
        const preview = body.createEl("pre", { cls: "ai-assistant-handoff-preview" });
        preview.setText(promptToCopy);
        this.scrollToBottom();
        this.focusInput();
    }

    private async submitEditHandoffReturn(pasted: string): Promise<void> {
        const ctx = this.pendingEditContext;
        this.chatMode = "normal";
        this.containerEl.setAttribute("data-chat-mode", "normal");
        this.updateSendButton();
        this.updateInputPlaceholder();
        if (!ctx) {
            await this.appendErrorMessage("Lost the edit context — please re-select the region and try again.");
            return;
        }
        this.pendingEditContext = null;
        this.renderEditProposal({
            id: "ep-web", note_path: ctx.note_path, scope: ctx.scope, intent: ctx.intent,
            original_text: ctx.original_text, replacement: pasted.trim(), options: [],
            offsets: ctx.offsets, source: "live", status: "proposed",
        });
    }

    /** BUG-005: central focus method — always safe to call */
    private focusInput(): void {
        // Use requestAnimationFrame so the DOM has settled after rendering
        requestAnimationFrame(() => {
            if (this.inputEl && !this.isLoading) {
                this.inputEl.focus();
            }
        });
    }

    private setLoading(v: boolean): void {
        this.isLoading        = v;
        this.sendBtn.disabled = v;
        this.inputEl.disabled = v;
        this.updateSendButton();
        // BUG-005: re-focus when loading completes
        if (!v) this.focusInput();
    }

    private updateSendButton(): void {
        if (this.isLoading)                                      this.sendBtn.setText("...");
        else if (this.chatMode === "handoff-awaiting-response")  this.sendBtn.setText("Return Response");
        else if (this.chatMode === "edit-handoff-awaiting")      this.sendBtn.setText("Return Edit");
        else                                                     this.sendBtn.setText("Send");
    }

    private updateInputPlaceholder(): void {
        if (this.chatMode === "handoff-awaiting-response")
            this.inputEl.placeholder = "Paste web AI response here...";
        else if (this.chatMode === "edit-handoff-awaiting")
            this.inputEl.placeholder = "Paste the web AI's revised text here...";
        else if (this.editMode && this.pendingSelection)
            this.inputEl.placeholder = "✎ Describe the edit to the selected region...";
        else if (this.vaultQa)
            this.inputEl.placeholder = "📚 Ask your whole vault... (cited answers)";
        else if (this.isPrivate)
            this.inputEl.placeholder = "🔒 Private — no-train providers only (no Gemini)...";
        else if (this.selectedProvider === "webui")
            this.inputEl.placeholder = "Ask... (will package for web AI)";
        else
            this.inputEl.placeholder = "Ask anything... (Enter to send, Shift+Enter for newline)";
    }

    private setConnectMode(mode: "http" | "vault"): void {
        this.containerEl.setAttribute("data-mode", mode);
        this.modeEl.setText(mode === "http" ? "Live" : "Vault");
        this.modeEl.className = `ai-assistant-mode ai-assistant-mode-${mode}`;
    }

    private clearMessages(): void {
        this.chatMode = "normal";
        this.containerEl.setAttribute("data-chat-mode", "normal");
        this.pendingEditContext = null;
        this.clearSelection();          // also resets editMode + badge
        this.clearMentions();
        this.updateSendButton();
        this.updateInputPlaceholder();
        this.messagesEl.empty();
        this.focusInput();    // BUG-005
    }

    private scrollToBottom(): void {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }
}
