# Warden Core — Bağlam Yükleme (2026-04-28)

> Sıfır kod, sıfır aksiyon. Salt okuma projesi tanıma özetidir.

---

## 1. Proje Kimliği

| Alan | Değer |
|------|-------|
| **Adı** | Warden Core (warden-core) |
| **Versiyon** | 3.0.0 (pyproject.toml) / 2.6.0 (CHANGELOG son) |
| **Amacı** | LLM'lerin (Claude, GPT-4 vb.) ürettiği kodu codebase'e girmeden doğrulayan AI-native güvenlik ve kalite kapısı |
| **Slogan** | "AI writes the code. Warden guards the production." |
| **Hedef Kullanıcı** | AI kod asistanı kullanan geliştiriciler, DevOps/CI-CD pipeline'ları |
| **Lisans** | Apache-2.0 |
| **Durum** | Beta |
| **Repo** | `git@github.com:alperduzgun/warden-core.git` |

---

## 2. Stack

| Katman | Teknoloji |
|--------|-----------|
| **Dil** | Python 3.10+ (ana), Rust (PyO3 ile extension) |
| **CLI Framework** | Typer |
| **TUI** | Rich + Textual |
| **AST Ayrıştırma** | tree-sitter (Python, JS/TS, Go, Java, Kotlin, Dart) |
| **Veri Doğrulama** | Pydantic v2 |
| **HTTP** | httpx, requests |
| **LLM Entegrasyonu** | openai SDK, özel provider'lar (Anthropic, Gemini, Groq, DeepSeek, Qwen Cloud, Ollama, Claude Code CLI, Codex CLI) |
| **Test** | pytest, pytest-asyncio, pytest-cov, pytest-timeout |
| **Lint/Format** | ruff (black+isort yerine) |
| **Tip Kontrolü** | mypy 1.10, pyright |
| **Build** | setuptools + setuptools-rust |
| **Rust Crate** | `warden_core_rust` (cdylib) — regex, sha2, rayon, ignore, memmap2 |

---

## 3. Mimari Özet

### Pipeline Aşamaları (Çalışma Sırası)

```
Aşama 0   PRE-ANALYSIS    → project_context, ast_cache, taint_paths
Aşama 0.5 TRIAGE          → dosya başına: FAST / MIDDLE / DEEP
Aşama 0.8 LSP AUDIT       → chain_validation (30s sınır)
Aşama 1   ANALYSIS        → quality_metrics, hotspots, technical_debt
Aşama 2   CLASSIFICATION  → selected_frames, suppression_rules
Aşama 3   VALIDATION      → frame_results, findings (13+ frame)
Aşama 3.3 LSP DIAGNOSTICS → findings'i genişletir
Aşama 3.5 VERIFICATION    → validated_issues, false_positives (LLM)
Aşama 4   FORTIFICATION   → applied_fixes, security_improvements (LLM)
Aşama 5   CLEANING        → refactorings, quality_score_after (LLM)
POST      BASELINE FILTER → bilinen borçları susturur
```

### Validation Frame'leri (Toplam 13)

| Frame | ID | Öncelik | Deterministik | LLM | Kapsam | Notlar |
|-------|----|---------|---------------|-----|--------|--------|
| Security | `security` | CRITICAL | Hybrid | Evet | DOSYA | 8 kontrol + taint analysis. SQLi, XSS, secrets, CSRF, weak crypto, JWT, command injection, path traversal |
| AntiPattern | `antipattern` | HIGH | Evet | Hayır | DOSYA | Boş catch, god class, debug çıktısı, TODO/FIXME işaretçileri |
| Architecture | `architecture` | HIGH | Evet | Opsiyonel | PROJE | Kırık import, döngüsel bağımlılık, yetim dosyalar |
| Orphan | `orphan` | MEDIUM | Evet | Opsiyonel | DOSYA | Kullanılmayan import, çağrılmayan fonksiyon, erişilemez kod |
| Resilience | `resilience` | HIGH | Hayır | Evet | DOSYA | Eksik hata yönetimi, timeout, circuit breaker, retry mantığı |
| Fuzz | `fuzz` | MEDIUM | Hayır | Evet | DOSYA | Null kontrol, sınır değer, tip doğrulama açıkları |
| Property | `property` | HIGH | Hayır | Evet | DOSYA | Önkoşul/sonkoşul, invariant ihlalleri, state machine hataları |
| GitChanges | `gitchanges` | MEDIUM | Evet | Hayır | DOSYA | Git diff'teki değişen satırlar |
| Spec | `spec` | LOW | Kısmen | Opsiyonel | PROJE | API consumer vs provider contract uyuşmazlığı |
| AsyncRace | `async_race` | MEDIUM | Hayır | Evet | DOSYA | Sadece Contract Mode. asyncio'da paylaşılan mutable state |
| DeadData | `dead_data` | LOW | Evet | Hayır | DOSYA | Sadece Contract Mode. Dead write, missing write |
| ProtocolBreach | `protocol_breach` | MEDIUM | Evet | Hayır | DOSYA | Sadece Contract Mode. Eksik mixin enjeksiyonları |
| StaleSync | `stale_sync` | MEDIUM | Hayır | Evet | DOSYA | Sadece Contract Mode. Mantıksal olarak bağlı alanların güncellenmemesi |

