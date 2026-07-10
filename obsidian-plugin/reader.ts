// ---------------------------------------------------------------------------
// v1.7 — Read-aloud (TTS). Pure Web Speech API (window.speechSynthesis): zero-cost,
// on-device, offline, private — audio never leaves the machine. Speaks one sentence per
// utterance so we always know the active sentence (for follow-along highlighting), with a
// live speed control and an OS voice picker, driven by a floating control bar.
// ---------------------------------------------------------------------------
import { Editor, Notice } from "obsidian";

export interface ReaderSettings { speed: number; voiceName: string; }

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

/** Split text into sentence ranges (offsets into the ORIGINAL text, so a note highlight
 *  stays valid even though we speak a markdown-stripped version). */
function sentenceRanges(text: string): { start: number; end: number }[] {
    const out: { start: number; end: number }[] = [];
    const re = /[.!?]+[)"'\]]*\s+|\n{2,}/g;
    let start = 0, m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
        const end = m.index + m[0].length;
        if (text.slice(start, end).trim()) out.push({ start, end });
        start = end;
    }
    if (text.slice(start).trim()) out.push({ start, end: text.length });
    return out;
}

/** Markdown → clean speech text. */
function speechText(md: string): string {
    return md
        .replace(/```[\s\S]*?```/g, " ")
        .replace(/`([^`]*)`/g, "$1")
        .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
        .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/\[\[([^\]|]*\|)?([^\]]*)\]\]/g, "$2")
        .replace(/^\s{0,3}#{1,6}\s*/gm, "")
        .replace(/^\s*>+\s?/gm, "")
        .replace(/^\s*[-*+]\s+/gm, "")
        .replace(/[*_~]{1,3}/g, "")
        .replace(/\s+/g, " ")
        .trim();
}

export class Reader {
    // Web Speech may be absent (e.g. Obsidian's Android WebView). Keep this optional and guard
    // every use so a missing API can never throw during plugin load. (Bug: eager getVoices() in
    // the constructor crashed onload on Android, so the whole plugin failed to load.)
    private synth: SpeechSynthesis | undefined =
        (typeof window !== "undefined" && "speechSynthesis" in window) ? window.speechSynthesis : undefined;
    private ranges: { start: number; end: number }[] = [];
    private full = "";
    private idx = 0;
    private editorBase = 0;      // offset of the read text within the editor (for selections)
    private editor: Editor | null = null;
    private el: HTMLElement | null = null;      // chat bubble being read (whole-element highlight)
    private bar: HTMLElement | null = null;
    private voices: SpeechSynthesisVoice[] = [];
    // v1.9.3 — server-audio fallback for platforms without Web Speech (Android WebView).
    private audio: HTMLAudioElement | null = null;
    private mode: "web" | "audio" = "web";

    constructor(private settings: ReaderSettings, private save: () => void,
                private ttsFetch?: (text: string) => Promise<Blob | null>) {
        if (this.synth) {
            const load = () => { this.voices = this.synth?.getVoices() ?? []; };
            try { load(); } catch { /* getVoices can throw on some WebViews */ }
            this.synth.addEventListener?.("voiceschanged", load);
        }
    }

    /** True when the browser has a usable Web Speech engine (desktop; false on Android WebView). */
    private get webAvailable(): boolean {
        return !!this.synth && typeof SpeechSynthesisUtterance !== "undefined";
    }

    /** True when read-aloud can run at all — Web Speech, or the server-audio fallback. */
    get available(): boolean {
        return this.webAvailable || !!this.ttsFetch;
    }

    // --- public entry points --------------------------------------------------
    readNote(editor: Editor): void {
        const sel = editor.getSelection();
        const text = sel && sel.trim() ? sel : editor.getValue();
        if (!text.trim()) { new Notice("Nothing to read."); return; }
        if (this.webAvailable) {
            // when reading a selection, offsets are relative to the selection start
            this.editor = editor; this.el = null;
            this._start(text, sel && sel.trim() ? editor.posToOffset(editor.getCursor("from")) : 0);
        } else if (this.ttsFetch) {
            void this._startAudio(text);
        } else {
            new Notice("Read-aloud isn't available on this device.");
        }
    }

    readText(text: string, el?: HTMLElement): void {
        if (!text.trim()) return;
        if (this.webAvailable) {
            this.editor = null; this.el = el ?? null;
            this.el?.addClass("ai-assistant-reading");
            this._start(text, 0);
        } else if (this.ttsFetch) {
            void this._startAudio(text);
        } else {
            new Notice("Read-aloud isn't available on this device.");
        }
    }

    stop(): void {
        this.synth?.cancel();
        if (this.audio) {
            this.audio.pause();
            if (this.audio.src.startsWith("blob:")) URL.revokeObjectURL(this.audio.src);
            this.audio = null;
        }
        this.idx = this.ranges.length;
        this._clearHighlight();
        this.bar?.remove(); this.bar = null;
        this.mode = "web";
    }

    // --- server-audio path (Android): synthesize on the box, play via <audio> ------------
    private async _startAudio(text: string): Promise<void> {
        this.stop();
        this.mode = "audio";
        const notice = new Notice("Synthesizing audio…", 0);
        let blob: Blob | null = null;
        try { blob = await this.ttsFetch!(text); } catch { /* handled below */ }
        notice.hide();
        if (!blob || !blob.size) {
            this.mode = "web";
            new Notice("Read-aloud needs the Loremaster service reachable (no audio returned).");
            return;
        }
        const audio = new Audio(URL.createObjectURL(blob));
        this.audio = audio;
        audio.playbackRate = this.settings.speed || 1;
        audio.onended = () => this.stop();
        this._ensureBar();
        void audio.play();
    }

    // --- engine ---------------------------------------------------------------
    private _start(text: string, editorBase: number): void {
        this.synth?.cancel();
        this.full = text;
        this.ranges = sentenceRanges(text);
        this.idx = 0;
        this.editorBase = editorBase;
        this._ensureBar();
        this._speakCurrent();
    }

    private _speakCurrent(): void {
        if (this.idx < 0) this.idx = 0;
        if (this.idx >= this.ranges.length) { this.stop(); return; }
        const r = this.ranges[this.idx];
        const say = speechText(this.full.slice(r.start, r.end));
        if (!say) { this.idx++; this._speakCurrent(); return; }
        const u = new SpeechSynthesisUtterance(say);
        u.rate = this.settings.speed;
        const v = this.voices.find(x => x.name === this.settings.voiceName);
        if (v) u.voice = v;
        u.onstart = () => this._highlight(r);
        u.onend = () => { if (this.idx < this.ranges.length) { this.idx++; this._speakCurrent(); } };
        this.synth?.speak(u);
    }

    private _restartFromCurrent(): void {
        this.synth?.cancel();
        this._speakCurrent();
    }

    private _highlight(r: { start: number; end: number }): void {
        if (this.editor) {
            const base = this.editorBase || 0;
            try {
                const from = this.editor.offsetToPos(base + r.start);
                const to = this.editor.offsetToPos(base + r.end);
                this.editor.setSelection(from, to);
                this.editor.scrollIntoView({ from, to }, true);
            } catch { /* offset out of range — ignore */ }
        }
        // (chat bubbles use a whole-element highlight set in readText)
    }

    private _clearHighlight(): void {
        this.el?.removeClass("ai-assistant-reading");
    }

    // --- floating control bar -------------------------------------------------
    private _ensureBar(): void {
        this.bar?.remove();
        const bar = document.body.createDiv("ai-assistant-reader-bar");
        this.bar = bar;
        const mkBtn = (txt: string, aria: string, fn: () => void) => {
            const b = bar.createEl("button", { text: txt, attr: { "aria-label": aria } });
            b.addEventListener("click", fn); return b;
        };
        bar.createEl("span", { text: "🔊", cls: "ai-assistant-reader-icon" });

        // Server-audio mode (Android): a single <audio> element — Play/Pause, Stop, Speed.
        // No per-sentence controls or voice picker (those are Web-Speech-only).
        if (this.mode === "audio") {
            const playPause = mkBtn("⏸", "Pause / resume", () => {
                if (!this.audio) return;
                if (this.audio.paused) { void this.audio.play(); playPause.setText("⏸"); }
                else { this.audio.pause(); playPause.setText("▶"); }
            });
            mkBtn("⏹", "Stop", () => this.stop());
            const aspeed = bar.createEl("select", { cls: "ai-assistant-reader-speed" });
            for (const s of SPEEDS) {
                const o = aspeed.createEl("option", { text: `${s}×`, value: String(s) });
                if (s === this.settings.speed) o.selected = true;
            }
            aspeed.addEventListener("change", () => {
                this.settings.speed = parseFloat(aspeed.value); this.save();
                if (this.audio) this.audio.playbackRate = this.settings.speed;
            });
            return;
        }

        mkBtn("⏮", "Previous sentence", () => { this.idx = Math.max(0, this.idx - 1); this._restartFromCurrent(); });
        const playPause = mkBtn("⏸", "Pause / resume", () => {
            if (this.synth?.paused) { this.synth.resume(); playPause.setText("⏸"); }
            else if (this.synth?.speaking) { this.synth.pause(); playPause.setText("▶"); }
            else { this._speakCurrent(); playPause.setText("⏸"); }
        });
        mkBtn("⏭", "Next sentence", () => { this.idx = Math.min(this.ranges.length - 1, this.idx + 1); this._restartFromCurrent(); });
        mkBtn("⏹", "Stop", () => this.stop());

        const speed = bar.createEl("select", { cls: "ai-assistant-reader-speed" });
        for (const s of SPEEDS) {
            const o = speed.createEl("option", { text: `${s}×`, value: String(s) });
            if (s === this.settings.speed) o.selected = true;
        }
        speed.addEventListener("change", () => {
            this.settings.speed = parseFloat(speed.value); this.save();
            this._restartFromCurrent();     // apply new rate to the current sentence onward
        });

        if (this.voices.length) {
            const voice = bar.createEl("select", { cls: "ai-assistant-reader-voice" });
            voice.createEl("option", { text: "Default voice", value: "" });
            for (const v of this.voices) {
                const o = voice.createEl("option", { text: v.name, value: v.name });
                if (v.name === this.settings.voiceName) o.selected = true;
            }
            voice.addEventListener("change", () => {
                this.settings.voiceName = voice.value; this.save();
                this._restartFromCurrent();
            });
        }
    }
}
