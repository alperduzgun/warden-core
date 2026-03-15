# LLM Provider Configuration Guide

Warden supports multiple LLM providers for AI-powered code analysis. This guide covers how to set up, configure, and troubleshoot each provider.

## Overview

Warden uses a two-tier model system:

- **Smart tier** — the primary provider for deep analysis (complex reasoning tasks)
- **Fast tier** — lightweight provider(s) for classification and pre-analysis (speed-sensitive tasks)

Both tiers can be configured independently, allowing you to mix providers (e.g., Groq for smart analysis, Ollama for fast local classification).

### Supported Providers

| Provider | Type | API Key Required | CI/CD Support | Default Model |
|---|---|---|---|---|
| Ollama | Local | No | Yes (self-hosted) | `qwen2.5-coder:7b` |
| OpenAI | Cloud | Yes | Yes | `gpt-4o` |
| Anthropic | Cloud | Yes | Yes | `claude-3-5-sonnet-20241022` |
| Azure OpenAI | Cloud | Yes | Yes | deployment name |
| Gemini | Cloud | Yes | Yes | `gemini-1.5-flash` |
| Groq | Cloud | Yes | Yes | `llama-3.3-70b-versatile` |
| DeepSeek | Cloud | Yes | Yes | `deepseek-coder` |
| QwenCode | Cloud | Yes | Yes | `qwen2.5-coder-32b-instruct` |
| Claude Code | Local CLI | No | No | managed by `claude config` |
| Codex | Local CLI | No | No | managed by `~/.codex/config.toml` |

---

## Provider Setup

### Ollama (Local, Free)

Ollama runs models entirely on your machine — no API key, no cost, no data leaving your network.

**Installation:**

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

**Start the Ollama server:**

```bash
ollama serve
```

**Pull a model:**

```bash
# Recommended for smart tier (balance of quality and speed)
ollama pull qwen2.5-coder:7b

# Lightweight for fast tier (CPU-friendly)
ollama pull qwen2.5-coder:3b
ollama pull qwen2.5-coder:0.5b
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: ollama
  smart_model: qwen2.5-coder:7b
  fast_model: qwen2.5-coder:0.5b
  fast_tier_providers:
    - ollama
```

**Custom endpoint** (if Ollama runs on a different host):

```bash
export OLLAMA_HOST=http://192.168.1.100:11434
```

> Warden validates the `OLLAMA_HOST` value at startup and blocks cloud metadata service addresses (169.254.x.x) to prevent SSRF.

**Verify Ollama is running:**

```bash
warden config llm test
```

---

### OpenAI

**Get an API key:** https://platform.openai.com/api-keys

**Set the environment variable:**

```bash
export OPENAI_API_KEY=sk-...
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: openai
  smart_model: gpt-4o
  fast_model: gpt-4o-mini
  fast_tier_providers:
    - ollama   # Use Ollama locally for fast tier
```

**Available models:**

- `gpt-4o` — Best quality, higher cost
- `gpt-4o-mini` — Cost-effective, fast
- `o1-preview` / `o1-mini` — Reasoning-focused

**Cost considerations:** OpenAI charges per token. For large codebases, pair OpenAI (smart tier) with Ollama (fast tier) to reduce cost. Rate limit defaults (`tpm_limit`, `rpm_limit`) help stay within free-tier quotas — adjust them for paid plans.

---

### Anthropic / Claude

**Get an API key:** https://console.anthropic.com/

**Set the environment variable:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: anthropic
  smart_model: claude-sonnet-4-20250514
```

**Available models:**

- `claude-sonnet-4-20250514` — Recommended, best balance of speed and quality
- `claude-opus-4-5-20251001` — Highest reasoning capability
- `claude-haiku-3-5-20251022` — Fastest, most cost-efficient
- `claude-3-5-sonnet-20241022` — Previous generation, still supported

**Prompt caching:** The Anthropic provider supports Anthropic's prompt caching API. Warden automatically attaches `cache_control` headers to the stable system context portion of prompts, reducing cost and latency for repeated scans.

---

### Azure OpenAI

Azure OpenAI is Warden's default cloud provider for enterprise deployments. It requires three environment variables.

**Set the environment variables:**

```bash
export AZURE_OPENAI_API_KEY=your-azure-api-key
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name

