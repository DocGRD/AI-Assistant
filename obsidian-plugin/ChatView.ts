import { ItemView, WorkspaceLeaf, MarkdownRenderer } from "obsidian";
import type AIAssistantPlugin from "./main";

export const CHAT_VIEW_TYPE = "ai-assistant-chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type ChatMode      = "normal" | "handoff-awaiting-response";
type ProviderChoice = "auto" | "groq" | "google" | "webui";

interface HandoffResponse {
    status:          "ok" | "handoff_required";
    reply:           string;
    provider_used:   string;
    actual_provider: string;
    timestamp:       string;
    prompt_to_copy?: string;
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
    private selectedProvider: ProviderChoice = "auto";
    private pendingHandoffUserMessage   = "";
    private serviceOnline               = false;

    constructor(leaf: WorkspaceLeaf, plugin: AIAssistantPlugin) {
        super(leaf);
        this.plugin = plugin;
    }

    getViewType():    string { return CHAT_VIEW_TYPE; }
    getDisplayText(): string { return "AI Assistant"; }
    getIcon():        string { return "bot"; }

    async onOpen(): Promise<void> {
        this.buildUI();
        await this.loadStatus();
        await this.loadHistory();
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

        const header = container.createDiv("ai-assistant-header");
        header.createEl("span", { text: "AI Assistant", cls: "ai-assistant-title" });
        this.modeEl = header.createEl("span", { cls: "ai-assistant-mode" });

        this.providerEl = container.createDiv("ai-assistant-provider-bar");
        this.buildProviderToggle();

        this.statusEl = container.createDiv("ai-assistant-status");
        this.statusEl.setText("Connecting...");

        this.messagesEl = container.createDiv("ai-assistant-messages");

        const inputArea = container.createDiv("ai-assistant-input-area");
        this.inputEl    = inputArea.createEl("textarea", {
            attr: { rows: "3" },
            cls:  "ai-assistant-input",
        });
        this.updateInputPlaceholder();
        this.inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            }
        });

        const btnRow    = inputArea.createDiv("ai-assistant-btn-row");
        this.sendBtn    = btnRow.createEl("button", { cls: "ai-assistant-send-btn" });
        this.updateSendButton();
        this.sendBtn.addEventListener("click", () => this.handleSend());

        const clearBtn = btnRow.createEl("button", { text: "Clear", cls: "ai-assistant-clear-btn" });
        clearBtn.addEventListener("click", () => this.clearMessages());

        const refreshBtn = btnRow.createEl("button", {
            text: "↻",
            cls:  "ai-assistant-refresh-btn",
            attr: { title: "Refresh status" },
        });
        refreshBtn.addEventListener("click", () => this.loadStatus());

        const shutdownBtn = btnRow.createEl("button", {
            text: "⏻",
            cls:  "ai-assistant-shutdown-btn",
             attr: { title: "Shut down the assistant service" },
        });
        shutdownBtn.addEventListener("click", () => this.shutdownService());
    }

    private buildProviderToggle(): void {
        this.providerEl.empty();
        const providers: ProviderChoice[] = ["auto", "groq", "google", "webui"];
        const labels: Record<ProviderChoice, string> = {
            auto: "Auto", groq: "Groq", google: "Gemini", webui: "Web UI",
        };
        providers.forEach(p => {
            const btn = this.providerEl.createEl("button", {
                text: labels[p],
                cls:  `ai-assistant-provider-btn${p === this.selectedProvider ? " active" : ""}`,
                attr: { "data-provider": p },
            });
            btn.addEventListener("click", () => {
                this.selectedProvider = p;
                this.buildProviderToggle();
                this.updateInputPlaceholder();
                // BUG-005: keep focus after clicking a provider button
                this.focusInput();
            });
        });
    }

    // ------------------------------------------------------------------
    // Status and history loading
    // ------------------------------------------------------------------
    private async loadStatus(): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/status`, {
                signal: AbortSignal.timeout(3000),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data: StatusResponse = await resp.json();
            const provider = data.active_provider ?? "none";
            this.statusEl.setText(`✓ Connected — ${provider.toUpperCase()} — ${data.message_count} messages`);
            this.statusEl.className = "ai-assistant-status ai-assistant-status-online";
            this.serviceOnline      = true;
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

        this.inputEl.value = "";
        this.setLoading(true);

        if (this.chatMode === "normal") {
            await this.appendMessage("user", text);
            if (this.serviceOnline) {
                await this.sendViaHTTP(text);
            } else {
                await this.sendViaVault(text);
            }
        } else {
            await this.submitHandoffReturn(text);
        }

        this.setLoading(false);
        // BUG-005: restore focus after every send cycle completes
        this.focusInput();
    }

    // ------------------------------------------------------------------
    // HTTP send
    // ------------------------------------------------------------------
    private async sendViaHTTP(text: string): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/chat`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({
                    message:           text,
                    provider_override: this.selectedProvider === "auto" ? null : this.selectedProvider,
                }),
                signal: AbortSignal.timeout(60000),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
                throw new Error(err.detail ?? `HTTP ${resp.status}`);
            }

            const data: HandoffResponse = await resp.json();

            if (data.status === "handoff_required" && data.prompt_to_copy) {
                this.enterHandoffMode(text, data.prompt_to_copy);
                return;
            }

            await this.appendMessage("assistant", data.reply);
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

        const noteContent = [
            "---",
            `assistant-status: pending`,
            `assistant-request: "${text.replace(/"/g, '\\"')}"`,
            "---",
            "",
            `**Sent:** ${new Date().toLocaleString()}`,
            "",
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

        const copyBtn = body.createEl("button", { text: "📋 Copy Prompt", cls: "ai-assistant-copy-btn" });
        copyBtn.addEventListener("click", async () => {
            await navigator.clipboard.writeText(promptToCopy);
            copyBtn.setText("✓ Copied!");
            setTimeout(() => copyBtn.setText("📋 Copy Prompt"), 2000);
            // BUG-005: return focus after clicking copy
            this.focusInput();
        });

        const preview = body.createEl("pre", { cls: "ai-assistant-handoff-preview" });
        preview.setText(promptToCopy.slice(0, 300) + (promptToCopy.length > 300 ? "\n..." : ""));

        this.scrollToBottom();
        // BUG-005: move focus to input so user can immediately paste
        this.focusInput();
    }

    private async submitHandoffReturn(pastedText: string): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/chat/handoff-return`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ response_text: pastedText }),
                signal:  AbortSignal.timeout(10000),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            this.chatMode                  = "normal";
            this.pendingHandoffUserMessage = "";
            this.containerEl.setAttribute("data-chat-mode", "normal");
            this.updateSendButton();
            this.updateInputPlaceholder();

            await this.appendMessage("assistant", pastedText);
            this.statusEl.setText("✓ Web handoff complete");
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
            await MarkdownRenderer.render(this.app, content, bodyEl, "", this);
        } else {
            bodyEl.setText(content);
        }

        this.scrollToBottom();
        // BUG-005: re-focus input after every message render
        if (!isHistory) {
            this.focusInput();
        }
        return msgEl;
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

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

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
        if (this.isLoading)                               this.sendBtn.setText("...");
        else if (this.chatMode === "handoff-awaiting-response") this.sendBtn.setText("Return Response");
        else                                              this.sendBtn.setText("Send");
    }

    private updateInputPlaceholder(): void {
        if (this.chatMode === "handoff-awaiting-response")
            this.inputEl.placeholder = "Paste web AI response here...";
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
        this.updateSendButton();
        this.updateInputPlaceholder();
        this.messagesEl.empty();
        this.focusInput();    // BUG-005
    }

    private scrollToBottom(): void {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }

    private async shutdownService(): Promise<void> {
        const { host, port } = this.plugin.settings;
        const confirmed = confirm(
            "Shut down the AI Assistant service?\n\n" +
            "The watcher and HTTP server will stop. " +
            "You will need to restart assistant.py manually."
        );
        if (!confirmed) return;

        try {
            await fetch(`http://${host}:${port}/shutdown`, {
                signal: AbortSignal.timeout(5000),
            });
            this.statusEl.setText("⏻ Service shut down");
            this.statusEl.className = "ai-assistant-status ai-assistant-status-offline";
            this.serviceOnline = false;
            this.setConnectMode("vault");
        } catch {
            // Service may have shut down before responding — that's fine
            this.statusEl.setText("⏻ Shutdown sent");
            this.statusEl.className = "ai-assistant-status ai-assistant-status-offline";
            this.serviceOnline = false;
            this.setConnectMode("vault");
        }
    }

}
