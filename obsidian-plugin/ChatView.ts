import { ItemView, WorkspaceLeaf, MarkdownRenderer } from "obsidian";
import type AIAssistantPlugin from "./main";

export const CHAT_VIEW_TYPE = "ai-assistant-chat";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type ChatMode      = "normal" | "handoff-awaiting-response";
// Provider keys are no longer a fixed union — the dropdown is populated from the
// service's /status endpoint, which is itself driven by Provider-Registry.md.
// "auto" means smart routing (no override).

interface HandoffResponse {
    status:               "ok" | "handoff_required";
    reply:                string;
    provider_used:        string;
    actual_provider:      string;
    timestamp:            string;
    prompt_to_copy?:      string;
    vault_actions_taken?: string[];   // commands executed from web AI suggestions
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
    private selectedProvider            = "auto";
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
        this.buildProviderBar();

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

        this.providerEl.createEl("span", { text: "Provider", cls: "ai-assistant-provider-label" });

        const select = this.providerEl.createEl("select", { cls: "ai-assistant-provider-select" });
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
    private async sendViaHTTP(text: string, forceAllowWebui = false): Promise<void> {
        const { host, port } = this.plugin.settings;
        try {
            const resp = await fetch(`http://${host}:${port}/chat`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({
                    message:           text,
                    provider_override: this.selectedProvider === "auto" ? null : this.selectedProvider,
                    private:                 this.isPrivate,
                    allow_webui_on_private:  this.isPrivate && (this.allowWebuiOnPrivate || forceAllowWebui),
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
            // M10 — carry the privacy flags into the watcher path.
            ...(this.isPrivate ? [`private: true`] : []),
            ...(this.isPrivate && this.allowWebuiOnPrivate ? [`allow-webui: true`] : []),
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
                method: "POST",
                headers: { "Content-Type": "application/json" },
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
        this.updateSendButton();
        this.updateInputPlaceholder();
        this.messagesEl.empty();
        this.focusInput();    // BUG-005
    }

    private scrollToBottom(): void {
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }
}