### Temel Servisler

- **Taint Analysis** — Paylaşılan Pre-Analysis servisi. Source-to-sink izleme. Python (AST), JS/TS/Go/Java (regex 3-pass). SecurityFrame, FuzzFrame, ResilienceFrame tarafından tüketilir.
- **Code Graph** — Import graph, gap report. CodeGraphAware frame'lere enjekte edilir.
- **LLM Router** — Provider kaydı, circuit breaker, rate limiting, paralel fast-tier çalıştırma.
- **Caching** — Dosya seviyesi hash cache, sonuç cache, verification cache, classification cache, triage cache.
- **Corpus Değerlendirme** — `verify/corpus/` altında FP/TP etiketli test dosyaları. Check başına F1 skorlama.

### Veri Akışı

1. Kullanıcı `warden scan <path>` çalıştırır.
2. Pre-Analysis stack tespiti yapar, AST cache oluşturur, taint path'leri hesaplar.
3. Triage her dosyaya analiz derinliği atar (FAST → LLM atla, DEEP → tam).
4. Classification dosya başına uygun frame'leri seçer.
5. Validation frame'leri çalıştırır (önce deterministik, sonra LLM batch).
6. Verification bulguları LLM ile tekrar kontrol eder (CI mode hariç).
7. Baseline filter bilinen sorunları susturur.
8. Rapor üretilir: Markdown, JSON, SARIF.

---

## 4. Son Aktivite (Son 30 Gün)

### Yoğun Dönem: 2026-04-06 → 2026-04-08
3 günde ~35 commit. Yoğun özellik teslimi + Copilot review döngüleri.

