import { Plugin, WorkspaceLeaf, PluginSettingTab, Setting, App, Notice, Modal, Editor, Menu, MarkdownView } from "obsidian";
import { ChatView, CHAT_VIEW_TYPE, ComposeModal, ApprovalsView, APPROVALS_VIEW_TYPE } from "./ChatView";
import { Reader, ReaderSettings } from "./reader";

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
export interface AIAssistantSettings {
    host: string;
    port: number;
    apiToken: string;      // X-API-Key for LAN access (must match the service's api_token)
    handshakeDir: string;  // vault folder for vault-mode chat notes
    reader: ReaderSettings; // v1.7 — read-aloud speed + voice
}

const DEFAULT_SETTINGS: AIAssistantSettings = {
    host: "127.0.0.1",
    port: 8765,
    apiToken: "",
    handshakeDir: "AI/Chat",
    reader: { speed: 1, voiceName: "" },
};

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------
export default class AIAssistantPlugin extends Plugin {
    settings!: AIAssistantSettings;
    reader!: Reader;   // v1.7 — read-aloud engine

    async onload(): Promise<void> {
        await this.loadSettings();
        this.reader = new Reader(this.settings.reader, () => void this.saveSettings(),
                                 (text) => this.fetchTts(text));

        // Register the sidebar chat view + the Approvals/Goals side panel (v1.7 — non-blocking)
        this.registerView(CHAT_VIEW_TYPE, (leaf: WorkspaceLeaf) => new ChatView(leaf, this));
        this.registerView(APPROVALS_VIEW_TYPE, (leaf: WorkspaceLeaf) => new ApprovalsView(leaf, this));

        // Ribbon button — opens the chat sidebar
        this.addRibbonIcon("bot", "Open Loremaster", () => {
            this.activateChatView();
        });

        // Command palette entries
        this.addCommand({
            id: "open-ai-assistant",
            name: "Open chat sidebar",
            callback: () => this.activateChatView(),
        });
        this.addCommand({
            id: "ai-summarize-note",
            name: "Summarize active note",
            callback: async () => { await this.activateChatView(); this.getChatView()?.commandSummarize(); },
        });
        this.addCommand({
            id: "ai-run-prompt",
            name: "Run a saved prompt",
            callback: async () => { await this.activateChatView(); this.getChatView()?.commandPrompts(); },
        });
        // M40 — web clipper: prompt for a URL and save it as a sourced, indexed note.
        this.addCommand({
            id: "ai-clip-url",
            name: "Clip a web page to the vault",
            callback: () => {
                new TextPromptModal(this.app, "Clip a web page", "https://… (or a YouTube link)", async (url) => {
                    await this.activateChatView();
                    this.getChatView()?.commandClip(url);
                }, true).open();
            },
        });
        // v1.6 — immersive inline editing via a controlled popup (ComposeModal).
        this.addCommand({
            id: "ai-continue-writing",
            name: "Continue writing (inline)",
            editorCallback: (editor: Editor) => new ComposeModal(this.app, this, editor, "continue").open(),
        });
        this.addCommand({
            id: "ai-rewrite-selection",
            name: "Rewrite selection (inline)",
            editorCallback: (editor: Editor) => new ComposeModal(this.app, this, editor, "rewrite").open(),
        });
        this.addCommand({
            id: "ai-compose",
            name: "Compose with Loremaster…",
            editorCallback: (editor: Editor) => new ComposeModal(this.app, this, editor, "compose").open(),
        });
        // v1.7 — read-aloud (offline TTS): selection if any, else the whole note.
        this.addCommand({
            id: "ai-read-aloud",
            name: "Read note aloud",
            // Plain callback (not editorCallback) so it ALWAYS shows in the palette — including
            // mobile/reading view, where there's no active editor (that's why it was missing on
            // Android). Uses the editor when available (for sentence highlight), else reads the
            // active file's text directly.
            callback: async () => {
                const view = this.app.workspace.getActiveViewOfType(MarkdownView);
                // Editing / Live Preview: readNote reads the selection if any (with highlight),
                // else the whole note minus frontmatter.
                if (view?.editor && view.getMode() === "source") {
                    this.reader.readNote(view.editor);
                    return;
                }
                // Reading view (incl. mobile): honor a highlighted text selection if there is one.
                const domSel = (window.getSelection?.()?.toString() ?? "").trim();
                if (domSel) { this.reader.readText(domSel); return; }
                const file = this.app.workspace.getActiveFile();
                if (!file) { new Notice("Open a note to read aloud."); return; }
                this.reader.readText(await this.app.vault.read(file));
            },
        });
        this.addCommand({
            id: "ai-read-stop",
            name: "Stop reading",
            callback: () => this.reader.stop(),
        });
        // M40 — fill a Templater/Templates template from context (propose-only).
        this.addCommand({
            id: "ai-fill-template",
            name: "Fill a template with Loremaster",
            callback: () => {
                new TextPromptModal(this.app, "Fill a template", "Template name (optionally: name :: context)", async (arg) => {
                    await this.activateChatView();
                    this.getChatView()?.commandVault(`vault:template ${arg}`);
                }).open();
            },
        });

        // v1.8 — Loremaster actions in the editor right-click menu.
        this.registerEvent(this.app.workspace.on("editor-menu", (menu: Menu, editor: Editor) => {
            menu.addItem((i) => i.setTitle("Loremaster: Read aloud").setIcon("volume-2")
                .onClick(() => this.reader.readNote(editor)));
            if (editor.getSelection()) {
                menu.addItem((i) => i.setTitle("Loremaster: Rewrite selection").setIcon("wand-2")
                    .onClick(() => new ComposeModal(this.app, this, editor, "rewrite").open()));
            }
            menu.addItem((i) => i.setTitle("Loremaster: Continue writing").setIcon("pencil")
                .onClick(() => new ComposeModal(this.app, this, editor, "continue").open()));
            menu.addItem((i) => i.setTitle("Loremaster: Compose…").setIcon("bot")
                .onClick(() => new ComposeModal(this.app, this, editor, "compose").open()));
        }));

        // Settings tab
        this.addSettingTab(new AIAssistantSettingTab(this.app, this));

        // Auto-open the sidebar on startup if it was open last session
        this.app.workspace.onLayoutReady(() => {
            if (!this.app.workspace.getLeavesOfType(CHAT_VIEW_TYPE).length) {
                this.activateChatView();
            }
        });
    }

