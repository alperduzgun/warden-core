# 🚀 Warden Core Quickstart Guide

**Zero to Hero in 2 Minutes.**

Transform your AI-generated code from "Wild West" to "Production Ready".

---

## 1. Installation

**Prerequisites:** Python 3.9+

```bash
pip install warden-core
```

---

## 2. Initialization (The Most Important Step)

Initialize Warden in your project root. This converts a standard repo into an "AI-Guarded Zone".

```bash
# Detects project type, creates configs, and sets up AI Hooks
warden init
```

**What this does:**
1.  Creates `.warden/` configuration directory.
2.  Generates `.warden/AI_RULES.md` ( The Protocol).
3.  **Injects hooks** into your AI Agent (e.g. Claude Code) to ensure it *reads* the rules automatically.
4.  Interactively configures your LLM (Claude, Ollama, etc.).

---

## 3. Switching Intelligence (LLM)

Warden supports multiple brains. The default is chosen during `warden init`.
To switch later, use the `config set` command.

### Option A: I use Claude Code (Recommended)
If you already use the `claude` CLI tool, Warden plugs into it seamlessly. **Zero API costs.**

```bash
# Note: Use 'claude_code' with an underscore
warden config set llm.provider claude_code
```

### Option B: I want 100% Offline/Private (Ollama)
Use your local GPU. Perfect for privacy and speed.

```bash
# 1. Install Ollama & Pull Model
ollama pull qwen2.5-coder:7b

# 2. Configure Warden
warden config set llm.provider ollama
```

### Option C: Cloud API (OpenAI / Anthropic / Gemini)
To switch to a cloud provider:

```bash
# 1. Set Provider
warden config set llm.provider anthropic  # or openai, gemini

# 2. Add API Key to .env
# echo "ANTHROPIC_API_KEY=sk-..." >> .env
```

Tip: Check your configuration with `warden config list`.

---

## 4. Run Your First Scan

Validate your codebase.

```bash
warden scan
```

**Understanding the Output:**
- 🟢 **PASS:** Code meets all architectural and safety rules.
- 🔴 **FAIL:** Warden blocks the change. AI must fix issues.
- **Quality Score:** 0-10 rating of your codebase hygiene.

---

## 5. The "Verify-Loop" Workflow

When working with AI:

1.  **Ask AI to Code:** "Create a new user profile API."
2.  **AI Implements:** (Writes code...)
3.  **You Run Warden:**
    ```bash
    # Scan only what changed (Fast!)
    warden scan --diff
    ```
4.  **Feedback:** If it fails, paste the error back to the AI: *"Warden rejected this. Fix the Security Finding on line 42."*
5.  **Pass:** Commit confidently.

---

## 6. Optimization Tips

- **Incremental Scans:** Use `warden scan --diff` to check only your active changes (Seconds vs Minutes).
- **Smart Baseline:** Use `warden scan --diff --baseline` to ignore legacy debt and focus on *new* bugs.
- **Diagnostics:** If something feels wrong, run the doctor:
  ```bash
  warden doctor
  ```

---

**Need more?**
Run `warden --help` or see the [README.md](./README.md) for advanced configuration.
