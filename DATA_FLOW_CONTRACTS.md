# Flow Contracts

Bu dosya, Warden'ın çalışma akışlarını ve o akış içindeki veri zincirlerini
birleşik formatta tanımlar. Akış omurgadır, veri akışa gömülüdür.

**AI için:** Kod değişikliği yapmadan önce bu dosyayı oku.
Değişikliğin hangi flow step'ini etkilediğini bul.
O step'in precondition, postcondition ve data-out'unu kontrol et.
Bir önceki ve sonraki step'lerle tutarlılığı doğrula.

**Gap tespiti:** Eğer bir step, önceki hiçbir step'in üretmediği
veriyi tüketiyorsa → DATA GAP. Eğer bir step'in postcondition'ı
sonraki step'in precondition'ını karşılamıyorsa → FLOW GAP.

---

## Format

Her flow contract bir state machine'dir:

```
STEP → (başarı) → STEP → (başarı) → STEP
  ↓ (hata)          ↓ (hata)
  STEP               STEP
```

Her **step** şunları içerir:

| Alan | Açıklama |
|------|----------|
| `id` | Benzersiz step tanımlayıcı (S1, S2...) |
| `state` | Bu adımdaki sistem durumu |
| `actor` | Bu adımı kim tetikler (user, system, cli) |
| `action` | Çalışan kod/fonksiyon |
| `file` | Kaynak dosya(lar) ve satır numaraları |
| `precondition` | Bu adımın çalışması için önceden doğru olması gerekenler |
| `data-in` | Bu adımın tükettiği veriler (önceki step'lerden) |
| `data-out` | Bu adımın ürettiği veriler (sonraki step'ler için) |
| `postcondition` | Bu adım başarılı olduğunda garanti edilen durumlar |
| `on-error` | Hata durumunda hangi step'e gidilir |
| `on-success` | Başarı durumunda hangi step'e gidilir |

---

## Flow Registry

| Flow ID | Kapsam | Bağımlı Olduğu Flow'lar |
|---------|--------|------------------------|
| `scan-pipeline` | `warden scan` CLI → 6-faz pipeline → rapor | `llm-provider-chain`, `audit-context`, `classification-phase`, `frame-execution` |
| `llm-provider-chain` | Provider seçimi, fast/smart tier yönlendirme, fallback | — |
| `audit-context` | Pre-analysis: CodeGraph, DependencyGraph, Taint, ProjectIntelligence | `llm-provider-chain` |
| `classification-phase` | Cache → Heuristic → LLM ile frame seçimi | `llm-provider-chain` |
| `frame-execution` | Tek dosya için tek frame execution: cache, inject, execute, rules | `llm-provider-chain` |

---

## Flow: scan-pipeline

```yaml
flow-id: scan-pipeline
purpose: >
  Kullanıcı `warden scan <path>` komutunu çalıştırır.
  CLI bridge, config'i okur, LLM servisini başlatır,
  pipeline orchestrator'ı oluşturur ve 6-faz pipeline'ı çalıştırır.
  Sonuçlar terminal'e + opsiyonel raporlara yazılır.
actors:
  - user: CLI komutu tetikleyen geliştirici
  - system: Pipeline orchestrator
  - llm: LLM provider (Ollama/Groq/vb.)
```

### S1: CLI Entry & Argument Parse

```yaml
id: S1
state: CLI komutu alındı, argümanlar parse ediliyor
actor: user
action: async_scan_impl()
file:
  - src/warden/cli/commands/scan.py (giriş noktası)
precondition:
  - Python env aktif, warden paketi yüklü
  - targets geçerli path(ler) içeriyor
data-in: none (CLI args)
data-out:
  - targets: list[str] — taranacak dosya/dizinler
  - frames_override: list[str] | None — --frames argümanı
  - analysis_level: str — BASIC|STANDARD|DEEP (default: STANDARD)
  - force: bool — baseline cache bypass
  - ci_mode: bool — CI ortamı flag
postcondition:
  - Argümanlar validate edildi
  - Scan akışı başlatılacak
on-success: → S2
on-error: → S-ERR (typer validation hata mesajı + exit 1)
```

### S2: Config & Bridge Initialization

```yaml
id: S2
state: Config okunuyor, LLM servisi başlatılıyor
actor: system
action: WardenBridge.get_bridge() → load_config() → LlmServiceFactory.create()
file:
  - src/warden/cli_bridge/bridge.py (get_bridge)
  - src/warden/cli_bridge/handlers/config_handler.py (load_config)
  - src/warden/llm/factory.py (LLM oluşturma)
precondition:
  - S1 postcondition karşılanmış
  - .warden/config.yaml proje kökünde mevcut (yoksa default değerler)
data-in:
  - project_root: tarama dizininden hesaplanır
data-out:
  - config: PipelineConfig — tüm pipeline ayarları
    └─ config.frames: list[str] — aktif frame ID'leri
    └─ config.llm_config: dict — provider, model, timeout
    └─ config.parallel_limit: int (default 4)
    └─ config.timeout: int (default 300s)
    └─ config.analysis_level: AnalysisLevel
  - llm_service: OrchestratedLlmClient — (bkz. llm-provider-chain flow)
  - frame_registry: FrameRegistry — tüm frame sınıfları yüklü
postcondition:
  - config nesnesinde provider, model, timeout ayarları dolu
  - llm_service bağlantı testleri geçildi (Ollama için preflight)
  - frame_registry'de frame_id → class eşlemesi var
on-success: → S3
on-error: → S-ERR (config parse hatası, LLM bağlantı hatası)
note: >
  WARDEN_LLM_PROVIDER env var config.yaml'daki provider değerini override eder.
  Öncelik: env var > config.yaml > default (DeepSeek).
```

### S3: File Discovery

```yaml
id: S3
state: Taranacak dosyalar listeleniyor
actor: system
action: FileDiscovery.discover(targets, config)
file:
  - src/warden/cli/commands/scan.py (file_discovery çağrısı)
  - src/warden/analysis/infrastructure/file_discovery.py
precondition:
  - S2 postcondition karşılanmış
  - targets geçerli dosya/dizin yolları
data-in:
  - targets: S1'den
  - config.gitignore_enabled: bool
  - config.exclude_patterns: list[str]
data-out:
  - code_files: list[CodeFile]
    └─ CodeFile.path: str
    └─ CodeFile.content: str
    └─ CodeFile.language: str
    └─ CodeFile.size_bytes: int
postcondition:
  - code_files boş değil (en az 1 dosya)
  - .gitignore pattern'leri uygulandı
  - İkili dosyalar ve generated dosyalar filtrelendi
on-success: → S4
on-error (no files): → S-EMPTY (uyarı + exit 0)
```

### S4: Pipeline Orchestrator Creation

```yaml
id: S4
state: Orchestrator oluşturuluyor, PipelineContext başlatılıyor
actor: system
action: PhaseOrchestrator.__init__() + PipelineContext()
file:
  - src/warden/pipeline/application/orchestrator/orchestrator.py:280-299
  - src/warden/pipeline/domain/pipeline_context.py
precondition:
  - S3 postcondition karşılanmış
data-in:
  - config: S2'den
  - llm_service: S2'den
  - code_files: S3'ten
data-out:
  - context: PipelineContext
    └─ context.pipeline_id: str (UUID)
    └─ context.started_at: datetime
    └─ context.project_root: Path
    └─ context.llm_config: Any | None (llm_service.config)
    └─ context.llm_provider: str (llm_service.provider.value)
    └─ context.language: str (ilk dosyadan)
  - pipeline: ValidationPipeline (status=RUNNING)
postcondition:
  - context.pipeline_id unique
  - context.llm_provider dolu → frame_runner'da doğru timeout hesabı
on-success: → S5
on-error: → S-ERR
note: >
  context.llm_provider frame_runner'daki timeout floor'u belirler:
  "ollama" → 120s, cloud providers → 10s.
  OrchestratedLlmClient'ın .config attr'u olmadığı için
  llm_provider string olarak context'e eklendi (a4e5eaf fix).
```

### S5: Pipeline Execution (6 Faz)

```yaml
id: S5
state: 6-faz pipeline async olarak çalışıyor
actor: system
action: execute_pipeline_async() → asyncio.wait_for(phases, timeout=config.timeout)
file:
  - src/warden/pipeline/application/orchestrator/orchestrator.py:320-336
  - src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py
precondition:
  - S4 postcondition karşılanmış
data-in:
  - context: S4'ten
  - code_files: S3'ten
  - frames_to_execute: config.frames + frames_override
data-out: (her faz context'e yazar)
  - Faz 0 → context.project_context, context.file_contexts (bkz. audit-context)
  - Faz 0.5 → context.triage_decisions
  - Faz 0.7 → context.code_graph, context.gap_report
  - Faz 0.8 → context.chain_validation
  - Faz 1 → context.quality_metrics, context.hotspots
  - Faz 2 → context.selected_frames, context.suppression_rules (bkz. classification-phase)
  - Faz 3 → context.findings, context.frame_results (bkz. frame-execution)
  - Faz 4 → context.fortifications
  - Faz 5 → context.cleaning_suggestions
postcondition:
  - context.findings listesi dolu (ya da boş = temiz)
  - Her frame_result'da status ∈ {passed, failed, warning, skipped}
on-success: → S6
on-error (timeout): → S-ERR (pipeline status=FAILED, stuck phase loglanır)
timeout: config.timeout saniye (default 300)
```

### S6: Output & Report Generation

```yaml
id: S6
state: Bulgular terminal'e yazdırılıyor, raporlar kaydediliyor
actor: system
action: ScanReporter.render() + BaselineUpdater.update()
file:
  - src/warden/cli/commands/scan.py (output kısmı)
  - src/warden/reporting/ (reporter sınıfları)
precondition:
  - S5 postcondition karşılanmış
data-in:
  - context.findings: S5'ten
  - context.frame_results: S5'ten
  - context.quality_metrics: S5'ten
data-out:
  - Terminal: Rich formatted findings tablosu
  - .warden/baseline/*.json: güncellenmiş baseline (--no-baseline yoksa)
  - warden_report.{json,sarif,md}: opsiyonel raporlar
  - warden_badge.svg: quality badge
  - exit_code: 0 (temiz) | 1 (bulgular var) | 2 (hata)
postcondition:
  - Baseline güncellendi
  - Exit code'a göre CI pipeline'ı pass/fail
on-success: exit 0 veya 1
on-error: → S-ERR (exit 2)
```

### S-ERR: Pipeline Error Handler

```yaml
id: S-ERR
state: Pipeline kritik hata ile sonlandı
actor: system
action: exception logging + user-friendly mesaj
file:
  - src/warden/cli/commands/scan.py (except bloğu)
data-in: exception
data-out:
  - Terminal: hata mesajı + öneri
  - exit_code: 2
```

---

## Flow: llm-provider-chain

```yaml
flow-id: llm-provider-chain
purpose: >
  LLM istemcisi oluşturulur, her request önce fast tier'a
  (paralel race), başarısız olursa smart tier'a yönlendirilir.
actors:
  - system: OrchestratedLlmClient
  - fast_tier: Ollama / Groq / Codex (paralel)
  - smart_tier: Ollama / Groq / Azure / OpenAI (fallback)
```

### S1: Config Resolution

```yaml
id: S1
state: Provider konfigürasyonu belirleniyor
actor: system
action: load_llm_config() — env var + config.yaml birleşimi
file:
  - src/warden/llm/config.py:217-325
  - src/warden/llm/factory.py
precondition:
  - Çalışma ortamı aktif
data-in:
  - WARDEN_LLM_PROVIDER env var (opsiyonel)
  - WARDEN_FAST_TIER_PRIORITY env var (opsiyonel)
  - WARDEN_BLOCKED_PROVIDERS env var (opsiyonel)
  - .warden/config.yaml llm bölümü
data-out:
  - llm_config: LlmConfiguration
    └─ default_provider: LlmProvider enum
    └─ smart_model: str
    └─ fast_model: str
    └─ fast_tier_providers: list[LlmProvider]
    └─ blocked_providers: set[LlmProvider]
postcondition:
  - Öncelik: env var > config.yaml > default (DeepSeek)
  - blocked_providers listesindeki provider'lar excluded
on-success: → S2
on-error: → default config (groq smart, ollama fast)
```

### S2: Client Instantiation

```yaml
id: S2
state: Smart ve fast tier istemcileri oluşturuluyor
actor: system
action: create_provider_client(provider, config) × N
file:
  - src/warden/llm/factory.py
  - src/warden/llm/providers/{ollama,groq,openai,...}.py
precondition:
  - S1 postcondition karşılanmış
data-in:
  - llm_config: S1'den
data-out:
  - smart_client: ILlmClient (tek adet)
  - fast_clients: list[ILlmClient] (sıfır veya daha fazla)
  - orchestrated: OrchestratedLlmClient(smart_client, fast_clients)
postcondition:
  - fast_clients boşsa → Smart-Only mode (info log)
  - CLAUDE_CODE/CODEX provider → single-tier mode (fast=smart)
on-success: → S3
on-error: → S-ERR (provider init failed)
note: >
  Ollama için preflight check yapılır (model yüklü mü?).
  Yüklü değil → ModelNotFoundError → scan devam eder (fail-open).
```

### S3: Request Routing

```yaml
id: S3
state: LLM request geldi, tier seçimi yapılıyor
actor: system
action: OrchestratedLlmClient.send_async(request)
file:
  - src/warden/llm/providers/orchestrated.py:95-160
precondition:
  - S2 postcondition karşılanmış
  - request: LlmRequest(system_prompt, user_message, use_fast_tier)
data-in:
  - request.use_fast_tier: bool (frame'ler genelde True gönderir)
  - fast_clients: S2'den
data-out:
  - response: LlmResponse
    └─ response.success: bool
    └─ response.content: str
    └─ response.model_used: str
    └─ response.prompt_tokens, completion_tokens: int
postcondition:
  - response.success=True ise content dolu
  - Metrics collector'a kayıt düşüldü (tier, provider, duration_ms)
on-success (fast tier): → S-DONE (ilk başarılı fast response döner)
on-success (smart fallback): → S-DONE
on-error (tüm tier'lar fail): → response.success=False, content=""
```

### S3-FAST: Fast Tier Parallel Race

```yaml
id: S3-FAST
state: Tüm fast clients paralel olarak race ediyor
actor: system
action: asyncio.gather(*[try_fast_provider(c) for c in fast_clients])
file:
  - src/warden/llm/providers/orchestrated.py:104-140
precondition:
  - fast_clients boş değil
  - request.use_fast_tier = True
data-in:
  - fast_clients: list[ILlmClient] — S2'den
  - request: LlmRequest — her client'a kopyalanır (fast_model kullanır)
data-out:
  - İlk başarılı response: LlmResponse
  - Kaybeden coroutine'ler: iptal edilir (cancel)
postcondition:
  - Sadece bir response döner (ilk success)
  - Kaybedenler serbest bırakılır
on-success: → S-DONE (smart tier atlanır)
on-error (hepsi fail): → S3-SMART
```

### S3-SMART: Smart Tier Fallback

```yaml
id: S3-SMART
state: Smart tier'a fallback yapılıyor
actor: system
action: smart_client.send_async(request)
file:
  - src/warden/llm/providers/orchestrated.py:141-160
precondition:
  - S3-FAST tüm provider'lar başarısız oldu
  - VEYA fast_clients boş (Smart-Only mode)
data-in:
  - request: LlmRequest — smart_model kullanır
data-out:
  - response: LlmResponse (smart tier'dan)
postcondition:
  - response.success durumuna göre frame devam eder/hata alır
on-success: → S-DONE
on-error: → response(success=False)
```

---

## Flow: audit-context

```yaml
flow-id: audit-context
purpose: >
  Scan başlamadan önce kod tabanı hakkında yapısal intelligence üretilir.
  Faz 0'dan 0.8'e kadar sıralı çalışır; her adımın çıktısı
  PipelineContext'e yazılır, sonraki fazlar ve frame'ler bunu okur.
actors:
  - system: PreAnalysisExecutor
  - ast: Tree-sitter AST provider
  - llm: LLM provider (opsiyonel)
```

### S1: File Context Analysis

```yaml
id: S1
state: Her dosyanın rolü ve bağlamı belirleniyor
actor: system
action: PreAnalysisPhase.execute_async() → FileContextAnalyzer
file:
  - src/warden/pipeline/application/executors/pre_analysis_executor.py:19-94
  - src/warden/analysis/application/pre_analysis_phase.py
precondition:
  - code_files listesi dolu
data-in:
  - code_files: list[CodeFile] — scan-pipeline S3'ten
data-out:
  - context.file_contexts: dict[str, FileAnalysisResult]
    └─ is_test: bool
    └─ is_config: bool
    └─ is_generated: bool
    └─ file_role: str — "auth", "handler", "model", "config" vb.
    └─ criticality: Criticality — CRITICAL|HIGH|MEDIUM|LOW
  - context.project_context: ProjectContext
    └─ project_type: ProjectType — BACKEND|WEB|CLI|LIBRARY vb.
    └─ framework: Framework | None — Django|FastAPI|Flask vb.
    └─ confidence: float
postcondition:
  - Her dosya için context.file_contexts'te kayıt var
  - context.project_context.project_type ≠ None
on-success: → S2
on-error: → context.project_context = default (UNKNOWN), devam
```

### S2: Dependency Graph

```yaml
id: S2
state: Import grafı çıkarılıyor
actor: system
action: DependencyGraph.analyze(code_files)
file:
  - src/warden/analysis/infrastructure/dependency_graph.py
  - .warden/intelligence/dependency_graph.json (persist)
precondition:
  - S1 postcondition karşılanmış
data-in:
  - code_files: CodeFile listesi
data-out:
  - context.dependency_graph_forward: dict[str, list[str]]
    └─ "auth.py" → ["models.py", "utils.py"]
  - context.dependency_graph_reverse: dict[str, list[str]]
    └─ "models.py" → ["auth.py", "app.py"]
postcondition:
  - Döngüsel bağımlılıklar tespit edilmiş
  - .warden/intelligence/dependency_graph.json yazılmış
on-success: → S3
on-error: → context.dependency_graph_* = {}, devam
```

### S3: Triage (FAST/MIDDLE/SLOW)

```yaml
id: S3
state: Her dosyanın tarama hızı sınıflandırılıyor
actor: system
action: TriagePhase.execute_async()
file:
  - src/warden/analysis/application/triage_phase.py
precondition:
  - S1 postcondition karşılanmış (file_contexts hazır)
data-in:
  - code_files: CodeFile listesi
  - context.file_contexts: S1'den
data-out:
  - context.triage_decisions: dict[str, TriageDecision]
    └─ lane: "FAST" | "MIDDLE" | "SLOW"
    └─ reason: str — "Low complexity", "Contains auth logic" vb.
postcondition:
  - Her dosya için lane kararı var
  - FAST → rules-only, MIDDLE → mixed, SLOW → LLM-heavy
on-success: → S4
on-error: → tüm dosyalar SLOW lane'e düşer
```

### S4: Code Graph & Symbol Extraction

```yaml
id: S4
state: Sembol grafı AST ile çıkarılıyor
actor: system
action: CodeGraphBuilder.build_async(code_files)
file:
  - src/warden/analysis/application/code_graph_builder.py
  - src/warden/ast/providers/python_ast_provider.py
  - .warden/intelligence/code_graph.json (persist)
precondition:
  - S1 postcondition karşılanmış
data-in:
  - code_files: CodeFile listesi
data-out:
  - context.code_graph: CodeGraph
    └─ nodes: dict[symbol_id, SymbolNode]
       └─ SymbolNode.name, .type, .file, .line
       └─ SymbolNode.calls: list[str] — çağırdığı semboller
       └─ SymbolNode.callers: list[str] — kendini çağıranlar
       └─ SymbolNode.decorators: list[str] — @route, @pytest.mark vb.
    └─ edges: list[tuple[str, str]]
postcondition:
  - context.code_graph.nodes boş değil
  - .warden/intelligence/code_graph.json yazılmış
on-success: → S5
on-error: → context.code_graph = empty graph, devam
note: >
  Framework-aware filtering: Flask route, Django view, FastAPI endpoint,
  Click/Typer command, pytest fixture gibi decorator'a sahip semboller
  "orphan" sayılmaz (false-positive azaltma, S14 session fix).
```

### S5: Gap Analysis

```yaml
id: S5
state: Ölü semboller ve erişilemeyen kod tespit ediliyor
actor: system
action: GapAnalyzer.analyze(code_graph)
file:
  - src/warden/analysis/application/gap_analyzer.py
  - .warden/intelligence/gap_report.json (persist)
precondition:
  - S4 postcondition karşılanmış (code_graph dolu)
data-in:
  - context.code_graph: S4'ten
data-out:
  - context.gap_report: GapReport
    └─ orphan_symbols: list[SymbolNode] — hiç çağrılmayan
    └─ dead_symbols: list[SymbolNode] — tanımlanmış ama ulaşılamaz
    └─ detected_framework: str
    └─ framework_excluded_count: int
postcondition:
  - framework_excluded_count framework decorator'lı FP'leri gösterir
  - .warden/intelligence/gap_report.json yazılmış
  - OrphanFrame bu veriyi S5-data olarak tüketir
on-success: → S6
on-error: → context.gap_report = empty, devam
```

### S6: Taint Analysis

```yaml
id: S6
state: Kullanıcı girdisinin tehlikeli sink'lere akışı izleniyor
actor: system
action: TaintAnalysisService.analyze_async(code_files)
file:
  - src/warden/analysis/taint/service.py
  - src/warden/validation/frames/security/_internal/analyzer.py
precondition:
  - S4 postcondition karşılanmış
data-in:
  - code_files: CodeFile listesi
  - context.code_graph: S4'ten (source-sink yolları için)
data-out:
  - context.taint_paths: dict[str, list[TaintPath]]
    └─ key: file_path
    └─ TaintPath.source: SourceNode — request.args, input() vb.
    └─ TaintPath.sink: SinkNode — execute(), subprocess.run() vb.
    └─ TaintPath.is_sanitized: bool
    └─ TaintPath.confidence: float
postcondition:
  - TaintAware frame'ler (SecurityFrame, ResilienceFrame, FuzzFrame)
    context.taint_paths'ı set_taint_paths() ile alır
  - SSRF, SQL injection, command injection yolları işaretlendi
on-success: → S7
on-error: → context.taint_paths = {}, devam (taint atlanır)
```

### S7: ProjectIntelligence Population

```yaml
id: S7
state: Frame'lere verilecek intelligence objesi derleniyor
actor: system
action: frame_runner.py (context injection bloğu)
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py:197-248
  - src/warden/pipeline/domain/intelligence.py
precondition:
  - S4, S5, S6 postcondition'ları karşılanmış
data-in:
  - context.code_graph: S4'ten
  - context.gap_report: S5'ten
  - context.ast_cache: AST parse sonuçları
data-out:
  - context.project_intelligence: ProjectIntelligence
    └─ entry_points: list[str] — main.py, app.py, wsgi.py vb.
    └─ input_sources: list[dict] — {"source", "file", "line"}
    └─ critical_sinks: list[dict] — {"sink", "type", "file", "line"}
    └─ auth_patterns: list[str] — @login_required vb.
    └─ total_files: int
    └─ primary_language: str
postcondition:
  - SecurityFrame ve ResilienceFrame LLM prompt'larına
    entry_points, critical_sinks inject edilir
  - Daha az false positive üretilir
on-success: → scan-pipeline S5 (Validation fazı)
on-error: → context.project_intelligence = None, frame'ler onsuz çalışır
```

### S8: LSP Chain Validation (opsiyonel)

```yaml
id: S8
state: Dil sunucusu ile sembol referansları doğrulanıyor
actor: system
action: LSPDiagnosticService.validate_chains_async(code_graph)
file:
  - src/warden/lsp/diagnostic_service.py
precondition:
  - S4 postcondition karşılanmış
  - config.lsp.enabled = true (default: false)
data-in:
  - context.code_graph: S4'ten
data-out:
  - context.chain_validation: ChainValidation
    └─ confirmed: int — LSP doğrulanan canlı semboller
    └─ unconfirmed: int — potansiyel ama doğrulanmayan
    └─ dead_symbols: list[str] — kesin ölü semboller
    └─ lsp_available: bool
  - .warden/intelligence/chain_validation.json (persist)
postcondition:
  - LSPAware frame'ler set_lsp_context() ile bu veriyi alır
on-success: → scan-pipeline S5
on-error: → context.chain_validation = None, devam (fail-open)
```

---

## Flow: classification-phase

```yaml
flow-id: classification-phase
purpose: >
  Her dosya için hangi validation frame'lerin çalışacağına karar verilir.
  Üç katmanlı cascade: cache hit → heuristic → LLM.
  Kararla birlikte suppression rule'ları ve öncelikler de üretilir.
actors:
  - system: ClassificationExecutor
  - llm: LLM provider (sadece katman 3'te)
```

### S1: Cache Check

```yaml
id: S1
state: Önceki classification sonucu cache'den aranıyor
actor: system
action: ClassificationCache.get(cache_key)
file:
  - src/warden/pipeline/application/executors/classification_executor.py:132-145
  - src/warden/classification/infrastructure/classification_cache.py
  - .warden/cache/classification_cache.json
precondition:
  - code_files ve available_frames hazır
data-in:
  - cache_key: hash(files_content + frame_ids + project_root)
data-out (hit):
  - cached_frames: list[str] — seçilmiş frame ID'leri
data-out (miss):
  - nothing
postcondition (hit):
  - selected_frames = cached_frames
  - LLM çağrısı atlandı
on-success (hit): → S-DONE (frame seçimi tamamlandı)
on-success (miss): → S2
```

### S2: Heuristic Pre-Classifier

```yaml
id: S2
state: Hızlı kural tabanlı frame seçimi yapılıyor
actor: system
action: HeuristicClassifier.classify_async()
file:
  - src/warden/classification/application/heuristic_classifier.py
precondition:
  - S1 cache miss
data-in:
  - code_files: CodeFile listesi
  - available_frame_ids: list[str]
  - context.project_type: S1 audit-context'ten
data-out:
  - heuristic_result.frames: list[str]
  - heuristic_result.confidence: float
postcondition:
  - confidence > 0.85 → LLM atlanır, heuristic seçim kullanılır
on-success (high confidence): → S4 (LLM atla)
on-success (low confidence): → S3
```

### S3: LLM Classification

```yaml
id: S3
state: LLM ile dosya içeriği analiz edilerek frame seçimi yapılıyor
actor: system → llm
action: LLMClassificationPhase.execute_async()
file:
  - src/warden/classification/application/llm_classification_phase.py
  - src/warden/classification/application/classification_prompts.py
precondition:
  - S2 confidence düşük (< 0.85)
  - LLM servisi mevcut
data-in:
  - code_files: dosya içerikleri (token-truncated)
  - available_frames: frame açıklamaları
  - context.project_type, context.framework: audit-context'ten
data-out:
  - llm_result.selected_frames: list[str]
  - llm_result.suppression_rules: list[dict]
    └─ {"pattern": "tests/*", "suppress": ["security"], "reason": str}
  - llm_result.priorities: dict[str, int] — frame öncelik override
  - llm_result.advisories: list[str]
  - llm_result.reasoning: str
postcondition:
  - selected_frames ⊆ available_frame_ids
  - Geçersiz frame ID'ler filtelendi
on-success: → S4
on-error: → default_frames = ["security", "orphan", "resilience"]
```

### S4: Cache Write & Result Publish

```yaml
id: S4
state: Seçim cache'e yazılıyor, context güncelleniyor
actor: system
action: ClassificationCache.put() + context güncelleme
file:
  - src/warden/pipeline/application/executors/classification_executor.py:210-240
precondition:
  - S2 veya S3 tamamlandı
data-in:
  - selected_frames: S2 veya S3'ten
  - suppression_rules: S3'ten (veya [])
data-out:
  - context.selected_frames: list[str] — Validation fazı bunu okur
  - context.suppression_rules: list[dict]
  - .warden/cache/classification_cache.json: güncellenmiş cache
postcondition:
  - context.selected_frames dolu
  - Sonraki scan aynı girdiyle cache hit alır
on-success: → scan-pipeline S5 (Validation fazı)
```

---

## Flow: frame-execution

```yaml
flow-id: frame-execution
purpose: >
  Tek bir frame, kendisine atanan dosyaları validate eder.
  Pre-rules → context inject → cache check → execute → post-rules
  sırasıyla çalışır. Her adım bağımsız hata alabileceği için
  fail-open tasarlanmıştır.
actors:
  - system: FrameRunner
  - frame: ValidationFrame subclass (SecurityFrame, OrphanFrame vb.)
  - llm: LLM provider (frame ihtiyacına göre)
```

### S1: Pre-Rules Check

```yaml
id: S1
state: Frame çalışmadan önce custom kurallar kontrol ediliyor
actor: system
action: RuleExecutor.execute_rules_async(frame_rules.pre_rules, files)
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py:371-401
precondition:
  - frame.frame_id config.frame_rules'te tanımlı (opsiyonel)
data-in:
  - frame_rules.pre_rules: list[CustomRule] — rules.yaml'dan
  - code_files: triage routing öncesi tüm dosyalar
data-out (ihlal yok):
  - nothing (devam)
data-out (blocker ihlal):
  - FrameResult(status="failed", metadata={"failure_reason": "pre_rules_blocker_violation"})
postcondition (ihlal yok):
  - Frame execution devam edecek
postcondition (blocker):
  - Frame çalışmadan "failed" döner
  - Post-rules, execute çalışmaz
on-success: → S2
on-error (blocker): → S-DONE (failed frame result)
```

### S2: Context Injection

```yaml
id: S2
state: Frame'e pipeline intelligence enjekte ediliyor
actor: system
action: frame.project_intelligence = ... + frame.set_taint_paths(...) vb.
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py:197-369
precondition:
  - S1 blocker yok
  - audit-context flow tamamlandı
data-in:
  - context.project_intelligence: audit-context S7'den
  - context.taint_paths: audit-context S6'dan (TaintAware frame ise)
  - context.chain_validation: audit-context S8'den (LSPAware frame ise)
  - context.findings: diğer frame'lerin önceki bulguları
data-out: (frame üzerinde attribute set edilir)
  - frame.project_intelligence: ProjectIntelligence | None
  - frame.prior_findings: list[Finding] (cross-frame awareness)
  - frame.taint_paths: dict | None (sadece TaintAware frame'ler)
  - frame.lsp_context: dict | None (sadece LSPAware frame'ler)
postcondition:
  - TaintAware frame → set_taint_paths() çağrılmış
  - LSPAware frame → set_lsp_context() çağrılmış
  - LLM prompt'larına entry_points ve critical_sinks inject edilecek
on-success: → S3
```

### S3: Findings Cache Lookup

```yaml
id: S3
state: Dosyanın önceki scan bulgularına bakılıyor
actor: system
action: FindingsCache.get_findings(frame_id, file_path, content)
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py:432-487
  - src/warden/pipeline/application/orchestrator/findings_cache.py
  - .warden/cache/findings_cache.json (max 500 entry, FIFO)
precondition:
  - S2 tamamlandı
  - findings_cache etkin (--no-cache yoksa)
data-in:
  - cache_key: "{frame_id}:{file_path}:{sha256(content)[:16]}"
data-out (hit):
  - cached_findings: list[Finding]
  - FrameResult döner, execute_async ATLANIR
data-out (miss):
  - nothing
postcondition (hit):
  - Dosya içeriği değişmemişse LLM çağrısı olmaz
on-success (hit): → S5 (post-rules)
on-success (miss): → S4
note: >
  Cache schema version farklıysa hit olmaz (invalidate).
  Limit: 500 entry, aşılınca en eski silinir (FIFO).
  File: .warden/cache/findings_cache.json
```

### S4: Frame Execute

```yaml
id: S4
state: Frame dosyayı analiz ediyor
actor: system → frame → llm
action: asyncio.wait_for(frame.execute_async(code_file, context=context), timeout)
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py:496-534
  - src/warden/validation/domain/frame.py (ValidationFrame ABC)
  - src/warden/validation/frames/{security,resilience,orphan,...}/
precondition:
  - S3 cache miss
  - timeout hesaplandı
data-in:
  - code_file: CodeFile (path, content, language)
  - context: PipelineContext (opsiyonel, signature check yapılır)
  - timeout: float — provider'a göre hesaplanmış
    └─ timeout_floor: 120s (ollama) | 10s (cloud)
    └─ timeout = max(floor, min(file_size/15000, 300))
data-out:
  - frame_result: FrameResult
    └─ frame_result.status: "passed" | "failed" | "warning"
    └─ frame_result.findings: list[Finding]
    └─ frame_result.duration: float
    └─ frame_result.is_blocker: bool
    └─ frame_result.metadata: dict — {"from_cache": bool, "is_degraded": bool}
postcondition:
  - frame_result.issues_found == len(frame_result.findings)
  - Başarılı ise FindingsCache'e yazılır
on-success: → S5
on-error (TimeoutError): → FrameResult(status="failed", findings=[])
on-error (Exception): → logged, FrameResult = None
```

### S5: Post-Rules Check

```yaml
id: S5
state: Frame çıktısı üzerinde custom post-rules uygulanıyor
actor: system
action: RuleExecutor.execute_rules_async(frame_rules.post_rules, files)
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py (~600+)
precondition:
  - S4 tamamlandı (veya S3 cache hit)
  - frame_rules.post_rules tanımlı (opsiyonel)
data-in:
  - frame_result: S4'ten
  - frame_rules.post_rules: list[CustomRule]
data-out (ihlal yok):
  - frame_result değişmez
data-out (blocker ihlal):
  - frame_result.status = "failed"
  - frame_result.is_blocker = True
postcondition:
  - frame_result final hali context'e yazılacak
on-success: → S6
```

### S6: Result Storage

```yaml
id: S6
state: Frame sonucu pipeline context'e kaydediliyor
actor: system
action: context.frame_results[frame.frame_id] = {...}
file:
  - src/warden/pipeline/application/orchestrator/frame_runner.py (~620+)
precondition:
  - S5 tamamlandı
data-in:
  - frame_result: S4-S5'ten
  - pre_violations, post_violations: S1 ve S5'ten
data-out:
  - context.frame_results[frame_id]: dict
    └─ "result": FrameResult
    └─ "pre_violations": list
    └─ "post_violations": list
  - context.findings: += frame_result.findings (aggregated)
postcondition:
  - scan-pipeline S6'da rapor bu veriyi okur
  - Suppression filter context.findings üzerinde çalışır
on-success: → frame-execution tamamlandı
```

---

## Kritik Veri Yapıları

### PipelineContext (tüm fazlar arası taşıyıcı)
```
context.pipeline_id        → str (UUID, scan ID)
context.project_root       → Path
context.llm_provider       → str ("ollama", "groq", ...)
context.llm_config         → Any | None (provider config)

# audit-context output'ları:
context.project_context    → ProjectContext (type, framework)
context.file_contexts      → dict[path, FileAnalysisResult]
context.dependency_graph_* → dict[path, list[path]]
context.triage_decisions   → dict[path, TriageDecision]
context.code_graph         → CodeGraph (sembol grafı)
context.gap_report         → GapReport (ölü semboller)
context.taint_paths        → dict[path, list[TaintPath]]
context.chain_validation   → ChainValidation | None
context.project_intelligence → ProjectIntelligence | None
context.ast_cache          → dict[path, AstResult]

# classification-phase output'ları:
context.selected_frames    → list[str]
context.suppression_rules  → list[dict]

# frame-execution output'ları:
context.frame_results      → dict[frame_id, dict]
context.findings           → list[Finding] (aggregated)
```

### Environment Variables (öncelik sırası)
```
WARDEN_LLM_PROVIDER        → provider override (groq, ollama, claude_code)
WARDEN_FAST_TIER_PRIORITY  → fast tier sırası (ollama,groq)
WARDEN_BLOCKED_PROVIDERS   → yasaklı provider'lar (deepseek,anthropic)
WARDEN_FILE_TIMEOUT_MIN    → per-file timeout floor override (saniye)
GROQ_API_KEY               → Groq auth
AZURE_OPENAI_API_KEY       → Azure OpenAI auth
CLAUDE_CODE_ENTRYPOINT     → Claude Code nested session detection
```

### Cache Dosyaları
```
.warden/cache/classification_cache.json  → frame seçim cache'i
.warden/cache/findings_cache.json        → bulgular cache'i (max 500 entry)
.warden/intelligence/code_graph.json     → sembol grafı
.warden/intelligence/gap_report.json     → boşluk analizi
.warden/intelligence/dependency_graph.json → import grafı
.warden/intelligence/chain_validation.json → LSP doğrulama
.warden/baseline/                        → baseline snapshot'ları
```

---

## Bilinen Gap'ler & Notlar

Öncelik: **CRITICAL** → kod yazılmadan okunmalı / **HIGH** → next sprint / **MEDIUM** → backlog

### Kapatılmış Gap'ler

| Gap ID | Açıklama | Commit |
|--------|----------|--------|
| DATA-GAP-CLOSED-1 | `context.llm_config` OrchestratedClient'ta None — `context.llm_provider` eklendi | a4e5eaf |
| DATA-GAP-CLOSED-2 | `FuzzFrame.from_json(content)` JSON string kabul etmiyordu — `json.loads()` eklendi | 0cf9bee |
| FLOW-GAP-CLOSED-1 | `ChaosFrame` 79cfad8'de kaldırıldı, ae2801c'de yanlışlıkla geri geldi | 13c7dd1 |
| FLOW-GAP-CLOSED-2 | Frame consistency check, `frame_rules` olmayan rules dosyasında yanlış uyarıyordu | 0cf9bee |

---

### Açık Gap'ler

#### DATA-GAP-1 — FrameResult tutarsızlığı (öncelik: HIGH)

```
Dosya: src/warden/validation/domain/frame.py:174
       src/warden/validation/frames/orphan/orphan_frame.py:164

Sorun: FrameResult(status="failed", findings=[], issues_found=0) kombinasyonu geçerli.
       Ancak status="failed" + findings=[] + is_blocker=False
       → findings_post_processor.py status'ü "passed"'e çeviriyor.
       Eğer durum "rule blocker violation" ise bu düzeltme gerçek hatayı gizler.

Beklenen: issues_found = len(findings) VEYA is_blocker=True
Gerçek:    İkisi birden False olabilir → silent status flip

Runtime:   Blocker kural ihlalleri "passed" görünür, CI bypass edilir.

Öneri:     FrameResult.issues_found'u @property yap → len(self.findings)
           VEYA factory method: FrameResult.blocker_violation(reason) vs FrameResult.failed(findings)
```

#### FLOW-GAP-1 — Suppression rules cache hit'te boş kalıyor (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/executors/classification_executor.py:141

Sorun: Classification cache hit veya heuristic shortcut durumunda
       context.suppression_rules = [] set ediliyor.
       LLM'den gelen suppression bilgisi cache'e yazılmıyor.
       Sonraki scan'de aynı dosya için suppression çalışmıyor.

Beklenen: Cache hit → önceki LLM suppression kararları da yüklensin
Gerçek:   Cache hit → suppression_rules=[] → tüm bulgular tekrar raporlanır

Runtime:  Scan 1: SQL injection suppressed
          Scan 2: Same file (cache hit) → SQL injection tekrar yeni bulgu

Data Chain:
  classification_cache.json → selected_frames SAKLAR
  classification_cache.json → suppression_rules SAKLAMAZ  ← GAP

Öneri:   ClassificationCache value'suna suppression_rules de ekle.
         get/put API'sini güncelle.
```

#### FLOW-GAP-2 — LLM response parsing tutarsızlığı (öncelik: MEDIUM)

```
Dosya: src/warden/validation/frames/property/property_frame.py:315
       (fuzz_frame.py'de düzeltildi ama property_frame.py'de eksik)

Sorun: BaseDomainModel.from_json(data) dict bekliyor.
       Bazı frame'ler json.loads yapmadan str content'i doğrudan geçiriyor.
       LLM provider'a göre content str | dict gelebiliyor.

Beklenen: Her from_json çağrısından önce isinstance(content, str) kontrolü
Gerçek:   property_frame.py'de eksik → parse error → bulgu düşer

Runtime:  LLM geçerli JSON döndürür ama bulgu üretilmez (silent fail).

Öneri:   _safe_parse_llm_response(content) → dict  utility'si
         src/warden/llm/utils.py'ye ekle, tüm frame'lerde kullan.
```

#### FLOW-GAP-3 — DependencyChecker boş dict/list'i "missing" sayıyor (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/dependency_checker.py:141

Sorun: _context_attr_exists() son kontrol:
       return not (isinstance(current, (list, dict)) and len(current) == 0)
       → Attribute VAR ama boşsa → False döner → frame skip edilir.

Beklenen: "exists" → attribute None değil (boş olması kabul edilebilir)
Gerçek:   Boş project_context={} → SpecFrame skip + yanıltıcı skip reason

Runtime:  "Required context 'project_context' is not available"
          hatası, attribute aslında mevcut ama boşken görünür.

Öneri:   Son satırı değiştir:
         return current is not None
         Boş-olmak kontrolünü "requires_nonempty_context" ile ayır.
```

#### FLOW-GAP-4 — Fortification linking ID mismatch (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/executors/fortification_executor.py:153-183

Sorun: LLM'e gönderilen issue.id ile LLM'den dönen fort.finding_id eşleşmeyebilir.
       LLM bazen ID'yi değiştiriyor veya yeni üretiyor.
       Eşleşmeyen fortification'lar sessizce drop ediliyor (unlinked).

Data Chain:
  issues[].id  →  (LLM)  →  fortifications[].finding_id
  EĞER finding_id yanlışsa → findings_map lookup miss → fix yok

Beklenen: Her fortification tam olarak bir finding'e bağlı
Gerçek:   unlinked_count > 0 → kullanıcı bazı fix'leri görmüyor

Runtime:  10 bulgu, 8 fix gösterilir. 2 fix "unlinked" loglanır, raporda yok.

Öneri:   LLM prompt'una "finding_id must EXACTLY match the input id" kısıtı ekle.
         Unlinked fortification'ları WARNING yerine ERROR logla.
         Post-LLM validation: len(linked) == len(issues) değilse retry.
```

#### RACE-GAP-1 — Suppression filter paralel execution'da paylaşılan listeyi mutate ediyor (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/orchestrator/suppression_filter.py:19-75
       src/warden/pipeline/application/orchestrator/frame_executor.py:150

Sorun: PARALLEL execution strategy'sinde birden fazla frame aynı
       context.findings listesine eş zamanlı erişiyor.
       SuppressionFilter bazı code path'lerde orijinal listeyi döndürüyor
       (findings boşsa: return findings — aynı referans).
       Paralel frame sonuçları bu referans üzerinden ekleniyor.

Data Chain:
  context.findings (shared ref)
      ↑ Frame A append
      ↑ Frame B append   ← concurrent, no lock
      ↓ SuppressionFilter(context.findings) → dönüşümde race

Beklenen: Thread-safe findings aggregation
Gerçek:   Intermittent data corruption / kayıp bulgular (PARALLEL mode)

Runtime:  Özellikle SecurityFrame + OrphanFrame + ResilienceFrame paralel
          çalışırken bulgu sayısı her scan'de farklı çıkabilir.

Öneri:   context._lock kullanımını suppression filter'a genişlet.
         SuppressionFilter hiçbir zaman orijinal listeyi döndürmesin:
         return findings[:] if not suppressions else filtered  # defensive copy
         context.findings append işlemlerini lock altına al.
```

#### SCHEMA-GAP-1 — findings_cache schema versiyonu manuel, auto-detect yok (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/findings_cache.py:33

Sorun: CACHE_SCHEMA_VERSION = 1 sabit olarak tanımlı.
       Finding dataclass alanları değiştiğinde developer version'ı
       manuel bump etmezse eski cache yanlış deserialize edilir.
       Sessiz eviction (benign) veya yanlış veri (malign) oluşabilir.

Beklenen: Schema değiştiğinde otomatik invalidation
Gerçek:   Manuel disiplin gerekiyor, CI'da yakalanmıyor

Runtime:  Development ortamında benign (cache miss → yeniden scan).
          CI'da: eski cache artifact yanlış Finding alanları → potential crash.

Öneri:   CACHE_SCHEMA_VERSION'ı Finding alanlarının hash'inden türet:
         import hashlib, inspect
         CACHE_SCHEMA_VERSION = hashlib.md5(
             str(inspect.getmembers(Finding)).encode()
         ).hexdigest()[:8]
```

#### DATA-GAP-2 — PipelineContext faz garantileri belgelenmemiş (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/domain/pipeline_context.py
       src/warden/pipeline/application/ (executor'lar)

Sorun: Hangi context field'ının hangi fazda doldurulduğu garantisi yok.
       Birçok yer getattr(context, "X", default) ile savunmacı okuyor.
       Bu, initialization bug'larını test'te sessizce geçiriyor.

Beklenen: "context.selected_frames sonraki fazda kesinlikle list[str]"
Gerçek:   Defensive coding → None veya [] default'u ile geçiştirilir

Faz garantisi haritası (şu an belirsiz):
  Faz 0 sonrası: project_context, file_contexts, triage_decisions
  Faz 0.7 sonrası: code_graph, gap_report
  Faz 2 sonrası: selected_frames, suppression_rules
  Faz 3 sonrası: frame_results, findings

Öneri:   Her faz executor'ın sonuna assertion bloğu ekle:
         assert context.selected_frames is not None, "CLASSIFICATION did not set selected_frames"
         VEYA PipelineContext'e phase_gate() metodu: context.assert_phase_complete("CLASSIFICATION")
```

---

### 4 Subagent Araştırmasından Yeni Gap'ler (2026-02-25)

Aşağıdaki gap'ler 4 paralel araştırma agentı tarafından tespit edildi.
Öncelik: **CRITICAL** → hemen düzelt / **HIGH** → next sprint / **MEDIUM** → backlog

---

#### CONFIG-GAP-1 — yaml_parser enable_llm / llm_provider alanlarını yok sayıyor (öncelik: CRITICAL)

```
Dosya: src/warden/config/yaml_parser.py:109,138-144

Sorun: parse_simple_format() sadece 4 settings alanı okuyor.
       config.yaml'daki enable_llm ve llm_provider alanları tamamen görmezden geliniyor.
       Kodda llm_provider="deepseek" hardcoded.

Beklenen: config.yaml settings.llm_provider → PipelineConfig.llm_provider
Gerçek:   Her zaman "deepseek" default değeri, kullanıcı konfigürasyonu yok sayılıyor

Data Chain:
  config.yaml settings.llm_provider
        ↓ parse_simple_format()
        X  (kayıp — okuma yok)
        ↓ PipelineConfig(llm_provider="deepseek")  ← hardcoded

Runtime:  Kullanıcı config.yaml'a provider: groq yazsa da pipeline deepseek
          kullanmaya çalışır. env var yoksa bağlantı hatası.

Öneri:    parse_simple_format():
          enable_llm=settings_data.get("enable_llm", True),
          llm_provider=settings_data.get("llm_provider", "deepseek"),
```

#### CONFIG-GAP-2 — yaml_parser.py'de timeout string → int coercion yok (öncelik: MEDIUM)

```
Dosya: src/warden/config/yaml_parser.py:140

Sorun: YAML'dan okunan timeout değeri string olabilir ("300" gibi).
       PipelineConfig int bekliyor; TypeError sessizce default'a düşer.

Beklenen: int(settings_data.get("timeout", 300))
Gerçek:   settings_data.get("timeout", 300) — string gelirse type error

Runtime:  config.yaml'da timeout: "300" (tırnaklı) → pipeline 300s değil
          default (None veya 0) timeout kullanır.
```

#### CONFIG-GAP-3 — Frame ID registry'ye karşı validate edilmiyor (öncelik: HIGH)

```
Dosya: src/warden/config/yaml_parser.py:164

Sorun: config.yaml'da tanımlı frame ID'leri (frames: [security, typo_frame])
       FrameRegistry'ye karşı validate edilmiyor.
       Yanlış yazılmış frame ID sessizce görmezden gelinir.

Beklenen: "typo_frame" → warning + kullanıcıya bildirim
Gerçek:   Frame kayıt eksikliği sessiz; scan aslında frame çalıştırmadan geçiyor

Runtime:  Kullanıcı "secuirty" yazsa scan yine "clean" döner.
          Configured frame count = 1 ama hiç validation olmaz.
```

---

#### SUPPRESSION-GAP-1 — fnmatch ** recursive pattern desteklemiyor (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/orchestrator/suppression_filter.py:61

Sorun: fnmatch.fnmatch() kullanılıyor — ** glob pattern desteği yok.
       suppressions: ["**/legacy/**/*.py"]  → hiçbir şeye eşleşmez.

Beklenen: pathlib.Path.match(pattern) — ** recursive desteği var
Gerçek:   fnmatch() yüzeysel match → **/alt/dosya.py eşleşmez

Runtime:  Subdirectory'deki dosyaları suppress etmek isteyen kullanıcı
          patternin sessizce çalışmadığını göremez; bulgular tekrar çıkar.

Öneri:    fnmatch.fnmatch(f_path, pattern)
          →  Path(f_path).match(pattern)
```

#### SUPPRESSION-GAP-2 — Suppressed bulgular için audit trail yok (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/orchestrator/suppression_filter.py:73

Sorun: Hangi bulgunun neden suppress edildiği kaydedilmiyor.
       context'e, log'a veya rapora yazılmıyor.

Beklenen: context.suppressed_findings: list[{finding_id, rule, reason}]
Gerçek:   Bulgu sessizce drop → ne kadar suppress edildiği bilinmiyor

Runtime:  "Neden bu CVE raporumda yok?" sorusu yanıtsız kalır.
          Yanlışlıkla eklenen suppression rule'u tespit edilemiyor.
```

#### SUPPRESSION-GAP-3 — İki suppression sistemi aynı anda çalışıyor (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/suppression_filter.py
       src/warden/pipeline/application/orchestrator/frame_runner.py (suppression/matcher.py)

Sorun: Config-based suppression (SuppressionFilter) ve LLM-based suppression
       (classification_executor'dan gelen suppression_rules) aynı anda çalışıyor.
       Formatları uyumsuz: biri dict, diğeri SuppressionEntry modeli.
       Hangisinin önce uygulandığı ve çakışmada ne olduğu belirsiz.

Runtime:  LLM suppress ettiği bulguyu config rule'u yeniden gösterebilir
          veya tam tersi. Davranış deterministik değil.
```

---

#### RULES-GAP-1 — Duplicate rule ID'leri sessizce drop ediliyor (öncelik: HIGH)

```
Dosya: src/warden/rules/infrastructure/yaml_loader.py:114

Sorun: .warden/rules/*.yaml dosyalarında aynı ID'ye sahip iki kural varsa
       ilki sessizce eziliyor veya ikisi de işlenmiyor.
       Hata/uyarı log'u yok.

Beklenen: DuplicateRuleError veya en azından warning log
Gerçek:   Sessiz drop → kullanıcı hangi kuralın aktif olduğunu bilmiyor

Runtime:  my_rules.yaml + security_rules.yaml aynı ID'yi tanımlarsa
          biri çalışmaz, neden bilinmez.
```

#### RULES-GAP-2 — İki incompatible CustomRule sınıfı (öncelik: HIGH)

```
Dosya: src/warden/config/domain/models.py (Panel format)
       src/warden/rules/domain/models.py (project config format)

Sorun: İki ayrı CustomRule dataclass var, field'ları uyumsuz.
       Frame runner hangisini kullandığına göre davranış değişiyor.
       Merge stratejisi belgelenmemiş.

Data Chain:
  rules.yaml → yaml_loader → rules/domain/models.CustomRule
  config.yaml (nodes format) → yaml_parser → config/domain/models.CustomRule
  frame_runner.py:139 → hangisi?

Runtime:  frame_runner PipelineConfig.frame_rules kullanıyor (config format).
          rules.yaml kuralları config.frame_rules'e dönüştürülüyorsa field mapping hatası.
          Dönüştürülmüyorsa rules.yaml pre/post kuralları çalışmıyor.
```

#### RULES-GAP-3 — Pre/post rules tüm dosyaları görüyor, frame sadece triage filtreli alt kümeyi (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/orchestrator/frame_runner.py:137-147, 782

Sorun: Pre-rules triage öncesi TÜM dosyalar üzerinde çalışır.
       Frame execute_async ise sadece triage-filtreli (FAST/MIDDLE/SLOW) dosyalar görür.
       Post-rules da triage filtreli dosyaları görür.
       Pre-rules'un gördüğü ile frame'in gördüğü dosya seti farklı.

Senaryo:
  Pre-rule: "auth.py'de SECRET var ise blocker"
  Triage: auth.py → SLOW lane (ama scan başka frame'e atandı)
  Frame: auth.py işlenmedi → pre-rule ihlali hayalet veri

Runtime:  Pre-rule blocker violation üretir ama frame bulgu bulamaz →
          FrameResult inconsistency (status=failed, findings=[]).
```

---

#### FRAME-GAP-1 — Finding ID'leri index tabanlı: scan arası deduplication bozuk (öncelik: HIGH)

```
Dosya: src/warden/validation/frames/orphan/orphan_frame.py:634
       src/warden/validation/frames/architecture/architecture_frame.py:242-260

Sorun:
  OrphanFrame:       id=f"{frame_id}-{orphan_type}-{i}"     ← enumerate index
  ArchitectureFrame: id=f"{frame_id}-broken-import-{idx}"   ← enumerate index

  Scan 1: orphans=[func_a, func_b] → IDs: orphan-0, orphan-1
  Scan 2: orphans=[func_b]         → IDs: orphan-0
  → findings_cache'de orphan-0 = farklı fonksiyon!

Beklenen: id=f"{frame_id}-{orphan_type}-{line_number}"  (stable, content-based)
Gerçek:   Index-based ID → cross-scan dedup bypass → duplicate findings cache miss

Runtime:  SARIF report'ta aynı sorun farklı ID'lerle tekrar görünür.
          Baseline tracking bozulur: "yeni" bulgu ama aslında aynı sorun.
```

#### FRAME-GAP-2 — 6 frame context parametresiz: project intelligence ulaşamıyor (öncelik: MEDIUM)

```
Dosya: antipattern_frame.py:110, gitchanges_frame.py:94, property_frame.py:96,
       spec_frame.py:345, orphan_frame.py:200, fuzz_frame.py:72

Sorun: execute_async(self, code_file) — context parametresi yok.
       frame_runner.py:441 signature check ile mitigate edilmiş (crash yok).
       Ama bu frame'ler şunlara ulaşamıyor:
         - project_intelligence (entry_points, critical_sinks)
         - prior_findings (cross-frame dedup)
         - gap_report, code_graph (architecture context)
         - chain_validation (dead symbol verisi)

Beklenen: Tüm frame'ler context=None optional param ile project intel alabilmeli
Gerçek:   6 frame "kör" çalışıyor → daha fazla false positive, daha az context

Öneri:    execute_async(self, code_file, context=None) imzası ekle (backward compat).
```

#### FRAME-GAP-3 — SpecFrame _create_skip_result duration=0.0 hardcoded (öncelik: MEDIUM)

```
Dosya: src/warden/validation/frames/spec/spec_frame.py:604

Sorun: _create_skip_result() her zaman duration=0.0 döndürüyor.
       start_time parametresi almıyor.
       Pipeline metrics'te SpecFrame skip süresi kayıp.

Runtime:  LLM Performance Summary'de SpecFrame 0s görünür,
          gerçek skip maliyeti (config validation, platform check) gizlenir.
```

---

#### LLM-GAP-1 — TokenBucketLimiter manual lock release/acquire: deadlock riski (öncelik: CRITICAL)

```
Dosya: src/warden/llm/rate_limiter.py:51-78

Sorun:
  async with self._lock:        ← context manager acquire
      ...
      self._lock.release()      ← MANUAL release — context manager biliyor mu?
      await asyncio.sleep(wait)
      await self._lock.acquire()
  # context manager __exit__ tekrar release() → double-release

Beklenen: asyncio.Lock doğru kullanımı: manual acquire/release olmadan
Gerçek:   Context manager + manual release/acquire → lock state bozulabilir
          Concurrent requests → token state inconsistent

Runtime:  Rate-limited scan'lerde (Groq, OpenAI) concurrent LLM çağrıları
          deadlock'a girebilir veya rate limit bypasslanabilir.
```

#### LLM-GAP-2 — Provider-level circuit breaker yok (öncelik: HIGH)

```
Dosya: src/warden/llm/providers/ (tüm provider'lar)
       (ResilienceFrame'de frame-level CB var ama provider'larda yok)

Sorun: Bir provider 3+ kez başarısız olursa otomatik "open" state yok.
       Her request yeniden deneniyor, her seferinde timeout bekliyor.

Beklenen: Provider fail threshold → circuit open → fallback without wait
Gerçek:   Provider fail → retry (N kez) → her seferinde full timeout

Runtime:  Groq down → 5 frame × 30s timeout = 150s bekleme,
          sonra fallback. Tüm pipeline bloklanır.

Not:      ResilienceFrame'de frame-level CB mevcut (3 fail → 5dk open).
          Aynı pattern diğer frame'lere ve provider seviyesine taşınmalı.
```

#### LLM-GAP-3 — Ollama non_retryable flag @resilient decorator tarafından görmezden geliniyor (öncelik: MEDIUM)

```
Dosya: src/warden/llm/providers/ollama.py
       src/warden/llm/ (resilience decorator)

Sorun: ModelNotFoundError.non_retryable = True tanımlı ama
       @resilient decorator bu flag'i kontrol etmiyor.
       Model bulunamadığında retry yapılıyor → 60s+ gecikme.

Beklenen: non_retryable=True → immediate fail, retry yok
Gerçek:   @resilient retry_max_attempts kez deneniyor (her biri 30s timeout)

Runtime:  Kurulu olmayan model → 3 retry × 30s = 90s gecikme.
          (Kısmen fixed: _missing_models cache ile; ama @resilient bypass edilemiyor)
```

#### LLM-GAP-4 — Groq 429 rate limit immediate failure, backoff yok (öncelik: HIGH)

```
Dosya: src/warden/llm/providers/groq.py:35-111

Sorun: 429 (Too Many Requests) alındığında LlmResponse(success=False) döner.
       asyncio.sleep() veya Retry-After header'ı yok.
       GlobalRateLimiter'da Groq "default" bucket kullanıyor (doğru bucket değil).

Data Chain:
  GlobalRateLimiter.acquire("default")  ← "groq" değil, yanlış bucket
  → Groq RPM limit kontrolü etkin değil
  → 429 anında fallback → orchestrated smart tier
  → smart tier de Groq ise → 429 cascades

Runtime:  Yüksek yükte tüm Groq tier'ı 429 → smart tier de Groq ise
          tüm LLM çağrıları başarısız → bulgular üretilmiyor.
```

#### LLM-GAP-5 — Metrics frame_scope kullanılmıyor: tüm kayıtlar "_unattributed" (öncelik: MEDIUM)

```
Dosya: src/warden/llm/metrics.py:64-87

Sorun: LLMMetricsCollector.frame_scope(name) context manager mevcut.
       Ama hiçbir frame bunu kullanmıyor (grep: 0 sonuç).
       Tüm LLM request'leri "_unattributed" frame altında kaydediliyor.

Beklenen: SecurityFrame LLM maliyeti, OrphanFrame LLM maliyeti ayrı görünür
Gerçek:   LLM Performance Summary'de frame attribution yok,
          hangi frame ne kadar LLM harcadığı bilinmiyor

Runtime:  Optimizasyon için hangi frame'in LLM'i çok kullandığı tespit edilemiyor.
```

---

#### CACHE-GAP-1 — findings_cache remediation/exploit_evidence/machine_context alanlarını drop ediyor (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/findings_cache.py:217-221

Sorun: Finding serialize edilirken nested field'lar (remediation, exploit_evidence,
       machine_context) kaydedilmiyor veya None serialize edilmiyor.
       Cache replay'de bu field'lar boş gelir.

Beklenen: Tüm Finding field'ları cache round-trip'ten sağlam geçmeli
Gerçek:   Cache hit sonrası finding.remediation = None (orijinalde dolu olsa bile)

Runtime:  "Nasıl düzeltirim?" önerisi cache'den dönen bulgularda yok.
          Fortification linking yanlış çalışabilir (machine_context eksik).
```

#### CACHE-GAP-2 — Triage cache schema versiyonu yok (öncelik: MEDIUM)

```
Dosya: src/warden/analysis/application/triage_cache.py

Sorun: findings_cache CACHE_SCHEMA_VERSION = 1 tanımlı (kısmi koruma var).
       Triage cache'de hiç schema versiyonlama yok.
       TriageDecision alanları değişirse eski cache stale kalır.

Runtime:  Triage yükseltmesi sonrası eski kararlar (FAST/MIDDLE/SLOW)
          yeni logic yerine replay edilir → yanlış frame routing.
```

#### CACHE-GAP-3 — Custom frame'ler CACHEABLE_FRAME_IDS'de değil (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/findings_cache.py:38-48

Sorun: CACHEABLE_FRAME_IDS sabit listesi sadece built-in frame'leri içeriyor.
       .warden/frames/ ile yüklenen hub/custom frame'ler bu listede yok.
       Custom frame bulguları asla cache'lenmez.

Beklenen: Hub/custom frame'ler de cache'lenmeli
Gerçek:   Custom frame her scan'de LLM çağrısı yapıyor (cache bypass)

Runtime:  Custom frame'i olan projeler incremental scan hızından yararlanamıyor.
```

---

#### EXEC-GAP-1 — Fortification executor raw findings fallback kullanıyor (öncelik: HIGH)

```
Dosya: src/warden/pipeline/application/executors/fortification_executor.py:66-75

Sorun:
  raw_findings = getattr(context, "validated_issues", [])
  if not raw_findings:
      raw_findings = getattr(context, "findings", [])  ← suppressed/raw fallback

  validated_issues result_aggregator tarafından doldurulmazsa
  fortification suppress edilmiş veya ham bulgular üzerinde çalışır.

Beklenen: validated_issues boşsa → fortification atla, hata log'la
Gerçek:   Ham findings'e fallback → suppress edilmesi gereken bulgular için
          fix üretilir; kullanıcıya anlamsız patch gelir

Runtime:  "Bu bulgu suppress edildi" denen şey için fix önerisi çıkabilir.
          Fortification kalitesi tahmin edilemez hale gelir.
```

#### EXEC-GAP-2 — Parallel frame execution fail-fast blocker'ı bekletmiyor (öncelik: MEDIUM)

```
Dosya: src/warden/pipeline/application/orchestrator/frame_executor.py:255

Sorun: asyncio.gather(..., return_exceptions=True) tüm frame'leri tamamlanana kadar bekler.
       Bir frame blocker ihlali üretse bile diğer frame'ler çalışmaya devam eder.

Beklenen: fail_fast=True → blocker violation → remaining frames cancel
Gerçek:   Tüm frame'ler çalışır, sonra blocker kontrol edilir

Runtime:  10 frame × 30s = 300s harcandıktan sonra "ilk frame blocker'dı"
          bilgisi gelir. Erken çıkış yapılabilirdi.
```