    async onunload(): Promise<void> {
        this.app.workspace.detachLeavesOfType(CHAT_VIEW_TYPE);
        this.app.workspace.detachLeavesOfType(APPROVALS_VIEW_TYPE);
    }

    // v1.7 — open/reveal the Approvals & Goals side panel (non-blocking, dockable) on a tab.
    async openApprovals(tab: "approvals" | "goals"): Promise<void> {
        const { workspace } = this.app;
        // The Approvals panel renders via the ChatView; make sure one exists first so it
        // never falls back to the "open chat first" placeholder. (bug: getRightLeaf(false)
        // used to reuse — and evict — the chat's own sidebar leaf, leaving getChatView() null.)
        await this.ensureChatView();
        let leaf = workspace.getLeavesOfType(APPROVALS_VIEW_TYPE)[0];
        if (!leaf) {
            // `true` → a NEW split leaf, so we don't steal the chat's leaf.
            const right = workspace.getRightLeaf(true) ?? workspace.getRightLeaf(false);
            if (!right) return;
            leaf = right;
            await leaf.setViewState({ type: APPROVALS_VIEW_TYPE, active: true });
        }
        workspace.revealLeaf(leaf);
        (leaf.view as ApprovalsView).setTab(tab);
    }

    /** Ensure a ChatView leaf exists (creating one in the right sidebar if needed) WITHOUT
     *  stealing focus. Returns the ChatView so callers can render through it. */
    async ensureChatView(): Promise<ChatView | null> {
        const { workspace } = this.app;
        if (!workspace.getLeavesOfType(CHAT_VIEW_TYPE).length) {
            const right = workspace.getRightLeaf(false);
            if (right) await right.setViewState({ type: CHAT_VIEW_TYPE, active: false });
        }
        return this.getChatView();
    }