# Optional: override API version (default: 2024-02-01)
export AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: azure_openai
  smart_model: your-deployment-name   # Use deployment name, not model name
```

The `AZURE_OPENAI_DEPLOYMENT_NAME` value is used as the model identifier. All three required variables (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`) must be present for Azure to be auto-detected.

---

### Google Gemini

**Get an API key:** https://aistudio.google.com/

**Set the environment variable:**

```bash
export GEMINI_API_KEY=your-gemini-api-key
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: gemini
  smart_model: gemini-1.5-pro
```

**Available models:**

- `gemini-1.5-flash` — Default, fast and cost-efficient
- `gemini-1.5-pro` — Higher quality, larger context window
- `gemini-2.0-flash` — Latest generation, faster

---

### Groq

Groq provides hardware-accelerated inference with very low latency — an excellent choice for CI/CD pipelines.

**Get an API key:** https://console.groq.com/

**Set the environment variable:**

```bash
export GROQ_API_KEY=gsk_...
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: groq
  smart_model: llama-3.3-70b-versatile
```

**Available models:**

- `llama-3.3-70b-versatile` — Default, strong reasoning
- `llama-3.1-8b-instant` — Fastest, minimal latency
- `mixtral-8x7b-32768` — Large context window

**CI/CD recommendation:** Groq's free tier is generous and inference is fast enough for short-lived CI runners. Set it as the CI provider:

```yaml
llm:
  ci:
    provider: groq
    smart_model: llama-3.3-70b-versatile
    fast_tier_providers:
      - groq
    fast_model: llama-3.1-8b-instant
```

---

### DeepSeek

DeepSeek offers a cost-effective API with strong code understanding capabilities.

**Get an API key:** https://platform.deepseek.com/

**Set the environment variable:**

```bash
export DEEPSEEK_API_KEY=your-deepseek-api-key
```

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: deepseek
  smart_model: deepseek-coder
```

**Available models:**

- `deepseek-coder` — Default, optimized for code
- `deepseek-chat` — General purpose

---

### Claude Code (Local CLI)

Claude Code uses your existing Claude subscription via the `claude` CLI — no separate API key needed.

**Prerequisites:**

- Install Claude Code: https://docs.anthropic.com/claude/docs/claude-code
- Authenticate: `claude auth login`

**Auto-detection:** Warden automatically detects a working `claude` binary at startup. No manual configuration is required if `claude` is in your `PATH`.

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: claude_code
```

**Model selection:** Claude Code manages model selection internally. Use `claude config` to switch between Sonnet, Opus, and Haiku.

> Claude Code is a local CLI tool and is not available in CI/CD runners. Warden filters it from CI provider selections automatically.

**Single-tier behavior:** When Claude Code is the primary provider, the fast tier is disabled. Claude Code manages its own model routing internally.

---

### Codex (Local CLI)

The Codex provider integrates with the OpenAI Codex CLI for local, file-based analysis.

**Prerequisites:**

- Install Codex CLI and authenticate per the Codex CLI documentation
- Verify installation: `codex --version`

**Auto-detection:** Warden automatically detects a working `codex` binary. No manual configuration is required.

**Configure Warden:**

```yaml
# .warden/config.yaml
llm:
  provider: codex
```

> Like Claude Code, Codex is a local-only provider not available in CI/CD environments. Single-tier mode applies.

---

## Configuration Methods

There are three ways to configure the LLM provider, applied in this precedence order (highest wins):

1. **Environment variable** (`WARDEN_LLM_PROVIDER`)
2. **`.warden/config.yaml`** (`llm.provider`)
3. **Auto-detection** (Warden detects available providers at startup)

### warden.yaml / .warden/config.yaml Fields

All LLM settings live under the `llm:` key:

```yaml
llm:
  # Primary provider for smart (deep analysis) tier
  provider: ollama

  # Model for smart tier
  smart_model: qwen2.5-coder:7b

  # Model for fast tier (classification, pre-analysis)
  fast_model: qwen2.5-coder:0.5b

  # Providers used for the fast tier (in priority order)
  fast_tier_providers:
    - ollama

  # Route smart-tier requests to a specific provider
  # (e.g., use Groq for deep analysis while Ollama handles fast)
  smart_tier_provider: groq
  smart_tier_model: llama-3.3-70b-versatile

  # Rate limiting (see Advanced section)
  tpm_limit: 10000
  rpm_limit: 60

  # Per-category token budgets
  token_budgets:
    security: {deep: 400, fast: 300}
    resilience: {deep: 400, fast: 300}

  # CI/CD override block — merged when CI=true or GITHUB_ACTIONS=true
  ci:
    provider: groq
    smart_model: llama-3.3-70b-versatile
    fast_tier_providers:
      - groq
    fast_model: llama-3.1-8b-instant
```

