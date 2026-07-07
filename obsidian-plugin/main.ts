import { Plugin, WorkspaceLeaf, PluginSettingTab, Setting, App, Notice } from "obsidian";
import { ChatView, CHAT_VIEW_TYPE } from "./ChatView";

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
export interface AIAssistantSettings {
    host: string;
    port: number;
    apiToken: string;      // X-API-Key for LAN access (must match the service's api_token)
    handshakeDir: string;  // vault folder for vault-mode chat notes
}

const DEFAULT_SETTINGS: AIAssistantSettings = {
    host: "127.0.0.1",
    port: 8765,
    apiToken: "",
    handshakeDir: "AI/Chat",
};

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------
export default class AIAssistantPlugin extends Plugin {
    settings!: AIAssistantSettings;

    async onload(): Promise<void> {
        await this.loadSettings();

        // Register the sidebar chat view
        this.registerView(CHAT_VIEW_TYPE, (leaf: WorkspaceLeaf) => new ChatView(leaf, this));

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