    /** v1.9.3 — fetch synthesized speech from the service (used by read-aloud on Android, where
     *  the browser has no Web Speech engine). Returns a WAV Blob, or null if unavailable. */
    async fetchTts(text: string): Promise<Blob | null> {
        const { host, port, apiToken } = this.settings;
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (apiToken?.trim()) headers["X-API-Key"] = apiToken.trim();
        try {
            const resp = await fetch(`http://${host}:${port}/tts`, {
                method: "POST", headers, body: JSON.stringify({ text }),
                signal: AbortSignal.timeout(60000),
            });
            if (!resp.ok) return null;
            return await resp.blob();
        } catch {
            return null;
        }
    }

    // v1.8 — refine a proposed goal's plan with feedback (iterate before approving).
    replanGoal(slug: string): void {
        new TextPromptModal(this.app, `Refine plan: ${slug}`, "What should change? (feedback)", async (fb) => {
            await this.activateChatView();
            this.getChatView()?.commandVault(`vault:goal replan ${slug} :: ${fb}`);
        }).open();
    }

    // ------------------------------------------------------------------
    // Sidebar management
    // ------------------------------------------------------------------
    getChatView(): ChatView | null {
        const leaf = this.app.workspace.getLeavesOfType(CHAT_VIEW_TYPE)[0];
        return leaf ? (leaf.view as ChatView) : null;
    }

    async activateChatView(): Promise<void> {
        const { workspace } = this.app;

        // Reuse existing leaf if already open
        let leaf = workspace.getLeavesOfType(CHAT_VIEW_TYPE)[0];

        if (!leaf) {
            // Open in the right sidebar
            const rightLeaf = workspace.getRightLeaf(false);
            if (!rightLeaf) return;
            leaf = rightLeaf;
            await leaf.setViewState({ type: CHAT_VIEW_TYPE, active: true });
        }

        workspace.revealLeaf(leaf);
    }

    // ------------------------------------------------------------------
    // Settings persistence
    // ------------------------------------------------------------------
    async loadSettings(): Promise<void> {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings(): Promise<void> {
        await this.saveData(this.settings);
    }
}

// ---------------------------------------------------------------------------
// v1.6 — generic one-line text prompt (used by the clipper + template fill)
// ---------------------------------------------------------------------------
class TextPromptModal extends Modal {
    constructor(
        app: App,
        private title: string,
        private placeholder: string,
        private onSubmit: (value: string) => void,
        private prefillUrlFromClipboard = false,
    ) { super(app); }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.createEl("h3", { text: this.title });
        const input = contentEl.createEl("input", { type: "text", placeholder: this.placeholder });
        input.style.width = "100%";
        if (this.prefillUrlFromClipboard) {
            navigator.clipboard?.readText?.().then((t) => {
                if (/^https?:\/\//i.test((t || "").trim())) input.value = t.trim();
            }).catch(() => {});
        }
        const submit = () => {
            const v = input.value.trim();
            this.close();
            if (v) this.onSubmit(v);
        };
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
        const row = contentEl.createDiv();
        row.style.marginTop = "8px";
        row.createEl("button", { text: "OK", cls: "mod-cta" }).addEventListener("click", submit);
        setTimeout(() => input.focus(), 0);
    }

    onClose(): void { this.contentEl.empty(); }
}

// ---------------------------------------------------------------------------
// Settings tab
// ---------------------------------------------------------------------------
class AIAssistantSettingTab extends PluginSettingTab {
    plugin: AIAssistantPlugin;