### Environment Variables

| Variable | Description | Example |
|---|---|---|
| `WARDEN_LLM_PROVIDER` | Override the active provider | `groq` |
| `WARDEN_SMART_MODEL` | Override the smart-tier model | `gpt-4o` |
| `WARDEN_FAST_MODEL` | Override the fast-tier model | `qwen2.5-coder:3b` |
| `WARDEN_FAST_TIER_PRIORITY` | Comma-separated fast tier providers | `groq,ollama` |
| `WARDEN_SMART_TIER_PROVIDER` | Route smart calls to a specific provider | `groq` |
| `WARDEN_SMART_TIER_MODEL` | Model for the smart-tier provider override | `llama-3.3-70b-versatile` |
| `WARDEN_LLM_CONCURRENCY` | Global max concurrent LLM requests | `4` |
| `WARDEN_BLOCKED_PROVIDERS` | Comma-separated providers to disable | `claude_code` |
| `OLLAMA_HOST` | Custom Ollama endpoint | `http://localhost:11434` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | — |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | `https://...openai.azure.com/` |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Azure deployment name | `gpt-4o-deployment` |
| `AZURE_OPENAI_API_VERSION` | Azure API version | `2024-02-01` |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `GROQ_API_KEY` | Groq API key | `gsk_...` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |

### CLI: `warden config llm`

Warden provides dedicated CLI subcommands for managing LLM configuration without editing YAML manually.

**View current configuration:**

```bash
warden config llm status
```

Output shows the active smart and fast providers, models, and health status.

**Set the smart (primary) provider:**

```bash
# Use Ollama
warden config llm smart ollama

# Use Anthropic with a specific model
warden config llm smart anthropic --model claude-sonnet-4-20250514

# Use Groq
warden config llm smart groq
```

**Set the fast tier provider:**

```bash
# Use Ollama for fast tier
warden config llm fast ollama

# Use Ollama with a specific lightweight model
warden config llm fast ollama --model qwen2.5-coder:0.5b

# Disable fast tier
warden config llm fast none
```

**Open the interactive TUI editor** (configures local and CI/CD providers in one step):

```bash
warden config llm edit
```

**Test the active provider:**

```bash
warden config llm test
```

**Quick provider switch** (updates provider and default models together):

```bash
warden config set llm.provider groq
```

---

## Advanced Configuration

### Rate Limiting

Warden enforces per-provider rate limits to stay within API quotas. The global rate limiter applies to all providers.

```yaml
llm:
  tpm_limit: 10000   # Tokens per minute (default: 1000 for free tiers)
  rpm_limit: 60      # Requests per minute (default: 6 for free tiers)
```

Raise these values for paid API tiers:

```yaml
llm:
  tpm_limit: 1000000   # 1M TPM for paid OpenAI/Anthropic
  rpm_limit: 500
```

For CI pipelines where you want to run fast without throttling:

```bash
export WARDEN_LLM_PROVIDER=groq
# Then in config.yaml, set generous limits in the ci: block
```

### Timeout Configuration

The default LLM request timeout is 90 seconds per request. For slow hardware running Ollama locally, increase the timeout via the config:

```yaml
llm:
  timeout: 300   # 5 minutes, useful for large models on CPU
```

Ollama streaming timeouts are calibrated automatically at startup based on a speed benchmark of your hardware. This prevents timeout failures on slow CPUs without manual tuning.

### Token Budgets

Token budgets control the maximum output tokens Warden allocates per analysis category and tier:

```yaml
llm:
  token_budgets:
    security: {deep: 400, fast: 300}
    resilience: {deep: 400, fast: 300}
    property: {deep: 300, fast: 200}
    fuzz: {deep: 300, fast: 200}
    orphan: {deep: 500, fast: 400}
    triage: {deep: 400, fast: 400}
    classification: {deep: 400, fast: 400}
```

Tighter budgets reduce cost and improve latency on local models. Increase them if analysis results appear truncated.

