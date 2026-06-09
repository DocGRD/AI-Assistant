import { Plugin, WorkspaceLeaf, PluginSettingTab, Setting, App } from "obsidian";
import { ChatView, CHAT_VIEW_TYPE } from "./ChatView";

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
export interface AIAssistantSettings {
    host: string;
    port: number;
    handshakeDir: string;  // vault folder for vault-mode chat notes
}

const DEFAULT_SETTINGS: AIAssistantSettings = {
    host: "127.0.0.1",
    port: 8765,
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
        this.addRibbonIcon("bot", "Open AI Assistant", () => {
            this.activateChatView();
        });

        // Command palette entry
        this.addCommand({
            id: "open-ai-assistant",
            name: "Open chat sidebar",
            callback: () => this.activateChatView(),
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

        containerEl.createEl("h2", { text: "AI Assistant Settings" });

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
    }
}