    constructor(app: App, plugin: AIAssistantPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        containerEl.createEl("h2", { text: "Loremaster Settings" });

        // Connection section
        containerEl.createEl("h3", { text: "Service connection" });
        containerEl.createEl("p", {
            text: "The assistant connects to your local Python service. If the service is offline, it falls back to vault-file mode automatically.",
            cls: "setting-item-description",
        });

        new Setting(containerEl)
            .setName("Host")
            .setDesc("Hostname where the Python service runs (default: 127.0.0.1)")
            .addText((text) =>
                text
                    .setPlaceholder("127.0.0.1")
                    .setValue(this.plugin.settings.host)
                    .onChange(async (value) => {
                        this.plugin.settings.host = value.trim() || "127.0.0.1";
                        await this.plugin.saveSettings();
                    })
            );

        new Setting(containerEl)
            .setName("Port")
            .setDesc("Port the Python service listens on (default: 8765)")
            .addText((text) =>
                text
                    .setPlaceholder("8765")
                    .setValue(String(this.plugin.settings.port))
                    .onChange(async (value) => {
                        const parsed = parseInt(value, 10);
                        if (!isNaN(parsed) && parsed > 0 && parsed < 65536) {
                            this.plugin.settings.port = parsed;
                            await this.plugin.saveSettings();
                        }
                    })
            );

        new Setting(containerEl)
            .setName("API token")
            .setDesc("Required when connecting to a service exposed on the LAN (must match `api_token` " +
                     "in the service's settings.json). Leave blank for a local-only service.")
            .addText((text) =>
                text
                    .setPlaceholder("(none)")
                    .setValue(this.plugin.settings.apiToken)
                    .onChange(async (value) => {
                        this.plugin.settings.apiToken = value.trim();
                        await this.plugin.saveSettings();
                    })
            );

        // Vault mode section
        containerEl.createEl("h3", { text: "Vault mode" });
        containerEl.createEl("p", {
            text: "When the service is offline, messages are written to a vault note and the watcher responds. This works from any device with Obsidian Sync.",
            cls: "setting-item-description",
        });

        new Setting(containerEl)
            .setName("Chat notes folder")
            .setDesc(
                "Vault folder where chat request notes are created (e.g. AI/Chat). " +
                "The folder is created automatically if it doesn't exist."
            )
            .addText((text) =>
                text
                    .setPlaceholder("AI/Chat")
                    .setValue(this.plugin.settings.handshakeDir)
                    .onChange(async (value) => {
                        this.plugin.settings.handshakeDir = value.trim() || "AI/Chat";
                        await this.plugin.saveSettings();
                    })
            );

        // Status check
        containerEl.createEl("h3", { text: "Connection check" });
        const statusEl = containerEl.createEl("p", { text: "Click to test...", cls: "setting-item-description" });

        new Setting(containerEl)
            .setName("Test connection")
            .setDesc("Try to reach the Python service right now.")
            .addButton((btn) =>
                btn.setButtonText("Test").onClick(async () => {
                    const { host, port } = this.plugin.settings;
                    try {
                        const resp = await fetch(`http://${host}:${port}/status`, {
                            signal: AbortSignal.timeout(3000),
                        });
                        const data = await resp.json();
                        statusEl.setText(
                            `✓ Connected — provider: ${data.active_provider ?? "none"}, ` +
                            `session messages: ${data.message_count}`
                        );
                        statusEl.style.color = "var(--color-green)";
                    } catch {
                        statusEl.setText(`✗ Could not connect to http://${host}:${port} — is the Python service running?`);
                        statusEl.style.color = "var(--color-red)";
                    }
                })
            );

        // ── Service control panel — edit the running service's settings.json ──
        containerEl.createEl("h3", { text: "Service settings (control panel)" });
        containerEl.createEl("p", {
            text: "Load and edit the running service's settings.json. Keys tagged (live) apply " +
                  "immediately; (restart) keys need a restart (shown after saving). Secrets are " +
                  "write-only — leave blank to keep the current value.",
            cls: "setting-item-description",
        });
        const panel = containerEl.createDiv("ai-assistant-control-panel");
        const controls = new Setting(containerEl)
            .setName("Server config")
            .setDesc("Pull the current settings from the service, edit, then save.");
        controls.addButton((b) => b.setButtonText("Load").onClick(() => this.loadServerSettings(panel)));
        controls.addButton((b) =>
            b.setButtonText("Restart service").setWarning().onClick(() => this.restartService()));
    }

    // ------------------------------------------------------------------
    // Service control panel (M16.5)
    // ------------------------------------------------------------------
    private apiBase(): string {
        const { host, port } = this.plugin.settings;
        return `http://${host}:${port}`;
    }

    private apiHeaders(): Record<string, string> {
        const h: Record<string, string> = { "Content-Type": "application/json" };
        if (this.plugin.settings.apiToken) h["X-API-Key"] = this.plugin.settings.apiToken;
        return h;
    }

