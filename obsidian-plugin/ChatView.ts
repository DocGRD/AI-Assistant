import { ItemView, WorkspaceLeaf, MarkdownRenderer, Notice } from "obsidian";
import type AIAssistantPlugin from "./main";

export const CHAT_VIEW_TYPE = "ai-assistant-chat";

// ---------------------------------------------------------------------------
// Types mirroring the Python server's response shapes
// ---------------------------------------------------------------------------
interface ChatResponse {
    reply: string;
    provider_used: string;
    timestamp: string;
}

interface StatusResponse {
    online: boolean;
    providers: Record<string, boolean>;
    active_provider: string | null;
    session_started: string;
    message_count: number;
}

interface HistoryMessage {
    role: string;
    content: string;
}

interface HistoryResponse {
    messages: HistoryMessage[];
    count: number;
}

// ---------------------------------------------------------------------------
// ChatView
// ---------------------------------------------------------------------------
export class ChatView extends ItemView {
    private plugin: AIAssistantPlugin;
    private messagesEl!: HTMLElement;
    private inputEl!: HTMLTextAreaElement;
    private sendBtn!: HTMLButtonElement;
    private statusEl!: HTMLElement;
    private modeEl!: HTMLElement;
    private isLoading = false;

    constructor(leaf: WorkspaceLeaf, plugin: AIAssistantPlugin) {
        super(leaf);
        this.plugin = plugin;
    }

    getViewType(): string { return CHAT_VIEW_TYPE; }
    getDisplayText(): string { return "AI Assistant"; }
    getIcon(): string { return "bot"; }

    async onOpen(): Promise<void> {
        this.buildUI();
        await this.loadStatus();
        await this.loadHistory();
    }

    async onClose(): Promise<void> {
        // Nothing to clean up
    }