### Dual-Tier (Hybrid) Setup

Route intensive analysis to a capable cloud model while keeping classification local:

```yaml
llm:
  provider: anthropic
  smart_model: claude-sonnet-4-20250514

  # Ollama handles fast classification locally
  fast_tier_providers:
    - ollama
  fast_model: qwen2.5-coder:0.5b
```

Or route smart calls to Groq while keeping Ollama as fast tier:

```yaml
llm:
  provider: ollama
  smart_model: qwen2.5-coder:7b
  fast_tier_providers:
    - ollama
  fast_model: qwen2.5-coder:0.5b

  smart_tier_provider: groq
  smart_tier_model: llama-3.3-70b-versatile
```

Alternatively, use the environment variable approach:

```bash
export WARDEN_SMART_TIER_PROVIDER=groq
export WARDEN_SMART_TIER_MODEL=llama-3.3-70b-versatile
export WARDEN_FAST_TIER_PRIORITY=ollama
```

### Blocking Providers

To prevent a specific provider from being used (e.g., block CLI tools in CI):

```bash
export WARDEN_BLOCKED_PROVIDERS=claude_code,codex
```

This is applied after all other configuration, so it always wins regardless of config.yaml settings.

### Concurrency

Control how many LLM requests run in parallel:

```yaml
# Global limit across all providers
llm:
  max_concurrency: 4
```

Per-provider concurrency is set in the provider config block (advanced use case, edit config.yaml directly):

```yaml
llm:
  openai:
    concurrency: 8
```

### Fallback Chain

Warden builds a fallback chain from all configured providers. If the primary provider fails, requests are retried against fallback providers in order.

The chain is constructed automatically based on which providers have valid credentials. You can observe the resolved chain:

```bash
warden config llm status
```

To explicitly set fallback behavior, configure multiple providers and let Warden order them by detected credentials.

---

## Troubleshooting

### Ollama: "Model not found"

```
Error: Model 'qwen2.5-coder:7b' not found. Run 'ollama pull qwen2.5-coder:7b'.
```

**Fix:** Pull the required model:

```bash
ollama pull qwen2.5-coder:7b
```

Then verify it is listed:

```bash
ollama list
```

### Ollama: "unreachable" in `warden config llm status`

Ollama is not running. Start it:

```bash
ollama serve
```

Or check if it is running on a non-default port:

```bash
export OLLAMA_HOST=http://localhost:11434
warden config llm test
```

### API Key Missing

```
Error: anthropic: API key is required but not configured
```

**Fix:** Export the required environment variable in your shell or add it to your CI/CD secrets:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Warden reads these at startup. Restart after setting.

### Azure OpenAI: All Three Variables Required

Azure requires `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_DEPLOYMENT_NAME` to be set simultaneously. If any is missing, Azure will not be detected as a configured provider.

### Claude Code or Codex Not Detected

Warden checks for `claude` or `codex` in your `PATH` by running `--version`. If detection fails:

1. Verify the binary is installed: `which claude` or `which codex`
2. Verify it runs: `claude --version`
3. Ensure the binary is accessible from the same shell environment Warden runs in

### Provider Switched via Env Var but Config Model Looks Wrong

When `WARDEN_LLM_PROVIDER` overrides the provider from config.yaml, Warden resets `smart_model` to the new provider's default model. This prevents mismatches like a `claude-sonnet-*` model name being sent to Groq.

To pin a specific model on the overridden provider:

```bash
export WARDEN_LLM_PROVIDER=groq
export WARDEN_SMART_MODEL=llama-3.3-70b-versatile
```

### CI Job Fails: "claude_code not available"

Claude Code is a local CLI tool. In CI environments (where `CI=true` or `GITHUB_ACTIONS=true`), Warden filters it out automatically. If you explicitly set `WARDEN_LLM_PROVIDER=claude_code` in CI, block it and fall back to an API provider:

```bash
export WARDEN_BLOCKED_PROVIDERS=claude_code
export WARDEN_LLM_PROVIDER=groq
export GROQ_API_KEY=${{ secrets.GROQ_API_KEY }}
```

### Checking Resolved Configuration

To see exactly what Warden has resolved (provider chain, models, rate limits):

```bash
warden config llm status
warden config list
```

For JSON output suitable for scripting:

```bash
warden config list --json | jq '.llm'
```