**Teslim Edilen Ana Özellikler:**
- **#648 / #657 — Autoimprove FP Azaltma**
  - `--auto-improve` flag: düşük güvenilirlikli bulgulardan otomatik FP corpus oluşturma
  - `--report-fp` flag: finding ID ile anında false positive susturma
  - `warden rules autoimprove`: FP azaltma için keep-or-revert döngüsü
  - ResilienceFrame artık autoimprove destekliyor (static check'ler LLM öncesinde çalışıyor)
- **#649 — Dışsallaştırılmış LLM Promptları**
  - LLM promptları düzenlenebilir `.md` dosyalarına taşındı (hardcoded string değil)
  - Path-traversal korumalı prompt yükleyici, package-data dahil edilmesi
- **#647 / #651 — Corpus Değerlendirme Sistemi**
  - Frame-agnostic corpus runner (`warden corpus eval`)
  - FP/TP etiketli corpus dosyaları ve F1 skorlama
  - CI gate desteği (`--min-f1 0.90`)
- **#534 — Otomatik Init**
  - İlk `warden scan`'de minimal `.warden/` otomatik oluşuyor
  - YAML injection, TOCTOU, path traversal karşı sertleştirildi
- **#595 — Verification Cache Kalıcılığı**
  - MemoryManager, verification cache'i çalışmalar arasında kalıcı hale getiriyor
- **Güvenlik Sertleştirme (#638-642)**
  - Path confinement, atomic yazma, idempotent init, regex doğrulama
  - HardcodedPassword / WeakCrypto için confidence scoring
  - XSS / PathTraversal için bağlam-bilinçli kontroller

### Provider Eklemleri
- Qwen (Alibaba Cloud DashScope) provider eklendi.
- QWEN → QWEN_CLOUD olarak yeniden adlandırıldı.
- Varsayılan model: `qwen-coder-turbo`.

### Sessiz Dönem
- **Son 7 gün:** Sıfır commit (son aktivite günü 2026-04-08).

---

## 5. Aktif Hat

| Alan | Değer |
|------|-------|
| **Mevcut Branch** | `feat/resilience-autoimprove-657` |
| **Tracking** | `origin/feat/resilience-autoimprove-657` |
| **Branch Durumu** | Güncel |
| **Çalışma Ağacı** | Kirli — `.warden/` cache/intelligence dosyaları değişmiş, `warden_badge.svg` değişmiş, takip edilmeyen `.qwen/` ve `examples/demo-scan/` var |
| **Açık PR** | #660 — `fix(antipattern): regex fallback when AST yields no violations` (bu branch üzerinde) |
| **Son Commit** | `f204c77` — "fix(orphan): fix cross-file corpus truncated to 5-file chunk, causing mass FPs" |

**Bu branch ne yapıyor:**
- ResilienceFrame için autoimprove desteği ekler (önceden sadece SecurityFrame destekliyordu)
- ResilienceFrame'de static check'ler LLM'den **önce** çalıştırılır (performans + determinizm)
- Pipeline scan'lerinde 0 bulgu yaratan AST node type mismatch düzeltilir
- Copilot review düzeltmeleri uygulanır (singleton registry, pre-split lines, frame_id, regex fix)

---

## 6. Açık Sorunlar ve PR'lar

### Açık Issues (20 toplam, öne çıkanlar)

| # | Başlık | Etiketler | Öncelik |
|---|--------|-----------|---------|
| 657 | feat(rules): autoimprove FP reduction support for resilience frame | enhancement | — |
| 650 | feat(config): security_research.md — otonom scan iyileştirme için insan strateji dosyası | enhancement | — |
| 628 | feat(resilience): LLM graceful degradation — prompt çok uzunsa context azaltma | enhancement, P2 | P2 |
| 627 | feat(fortification): `warden fix --auto-pr` — yamaları GitHub PR'ine otomatik dönüştürme | enhancement, P2 | P2 |
| 626 | feat(init): `warden init` sırasında git hook'larını otomatik kurma | enhancement, P2 | P2 |
| 597 | feat(llm): saldırgan/savunmacı perspektifli çok geçişli analiz | enhancement, P2 | P2 |
| 596 | feat(llm): onaylanmış bulgulardan zafiyet pattern corpus'u | enhancement, P2 | P2 |
| 593 | feat(llm): güvenlik analizi promptlarına JSON schema zorlaması | enhancement, P2 | P2 |
| 592 | feat(llm): deterministik LLM bağlamı için yapısal pre-tag'ler | enhancement, P2 | P2 |
| 589 | feat(cross-file): fonksiyon özetleriyle inter-procedural taint yayılımı | enhancement, P2 | P2 |
| 536 | chore(config): 12 PipelineConfig alanı config.yaml üzerinden yapılandırılamıyor | enhancement, P2 | P2 |
| 506 | feat(action): Warden'i GitHub Actions Marketplace'e yayınlama | enhancement | **P1** |
| 522 | bug(diff): yeniden adlandırılmış dosya yolu uyuşmazlığı bulguların düşmesine neden oluyor | bug, P2 | P2 |
| 507 | feat(cli): `warden heal` komutu — otomatik düzeltme önerileri | enhancement, P2 | P2 |

### Açık PR'lar (6 toplam)

| # | Başlık | Branch |
|---|--------|--------|
| 666 | chore(deps): mypy 1.20.0 → 1.20.2 | dependabot |
| 665 | chore(deps): pytest 8.2.2 → 9.0.3 | dependabot |
| 664 | chore(deps): sentence-transformers <4.0 → <6.0 | dependabot |
| 663 | chore(deps): rich <15.0 → <16.0 | dependabot |
| 661 | chore(ci): softprops/action-gh-release 2 → 3 | dependabot |
| 660 | fix(antipattern): AST ihlal vermeyince regex fallback | `feat/resilience-autoimprove-657` |

---

## 7. Notlar ve Project-Specific Quirks

### Self-Scan Kalitesi
- v2.6.0'da self-scan üzerinde **%99.5 false-positive azaltma** sağlandı: 388 bulgu → 2 bulgu.
- Cross-file analysis üretime hazır (import graph, value propagation, LLM context enrichment).
- **%98+ detection rate** 4 gerçek projedeki 53 yerleştirilmiş zafiyetle doğrulandı.

### Warden Kendini Korur
- `.warden/ai_status.md` şu anda **PASS** gösteriyor (0 critical, 0 toplam issue).
- Durum FAIL olursa agent SARIF/JSON raporlarını okuyup düzeltme yapmalıdır.

### Corpus Sistemi
- `verify/corpus/` altında bulunur.
- Dosyalarda `corpus_labels:` docstring blokları vardır (örn. `sql-injection: 3` TP, `xss: 0` FP).
- Çalıştırma: `warden corpus eval verify/corpus/ --fast`
- Kural: `pattern_confidence < 0.75` olan bulgular LLM'e yönlendirilir ve corpus skorlamasına **dahil edilmez**.

### Yapılandırma
- Proje yapılandırması `.warden/` dizininde yaşar.
- `config.yaml`, `rules/`, `suppressions.yaml`, `baseline/`, `cache/`, `intelligence/`.
- İlk scan'de auto-init minimal `.warden/` iskeleti oluşturur.
- 12 `PipelineConfig` alanı henüz `config.yaml` üzerinden yapılandırılamıyor (issue #536).

### CI Davranışı
- `--ci` flag otomatik olarak kapatır: Fortification, Cleaning, Verification (3 LLM-ağır aşama).
- `--diff` modu artımlı PR scan'leri için mevcuttur.

### Analiz Seviyeleri
- `basic` — triage atla, sadece heuristic classification, deterministik validation, verification/fortification/cleaning atla.
- `standard` — tam pipeline, fortification/cleaning config'e bağlı.
- `deep` — uzatılmış timeout, fortification & cleaning aktif.

### Dil Katmanları
- **Tier 1 (Tam):** Python, JavaScript/TypeScript — AST + taint + güvenlik kuralları.
- **Tier 2 (Standart):** Go, Java — AST + regex taint.
- **Tier 3 (Temel):** Kotlin, Dart — sadece AST.
- **Tier 4 (Sadece Regex):** Swift, C/C++, Ruby, PHP — sadece regex.

### Rust Extension
- `src/warden_rust/` `setuptools-rust` ile derlenir.
- Bağımsız binary değil; Python extension modülü olarak derlenir (`cdylib`).
- Performans-kritik yol için kullanılır: dosya tarama, hash, muhtemelen AST operasyonları.

### MCP ve Chat
- MCP (Model Context Protocol) sunucu desteği `src/warden/mcp/` altında mevcut.
- Etkileşimli chat/TUI `warden chat` ile açılır.
- Slash-command sistemi (`/scan`, `/analyze`, `/rules`, vb.) + `@dosya` enjeksiyonu + `!shell` çalıştırma.

### Geliştirme Akışı
- Conventional Commits zorunlu: `feat(scope):`, `fix(scope):`, `chore:`, `style:`.
- PR öncesi gerekli: test geçişi, `ruff check` temiz, formatlı kod.
- Görev sonrası: `warden scan --diff` çalıştır ve bulguları ele al.

### Türkçe Karakter Desteği
- Ruff `RUF001`/`RUF002` (string/docstring'de belirsiz unicode karakter) görmezden gelir çünkü projede kasıtlı olarak Türkçe karakterler bulunur.

### Branch Hijyeni
- Reponun **çok sayıda** remote branch'i (~150+) ve çoklu worktree'si vardır.
- Aktif worktree'ler: `worktree-agent-a152d24f`, `worktree-agent-a241fb0e`, `worktree-agent-a408d5b6`, `worktree-agent-a5ca0338`, `worktree-agent-aa0ea417`, `worktree-agent-ad831e28`, `worktree-agent-aecd3213`, `worktree-agent-afcbd9d3`.
- Ana geliştirme branch'i: `dev`. Production: `main`.

---

*Bağlam 2026-04-28 tarihinde oluşturuldu. Hiçbir kod değişikliği yapılmamıştır.*

WCORE_CONTEXT_KIMI_DONE
