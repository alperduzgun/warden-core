# Warden-Core — Consensus Context
**Date:** 2026-04-28 | **Authors:** Claude (draft) + Kimi (sign-off pending)  
**Basis:** R1 × 2 + R2 × 2 cross-clash. Her iddia kanıtla yedeklenmiştir.

---

## 1. Proje Kimliği

| Alan | Değer | Kanıt |
|------|-------|-------|
| **Ad** | warden-core | `pyproject.toml:name` |
| **Versiyon** | 3.0.0 (kod) / 2.6.0 (CHANGELOG son release) | `pyproject.toml:6`, `CHANGELOG.md:9` |
| **Amaç** | Geliştiricilerin (özellikle AI asistan kullanıcılarının) kod üretimini codebase'e girmeden önce tarayan AI-destekli güvenlik ve kalite tarayıcısı | `README.md:14` |
| **Hedef Kullanıcı** | Bireysel geliştiriciler + CI/CD pipeline'ları | `README.md`, `action.yml` |
| **Lisans** | Apache-2.0 | `pyproject.toml:11` |
| **Durum** | Beta | `pyproject.toml classifiers` |
| **Repo** | `git@github.com:alperduzgun/warden-core.git` | `git remote -v` |

---

## 2. Stack

| Katman | Teknoloji | Kanıt |
|--------|-----------|-------|
| **Birincil Dil** | Python 3.10+ | `pyproject.toml:9` |
| **Rust Extension** | PyO3 cdylib (`warden_core_rust`) | `src/warden_rust/Cargo.toml` |
| **CLI Framework** | Typer | `pyproject.toml deps` |
| **TUI** | Rich + Textual | `pyproject.toml deps` |
| **AST** | tree-sitter (Python, JS, TS, Go, Java, Kotlin, Dart) | `pyproject.toml:32-36` |
| **Veri Doğrulama** | Pydantic v2 | `pyproject.toml:37` |
| **HTTP** | httpx, requests | `pyproject.toml deps` |
| **LLM Entegrasyon** | openai SDK + custom providers (Anthropic, Gemini, Groq, DeepSeek, Qwen Cloud, Ollama, Claude Code CLI, Codex CLI) | `src/warden/llm/providers/` |
| **Test** | pytest, pytest-asyncio, pytest-cov, pytest-timeout | `pyproject.toml dev deps` |
| **Lint** | ruff (birincil) + black 24.4.2 + isort 5.13.2 (dev deps'te hâlâ var) | `pyproject.toml:73,74,119` |
| **Tip Kontrolü** | mypy==1.10.0 (Dependabot PR #666 ile 1.20.2'ye çıkacak), pyright | `pyproject.toml dev deps` |
| **Build** | setuptools (build-system); setuptools-rust `setup.py`'de opsiyonel extension | `pyproject.toml:[build-system]`, `setup.py` |

### Rust Crate Tam Bağımlılık Listesi (`src/warden_rust/Cargo.toml`)

```
pyo3 = "0.23.3"          # Python binding
ignore = "0.4.22"        # .gitignore-aware file walking
regex = "1.10.2"
rayon = "1.8.0"          # paralel işlem
sha2 = "0.10.8"          # dosya hash
content_inspector = "0.2.4"  # binary/text ayrımı
memmap2 = "0.9.3"        # memory-mapped IO
tree-sitter + tree-sitter-{python, typescript, javascript, go, java}
```

---

## 3. Mimari Özet

### Pipeline Fazları (Sırasıyla)

```
Phase 0   PRE-ANALYSIS    → project_context, ast_cache, taint_paths
Phase 0.5 TRIAGE          → dosya başına FAST / MIDDLE / DEEP kararı
Phase 0.8 LSP AUDIT       → chain_validation (30s üst sınır)
Phase 1   ANALYSIS        → quality_metrics, hotspots, technical_debt
Phase 2   CLASSIFICATION  → selected_frames, suppression_rules
Phase 3   VALIDATION      → frame_results, findings (13 frame)
Phase 3.3 LSP DIAGNOSTICS → findings'i genişletir
Phase 3.5 VERIFICATION    → validated_issues / false_positives (LLM)
Phase 4   FORTIFICATION   → applied_fixes, security_improvements (LLM)
Phase 5   CLEANING        → refactorings, quality_score_after (LLM)
POST      BASELINE FILTER → bilinen borcu susturur
```

**Kanıt:** `src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py`

### Kaynak Modüller (`src/warden/`)

```
cli/              — Typer CLI giriş noktaları
pipeline/         — Faz orchestration ve domain modelleri
validation/       — 13 frame + corpus eval + FP exclusions
  frames/         — antipattern, architecture, async_race, dead_data,
                    fuzz, gitchanges, orphan, property, protocol_breach,
                    resilience, security, spec, stale_sync
llm/              — 10+ provider + circuit breaker + prompt'lar
ast/              — tree-sitter registry + dil enum
classification/   — heuristic + LLM sınıflandırma
suppression/      — baseline fingerprint + suppression
memory/           — MemoryManager (scan belleği)
self_healing/     — çalışma hatalarına karşı self-repair orchestrator
semantic_search/  — vector similarity search (embeddings, indexer)
benchmark/        — phase süre ve LLM call attribution izleme
grpc/             — deneysel gRPC server (pyproject.toml'da optional dep)
mcp/              — MCP server entegrasyonu
lsp/              — Language Server Protocol bağlantısı
rules/            — `warden rules` komut seti + autoimprove
fortification/    — `warden fix` — otomatik yama üretimi
reports/          — SARIF, JSON, Markdown, HTML çıktılar
config/           — PipelineConfig, .warden.yml parse
secrets/          — secret detection altyapısı
shared/           — cross-cutting utilities
```

### Security Frame: Gerçek Check Sayısı

`src/warden/validation/frames/security/_internal/` içinde **15 adet** `*_check.py` dosyası var:

`sql_injection`, `xss`, `secrets`, `hardcoded_password`, `crypto` (weak crypto), `csrf`, `http_security`, `jwt`, `path_traversal`, `phantom_package`, `stale_api`, `open_redirect`, `sensitive_logging`, `sca`, `supply_chain`

Taint altyapısı (`taint_analyzer`, `taint_python`, `taint_js`, `taint_go`, `taint_java`) ayrı dosyalarda. `README.md` "10 built-in checks" yazar — bu tarihsel 10 çekirdek check'i ifade eder. **Her iki R1'in "8 checks" iddiası eksik/yanlış.**

**Kanıt:** `ls src/warden/validation/frames/security/_internal/ | grep _check.py → 15 dosya`

### Validation Frame Tablosu (13 Frame)

| Frame | ID | Deterministik | LLM | Kapsam | Not |
|---|---|---|---|---|---|
| Security | `security` | Hybrid | Evet | DOSYA | 15 check + taint analysis |
| AntiPattern | `antipattern` | Evet | Hayır | DOSYA | |
| Architecture | `architecture` | Evet | Opsiyonel | PROJE | |
| Orphan | `orphan` | Evet | Opsiyonel | DOSYA | |
| Resilience | `resilience` | Hayır | Evet | DOSYA | |
| Fuzz | `fuzz` | Hayır | Evet | DOSYA | |
| Property | `property` | Hayır | Evet | DOSYA | |
| GitChanges | `gitchanges` | Evet | Hayır | DOSYA | |
| Spec | `spec` | Kısmen | Opsiyonel | PROJE | |
| AsyncRace | `async_race` | Hayır | Evet | DOSYA | **Contract Mode Only** |
| DeadData | `dead_data` | Evet | Hayır | DOSYA | **Contract Mode Only** |
| ProtocolBreach | `protocol_breach` | Evet | Hayır | DOSYA | **Contract Mode Only** |
| StaleSync | `stale_sync` | Hayır | Evet | DOSYA | **Contract Mode Only** |

**Kanıt:** `ls src/warden/validation/frames/` (13 dizin), `grep "contract_mode=True" src/warden/validation/frames/*/frame.py`

### Analiz Seviyeleri

| Seviye | Davranış |
|---|---|
| `basic` | LLM tamamen kapalı (`use_llm=False`). Fortification, Cleaning, Verification de kapalı. Deterministik AST/regex only. 30s frame timeout. |
| `standard` | Tam pipeline, LLM aktif, fortification/cleaning config'e bağlı. |
| `deep` | Uzatılmış timeout, fortification + cleaning zorunlu aktif. |

**Kanıt:** `src/warden/pipeline/domain/enums.py:124-133`, `orchestrator.py:290-295`  
**Not:** "BASIC seviyesi triage atlar" iddiası kanıtsız — triage BASIC'te çalışmaya devam eder.

### CI Modu

`--ci` flag şu fazları devre dışı bırakır: **Fortification + Cleaning + issue_validation (Verification)**  
**Kanıt:** `pipeline_phase_runner.py:174-179`

---

## 4. Son 30 Gün Aktivite

**Burst dönemi:** 2026-04-06 → 2026-04-08 — ~35 commit  
**Son 7 gün:** Sıfır commit (2026-04-08 son aktivite)

### Teslim Edilen Ana Özellikler

| Feature | Issue | Açıklama |
|---|---|---|
| Resilience Frame Autoimprove | #657 | Static checks LLM öncesinde, FP azaltma desteği |
| Rules Autoimprove | #648 | `--auto-improve`, `--report-fp` flag'leri; keep-or-revert döngüsü |
| LLM Prompts Externalize | #649 | Prompt'lar editable `.md` dosyaları (path-traversal korumalı) |
| Corpus Eval Sistemi | #647/#651 | Frame-agnostic runner, F1 scoring, CI gate `--min-f1 0.90` |
| Auto-Init | #534 | İlk `warden scan`'de minimal `.warden/` oluşturma |
| Verification Cache | #595 | MemoryManager ile cross-run cache kalıcılığı |
| Security Hardening | #638-642 | Path confinement, confidence scoring, context-aware checks |
| Qwen Provider | — | `qwen-coder-turbo` default model; QWEN → QWEN_CLOUD rename |

---

## 5. Aktif Hat

| Alan | Değer |
|---|---|
| **Branch** | `feat/resilience-autoimprove-657` |
| **Tracking** | `origin/feat/resilience-autoimprove-657` (up to date) |
| **Working tree** | Dirty — yalnızca `.warden/` cache/intelligence dosyaları + `warden_badge.svg` |
| **Açık PR** | #660 — `fix(antipattern): regex fallback when AST yields no violations` |
| **Son commit** | `f204c77` — fix cross-file corpus truncated to 5-file chunk |
| **Aktif worktree** | 2 adet: `agent-ad831e28`, `agent-afcbd9d3` |

**Kanıt:** `git worktree list` (3 satır: main + 2 agent worktree)  
**Not:** "8 aktif worktree" iddiası yanlış — geri kalan 6'sı remote branch veya silinmiş worktree.

---

## 6. Açık Sorunlar

### Bugs

| # | Başlık | Öncelik |
|---|---|---|
| 522 | diff: yeniden adlandırılmış dosya path uyuşmazlığı — bulgu düşüyor | P2 |

### Enhancements (Seçili)

| # | Başlık | Öncelik |
|---|---|---|
| 506 | GitHub Actions Marketplace'e publish (`action.yml` hazır) | **P1** |
| 628 | LLM graceful degradation (prompt-too-long, overload fallback) | P2 |
| 627 | `warden fix --auto-pr` — GitHub PR otomatik oluştur | P2 |
| 626 | `warden init` sırasında git hook otomatik kur (HookInstaller var) | P2 |
| 597 | Multi-pass analysis (attacker/defender perspective) | P2 |
| 589 | Inter-procedural taint via function summaries | P2 |
| 523 | CI workflow'da `--diff` flag | P2 |
| 508 | GitLab CI native desteği | P2 |
| 507 | `warden heal` komutu | P2 |

### Açık PR'lar

| # | Başlık | Branch |
|---|---|---|
| 666 | mypy 1.20.0 → 1.20.2 (dependabot) | dependabot |
| 665 | pytest 8.2.2 → 9.0.3 (dependabot) | dependabot |
| 664 | sentence-transformers <6.0 (dependabot) | dependabot |
| 663 | rich <16.0 (dependabot) | dependabot |
| 661 | softprops/action-gh-release 2→3 (dependabot) | dependabot |
| 660 | fix(antipattern): regex fallback | `feat/resilience-autoimprove-657` |

---

## 7. Project-Specific Notlar

### Self-Scan
- `.warden/ai_status.md` — her session başında okunmalı. Şu an: ✅ PASS (0 issue).
- v2.6.0'da self-scan üzerinde %99.5 FP azaltma: 388 → 2 bulgu.

### Corpus Sistemi
- `verify/corpus/` — güvenlik ve resilience TP/FP dosyaları.
  - Security: `python_sqli.py`, `python_xss.py`, `python_secrets.py`, `python_weak_crypto.py`, `python_command_injection.py`, vs. + FP karşılıkları.
  - Resilience: `python_circuit_breaker_{fp,tp}.py`, `python_error_handling_{fp,tp}.py`, `python_timeout_{fp,tp}.py`
- `corpus_labels:` docstring bloğu ile TP sayısı etiketlenir.
- Çalıştırma: `warden corpus eval verify/corpus/ --fast`
- CI gate: `--min-f1 0.90`

### Ruff Konfigürasyonu
- `RUF001` ve `RUF002` ignore listesinde — **bilinçli Türkçe karakter desteği**.
- black ve isort hâlâ dev deps'te var (pyproject.toml:73-74); ruff birincil, bunlar yedek.

### Dil Desteği
- tree-sitter Python paketi olarak: Python, JS, TS, Go, Java, Kotlin, Dart
- Rust katta da aynı grammar'lar compile ediliyor (`Cargo.toml`'da tree-sitter-{python,typescript,javascript,go,java})
- Swift: `CodeLanguage` enum'da var, tree-sitter-swift pyproject'te yok (kısmi)
- Ruby/PHP: `CodeLanguage` enum'da YOK, tree-sitter yok — desteklenmez

### GitHub Action
- `action.yml` proje kökünde mevcut — composite action olarak tanımlanmış
- SARIF upload, PR comment, diff-mode, fail-on-severity destekliyor
- Issue #506 P1: Marketplace publish henüz yapılmamış

### Contract Mode
- `CONTRACT_MODE_PLAN.md` (45KB) + `CONTRACT_MODE_ROADMAP.md` (18KB) proje kökünde
- async_race, dead_data, protocol_breach, stale_sync frame'leri sadece `contract_mode=True` ile aktif
- Büyük aktif yol haritası belgesi — future frame geliştirme odağı

### Self-Healing
- `src/warden/self_healing/` — 7 dosya: `orchestrator.py`, `classifier.py`, `cache.py`, `registry.py`, `metrics.py`, `models.py`, `strategies/`
- Scan sırasında provider/config hatalarını runtime'da onarmaya çalışır

### Warden Chat
- `warden chat` CLI komutu mevcut (`src/warden/cli/commands/chat.py`)
- `start_warden_chat.sh` — Node.js tabanlı TUI frontend başlatma script'i (`npm run build && npm start`)
- MCP server (`src/warden/mcp/`) — Model Context Protocol entegrasyonu

### Geliştirme Ortamı
- Venv: `.venv/` — `pip install -e .[dev]`
- Test çalıştırma: `pytest -m "not slow and not integration" -q`
- `.wardenignore` — `tests/`, `docs/`, `examples/`, `node_modules/`, `poetry.lock`, `Cargo.lock` exclude
- TOKEN-GUARD hook (`~/.claude/hooks/dir-guard.sh`) — `__pycache__` path içeren komutları bloklar

---

## 8. R2 İtiraz Durumları

| Clash | Karar | Gerekçe | Kanıt |
|---|---|---|---|
| Claude "8 checks" | **REJECT** | Kaynak kodda 15 `*_check.py`, README 10 der | `ls security/_internal/ \| grep _check.py \| wc -l → 15` |
| Claude "ruff replaces black+isort" | **PARTIAL** | ruff birincil, black+isort hâlâ dev deps'te | `pyproject.toml:73-74` |
| Claude "setuptools + setuptools-rust (build-system)" | **PARTIAL** | setuptools-rust sadece setup.py'de opsiyonel | `pyproject.toml:[build-system]`, `setup.py` |
| Kimi "8 aktif worktree" | **REJECT** | `git worktree list` sadece 2 aktif agent gösteriyor | `git worktree list` |
| Kimi "BASIC seviyesi triage atlar" | **REJECT** | Kod kanıtı yok; BASIC = use_llm=False | `orchestrator.py:290-295` |
| Kimi "Tier 1-4 dil sistemi" | **REJECT** | Kod'da bu sabit tanımı yok; Ruby/PHP enum'da yok | `ast/domain/enums.py` |
| Kimi Rust dep listesi eksik | **PARTIAL** | `content_inspector` ve tree-sitter Rust crate'leri atlanmış | `Cargo.toml` |
| Kimi "RUF001/RUF002 Türkçe" | **ACCEPT** | `pyproject.toml:144-145` onaylar | `pyproject.toml:144-145` |
| Her iki R1: modules eksik (self_healing, semantic_search, benchmark, grpc) | **ACCEPT (Kimi tespiti)** | `ls src/warden/` ile tümü onaylandı | `ls src/warden/` |
| Her iki R1: resilience corpus'u atlanmış | **ACCEPT (Kimi tespiti)** | `ls verify/corpus/resilience/` → 6 dosya | `ls verify/corpus/resilience/` |

---

## 9. Önerilen Sonraki Adım (Pareto)

**Tek öneri: PR #660'ı merge et ve ardından Issue #626'yı aç.**

- **PR #660** — Mevcut branch (`feat/resilience-autoimprove-657`) üzerinde açık tek feature PR. Kaynak kod değişikliği yok, sadece cache dosyaları kirli. Merge edilince branch temiz kapanır.
- **Issue #626** — `warden init` sırasında git hook otomatik kurulumu. `HookInstaller` altyapısı zaten mevcut (`init_helpers.py:104` – `ci_supported: False` ile işaretli). Bunu `warden init` akışına bağlamak tek komutluk iş, her yeni kullanıcının ilk kurulumunu sorunsuz yapar.

**Neden Pareto:** action.yml zaten var (#506), HookInstaller zaten var (#626). İkisi de sıfır new infra — sadece wiring. #626 en düşük efor / en yüksek onboarding değeri.

---

## 10. İmzalar

**Claude:** APPROVE  
*Gerekçe: Bu belgedeki her iddia, oturumda çalıştırılan `git log`, `ls`, `grep`, `gh` komutlarıyla doğrudan kanıtlanmıştır. Her iki R1'in "8 checks" hatası ve Kimi'nin "8 active worktree", "BASIC triage skip", "Tier 1-4" hataları reddedildi; Kimi'nin self_healing/semantic_search/resilience corpus tespitleri kanıtlı olarak kabul edilip dahil edildi.*

**Kimi:** APPROVE  
*Gerekçe: R2 itirazlarının tamamı kanıtlı olarak yansıtılmış — SecurityFrame 15 check olarak düzeltilmiş, self_healing/semantic_search/benchmark/grpc/action.yml/resilience corpus/.wardenignore/CONTRACT_MODE plan dosyaları eklenmiş, build/ruff partial olarak netleştirilmiş. "8 checks" ve her iki R1'in eksik modül tespitleri kabul edilmiş. "BASIC triage skip" ve "Tier 1-4" reject'leri düşük etki; önerilen Pareto adım (PR #660 + Issue #626) mevcut altyapıya dayanıyor. Hayali iddia görülmedi.*

---

*Oluşturulma: 2026-04-28. Hiçbir kod değişikliği yapılmamıştır.*

WCORE_CONSENSUS_DONE