    private async loadServerSettings(panel: HTMLElement): Promise<void> {
        panel.empty();
        panel.createEl("p", { text: "Loading…", cls: "setting-item-description" });
        let data: { settings?: Record<string, unknown>; live_keys?: string[]; admin_allowed?: boolean };
        try {
            const resp = await fetch(`${this.apiBase()}/settings`,
                { headers: this.apiHeaders(), signal: AbortSignal.timeout(4000) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            data = await resp.json();
        } catch (e) {
            panel.empty();
            panel.createEl("p", {
                text: `✗ Could not load settings: ${e}. Is the service running, and the API token correct?`,
                cls: "setting-item-description",
            });
            return;
        }

        panel.empty();
        const settings = data.settings ?? {};
        const live = data.live_keys ?? [];
        const pending: Record<string, unknown> = {};

        if (data.admin_allowed === false) {
            panel.createEl("p", {
                text: "⚠ Admin is disabled on the service (public bind without an api_token). " +
                      "Set api_token in settings.json to enable saving and restart.",
                cls: "setting-item-description",
            });
        }

        for (const [key, value] of Object.entries(settings)) {
            const setting = new Setting(panel).setName(key + (live.includes(key) ? " (live)" : " (restart)"));
            const isSecret = key === "api_token" || key.endsWith("_api_key");
            if (isSecret) {
                setting.setDesc("write-only — leave blank to keep");
                setting.addText((t) => {
                    t.setPlaceholder("(unchanged)");
                    t.inputEl.type = "password";
                    t.onChange((v) => { if (v) pending[key] = v; else delete pending[key]; });
                });
            } else if (typeof value === "boolean") {
                setting.addToggle((t) => t.setValue(value).onChange((v) => (pending[key] = v)));
            } else if (typeof value === "number") {
                setting.addText((t) => t.setValue(String(value)).onChange((v) => {
                    const n = Number(v); if (!isNaN(n)) pending[key] = n;
                }));
            } else if (Array.isArray(value)) {
                setting.setDesc("one per line");
                setting.addTextArea((t) => {
                    t.setValue((value as unknown[]).join("\n"));
                    t.inputEl.rows = 3;
                    t.inputEl.style.width = "100%";
                    t.onChange((v) => (pending[key] = v.split("\n").map((s) => s.trim()).filter(Boolean)));
                });
            } else if (value && typeof value === "object" && !Array.isArray(value)) {
                setting.setDesc(Object.keys(value).join(" / "));
                for (const [sub, sv] of Object.entries(value as Record<string, unknown>)) {
                    setting.addText((t) => {
                        t.setPlaceholder(sub).setValue(String(sv)).onChange((v) => {
                            const n = Number(v);
                            if (!isNaN(n)) pending[key] = { ...(value as object), ...(pending[key] as object ?? {}), [sub]: n };
                        });
                        t.inputEl.style.width = "5em";
                    });
                }
            } else {
                setting.addText((t) =>
                    t.setValue(value == null ? "" : String(value)).onChange((v) => (pending[key] = v)));
            }
        }

        new Setting(panel).addButton((b) =>
            b.setButtonText("Save to service").setCta().onClick(() => this.saveServerSettings(panel, pending)));
    }

    private async saveServerSettings(panel: HTMLElement, pending: Record<string, unknown>): Promise<void> {
        const status = panel.createEl("p", { text: "Saving…", cls: "setting-item-description" });
        try {
            const resp = await fetch(`${this.apiBase()}/settings`, {
                method: "PUT", headers: this.apiHeaders(),
                body: JSON.stringify(pending), signal: AbortSignal.timeout(5000),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail ?? `HTTP ${resp.status}`);
            const updated: string[] = data.updated ?? [];
            const restart: string[] = data.restart_required ?? [];
            status.setText(`✓ Saved: ${updated.join(", ") || "no changes"}.` +
                (restart.length ? ` Restart needed for: ${restart.join(", ")}.` : " Applied live."));
            if (restart.length) {
                new Setting(panel).addButton((b) =>
                    b.setButtonText("Restart now").setWarning().onClick(() => this.restartService()));
            }
        } catch (e) {
            status.setText(`✗ Save failed: ${e}`);
        }
    }

    private async restartService(): Promise<void> {
        try {
            const resp = await fetch(`${this.apiBase()}/restart`,
                { method: "POST", headers: this.apiHeaders(), signal: AbortSignal.timeout(4000) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            new Notice("Restart requested — the service will be back in a moment.");
        } catch (e) {
            new Notice(`Restart failed: ${e}`);
        }
    }
}
