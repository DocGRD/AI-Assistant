# AI Assistant — Quick Start Guide

## First-time setup

### 1 — Create a virtual environment (once per machine)

**Windows (PowerShell):**
```powershell
cd "C:\development\AI Assistant"
python -m venv .venv
```

**Linux / Mac:**
```bash
cd ~/assistant-core
python3 -m venv .venv
```

---

### 2 — Activate the virtual environment

You must do this every time you open a new terminal.

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

If you see a permissions error:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then try again.

**Linux / Mac:**
```bash
source .venv/bin/activate
```

You know it worked when your prompt shows `(.venv)` at the start.

---

### 3 — Install dependencies (once, or after requirements.txt changes)

```bash
pip install -r requirements.txt
```

---

### 4 — Configure settings

Edit `config/settings.json`:
- Set `vault_path` to the full path of your Obsidian vault
- Add your `groq_api_key` (free at https://console.groq.com)
- Add your `google_api_key` (free at https://aistudio.google.com/app/apikey)

Never commit this file to git — it contains API keys.
A template is at `config/settings.example.json`.

---

### 5 — Run

```bash
python assistant.py
```

---

## Every time you open a new terminal

```powershell
# Windows
cd "C:\development\AI Assistant"
.venv\Scripts\Activate.ps1
python assistant.py
```

```bash
# Linux / Mac
cd ~/assistant-core
source .venv/bin/activate
python assistant.py
```

---

## Troubleshooting

**"ModuleNotFoundError: No module named 'groq'"**
You forgot to activate the venv. Run `.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (Linux) first.

**"Settings file not found"**
You need `config/settings.json`. Copy `config/settings.example.json` and fill in your vault path and API keys.

**"✗ Vault Found" at startup**
Check that `vault_path` in `config/settings.json` is the exact path to your Obsidian vault folder. Use forward slashes or double backslashes on Windows.

**Plugin shows orange "Vault" badge**
The Python service isn't running. Start it with `python assistant.py` and refresh the plugin.

---

## Running as a Linux service (headless)

See `AI/System/watcher.service` in your vault for the full systemd setup.
Quick version:
```bash
sudo cp watcher.service /etc/systemd/system/ai-assistant.service
# Edit the paths inside the file first
sudo systemctl enable --now ai-assistant
sudo systemctl status ai-assistant
```