    // ------------------------------------------------------------------
    // UI construction
    // ------------------------------------------------------------------
    private buildUI(): void {
        const container = this.containerEl.children[1] as HTMLElement;
        container.empty();
        container.addClass("ai-assistant-container");

        // Header bar
        const header = container.createDiv("ai-assistant-header");
        header.createEl("span", { text: "AI Assistant", cls: "ai-assistant-title" });
        this.modeEl = header.createEl("span", { cls: "ai-assistant-mode" });

        // Status bar
        this.statusEl = container.createDiv("ai-assistant-status");
        this.statusEl.setText("Connecting...");

        // Messages area
        this.messagesEl = container.createDiv("ai-assistant-messages");

        // Input area
        const inputArea = container.createDiv("ai-assistant-input-area");
        this.inputEl = inputArea.createEl("textarea", {
            attr: {
                placeholder: "Ask anything... (Enter to send, Shift+Enter for newline)",
                rows: "3",
            },
            cls: "ai-assistant-input",
        });
        this.inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            }
        });

        // Button row
        const btnRow = inputArea.createDiv("ai-assistant-btn-row");
        this.sendBtn = btnRow.createEl("button", { text: "Send", cls: "ai-assistant-send-btn" });
        this.sendBtn.addEventListener("click", () => this.handleSend());

        const clearBtn = btnRow.createEl("button", { text: "Clear", cls: "ai-assistant-clear-btn" });
        clearBtn.addEventListener("click", () => this.clearMessages());

        const statusBtn = btnRow.createEl("button", { text: "↻", cls: "ai-assistant-refresh-btn", attr: { title: "Refresh status" } });
        statusBtn.addEventListener("click", () => this.loadStatus());
    }

    // ------------------------------------------------------------------
    // Status and history loading
    // ------------------------------------------------------------------
    private async loadStatus(): Promise<void> {
        const settings = this.plugin.settings;
        const url = `http://${settings.host}:${settings.port}/status`;

        try {
            const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data: StatusResponse = await resp.json();

            const provider = data.active_provider ?? "none";
            this.statusEl.setText(`✓ Connected — ${provider.toUpperCase()} — ${data.message_count} messages this session`);
            this.statusEl.removeClass("ai-assistant-status-offline");
            this.statusEl.addClass("ai-assistant-status-online");
            this.setMode("http");
        } catch {
            this.statusEl.setText("⚡ Service offline — using vault mode");
            this.statusEl.removeClass("ai-assistant-status-online");
            this.statusEl.addClass("ai-assistant-status-offline");
            this.setMode("vault");
        }
    }

    private async loadHistory(): Promise<void> {
        const settings = this.plugin.settings;
        const url = `http://${settings.host}:${settings.port}/history`;

        try {
            const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
            if (!resp.ok) return;
            const data: HistoryResponse = await resp.json();

            if (data.messages.length === 0) return;

            // Render history as a faded "prior session" block
            const histDiv = this.messagesEl.createDiv("ai-assistant-history-header");
            histDiv.setText(`— ${data.messages.length} messages from this session —`);

            for (const msg of data.messages) {
                // Skip trimmed/collapsed messages
                if (msg.content.startsWith("[") && msg.content.endsWith("]")) continue;
                await this.appendMessage(msg.role as "user" | "assistant", msg.content, true);
            }

            this.scrollToBottom();
        } catch {
            // Service not available — that's fine, vault mode will be used
        }
    }

    // ------------------------------------------------------------------
    // Send message
    // ------------------------------------------------------------------
    private async handleSend(): Promise<void> {
        if (this.isLoading) return;
        const text = this.inputEl.value.trim();
        if (!text) return;

        this.inputEl.value = "";
        this.setLoading(true);
        await this.appendMessage("user", text);

        const mode = this.getCurrentMode();

        if (mode === "http") {
            await this.sendViaHTTP(text);
        } else {
            await this.sendViaVault(text);
        }

        this.setLoading(false);
    }

    private async sendViaHTTP(text: string): Promise<void> {
        const settings = this.plugin.settings;
        const url = `http://${settings.host}:${settings.port}/chat`;

        try {
            const resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text }),
                signal: AbortSignal.timeout(60000), // 60s — AI responses can be slow
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
                throw new Error(err.detail ?? `HTTP ${resp.status}`);
            }

            const data: ChatResponse = await resp.json();
            await this.appendMessage("assistant", data.reply);
            this.statusEl.setText(`✓ ${data.provider_used.toUpperCase()} — ${data.timestamp}`);

        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            // If HTTP failed, try falling back to vault mode
            if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("timeout")) {
                this.setMode("vault");
                await this.loadStatus();
                await this.sendViaVault(text);
            } else {
                await this.appendErrorMessage(`Error: ${msg}`);
            }
        }
    }

    private async sendViaVault(text: string): Promise<void> {
        const vault = this.app.vault;
        const settings = this.plugin.settings;
        const handshakeDir = settings.handshakeDir || "AI/Chat";
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const notePath = `${handshakeDir}/chat-${timestamp}.md`;

        // Build the frontmatter + body note
        const noteContent = [
            "---",
            `assistant-status: pending`,
            `assistant-request: "${text.replace(/"/g, '\\"')}"`,
            "---",
            "",
            `**Message sent:** ${new Date().toLocaleString()}`,
            "",
            text,
        ].join("\n");

        try {
            // Ensure the directory exists
            const dir = vault.getFolderByPath(handshakeDir);
            if (!dir) {
                await vault.createFolder(handshakeDir);
            }

            // Write the request note
            await vault.create(notePath, noteContent);

            // Show a "waiting" indicator
            const waitMsg = await this.appendWaitingMessage();

            // Poll for the response (up to 5 minutes, check every 3 seconds)
            const MAX_WAIT_MS = 5 * 60 * 1000;
            const POLL_INTERVAL_MS = 3000;
            const startTime = Date.now();

            const poll = async (): Promise<void> => {
                if (Date.now() - startTime > MAX_WAIT_MS) {
                    waitMsg.remove();
                    await this.appendErrorMessage("No response after 5 minutes. Is the watcher running?");
                    return;
                }

                const file = vault.getFileByPath(notePath);
                if (!file) {
                    setTimeout(poll, POLL_INTERVAL_MS);
                    return;
                }

                const content = await vault.read(file);

                // Check if the watcher has written a response
                if (content.includes("assistant-status: \"done\"") ||
                    content.includes("assistant-status: done") ||
                    content.includes("## Assistant Response")) {

                    // Extract the response section
                    const responseMatch = content.match(/## Assistant Response\s*\n+(?:\*\*Generated:\*\*[^\n]*\n+)?([\s\S]+?)(?:---|$)/);
                    const reply = responseMatch ? responseMatch[1].trim() : "Response received (see vault note).";

                    waitMsg.remove();
                    await this.appendMessage("assistant", reply);
                    return;
                }

                if (content.includes("assistant-status: \"error\"") ||
                    content.includes("assistant-status: error")) {
                    waitMsg.remove();
                    await this.appendErrorMessage("Watcher returned an error. Check the vault note for details.");
                    return;
                }

                setTimeout(poll, POLL_INTERVAL_MS);
            };

            setTimeout(poll, POLL_INTERVAL_MS);

        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            await this.appendErrorMessage(`Vault error: ${msg}`);
        }
    }

    // ------------------------------------------------------------------
    // Message rendering
    // ------------------------------------------------------------------
    private async appendMessage(
        role: "user" | "assistant",
        content: string,
        isHistory = false
    ): Promise<HTMLElement> {
        const msgEl = this.messagesEl.createDiv(`ai-assistant-message ai-assistant-${role}`);
        if (isHistory) msgEl.addClass("ai-assistant-history");

        const labelEl = msgEl.createEl("span", {
            text: role === "user" ? "You" : "Assistant",
            cls: "ai-assistant-label",
        });

        const bodyEl = msgEl.createDiv("ai-assistant-body");

        if (role === "assistant") {
            // Render Markdown for assistant replies
            await MarkdownRenderer.render(
                this.app,
                content,
                bodyEl,
                "",
                this
            );
        } else {
            bodyEl.setText(content);
        }

        this.scrollToBottom();
        return msgEl;
    }

    private async appendErrorMessage(text: string): Promise<void> {
        const msgEl = this.messagesEl.createDiv("ai-assistant-message ai-assistant-error");
        msgEl.createEl("span", { text: "⚠ Error", cls: "ai-assistant-label" });
        msgEl.createDiv("ai-assistant-body").setText(text);
        this.scrollToBottom();
    }

    private async appendWaitingMessage(): Promise<HTMLElement> {
        const msgEl = this.messagesEl.createDiv("ai-assistant-message ai-assistant-waiting");
        msgEl.createEl("span", { text: "Assistant", cls: "ai-assistant-label" });
        const body = msgEl.createDiv("ai-assistant-body");
        body.createEl("span", { text: "Waiting for vault watcher response", cls: "ai-assistant-waiting-text" });
        const dots = body.createEl("span", { cls: "ai-assistant-dots" });
        dots.setText("...");
        this.scrollToBottom();
        return msgEl;
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    private setLoading(loading: boolean): void {
        this.isLoading = loading;
        this.sendBtn.disabled = loading;
        this.sendBtn.setText(loading ? "..." : "Send");
        this.inputEl.disabled = loading;
    }

    private setMode(mode: "http" | "vault"): void {
        this.containerEl.setAttribute("data-mode", mode);
        this.modeEl.setText(mode === "http" ? "Live" : "Vault");
        this.modeEl.className = `ai-assistant-mode ai-assistant-mode-${mode}`;
    }

    private getCurrentMode(): "http" | "vault" {
        return (this.containerEl.getAttribute("data-mode") as "http" | "vault") ?? "vault";
    }

    private clearMessages(): void {
        this.messagesEl.empty();
    }

    private scrollToBottom(): void {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }
}
