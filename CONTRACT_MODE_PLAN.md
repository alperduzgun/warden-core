# Warden Contract Mode — Uygulama Planı

> **Temel İçgörü:**
> Warden'da intent yeteneği zaten var — LLM + confidence scoring (< 0.5 → skip) +
> `project_intelligence` + `prior_findings` injection. Contract mode için eksik olan
> tek şey **DDG** (Data Dependency Graph): proje genelinde `context.X` field'larının
> kim yazdığını, kim okuduğunu AST'den çıkaran altyapı.
>
> İki simülasyon çalıştırıldı. 3/4 bilinen gap tespit edildi. 3 yeni STALE_SYNC
> adayı keşfedildi. Yaklaşım çalışıyor.
>
> **Kullanıcı config yok. Her şey otomatik.**

---

## Gap Taksonomisi

| Gap | Tespit Yöntemi | LLM? | Güven | Simülasyon |
|-----|---------------|------|-------|------------|
| `DEAD_WRITE` | DDG: WriteNode var, ReadNode sıfır | Hayır | Yüksek | ✓ çalışıyor |
| `MISSING_WRITE` | DDG: ReadNode var, WriteNode sıfır | Hayır | Yüksek | ✓ algoritma çalışıyor; DEP-GAP-1/INJECT-GAP-1 FP çıktı (PIPELINE_CTX_NAMES fix ile kapandı) |
| `NEVER_POPULATED` | DDG: `Optional[X]` context field, WriteNode sıfır | Hayır | Çok yüksek | — |
| `STALE_SYNC` | DDG co-write pattern → LLM verdict | Evet | Orta | ✓ BASELINE-GAP-2 + 3 yeni aday |
| `PROTOCOL_BREACH` | AST: mixin impl var, frame_runner injection yok | Hayır | Yüksek | — |
| `ASYNC_RACE` | AST: `asyncio.gather` + paylaşılan mutable + Lock yok | Evet | Orta | — |
| `INTENT_GAP` | LLM only — veri akıyor ama amacına ulaşmıyor | Evet | Düşük | PIPELINE-GAP-1 bu kategoride |

> **`INTENT_GAP` nedir?**
> `context.triage_decisions` hem yazılıyor hem okunuyor — DDG açısından sağlıklı.
> Ama triage sonuçları frame seçimini etkilemiyor. Bu semantic bir gap, DDG'nin
> göremeyeceği türden. Sadece LLM tespit edebilir (Aşama 4+ kapsamında).

---

## Mimari

```
  Pre-Analysis
  execute_pre_analysis_async()
        │
        ▼
  context.ast_cache          dict[file_path → ParseResult]   (mevcut, Phase 0)
        │
        │  DataDependencyBuilder(ast_cache).build()          (Aşama 1, yeni)
        ▼
  DataDependencyGraph
    ├── writes[field] → [WriteNode(file, line, func, conditional)]
    └── reads[field]  → [ReadNode(file, line, func)]
        │
        ├── dead_writes()           → DEAD_WRITE findings   (DeadDataFrame, no LLM)
        ├── missing_writes()        → MISSING_WRITE findings (DeadDataFrame, no LLM)
        ├── never_populated()       → NEVER_POPULATED        (DeadDataFrame, no LLM)
        └── co_write_candidates()   → LLM'e gönderilir       (StaleSyncFrame)
                                            │
                                    Mevcut LLM altyapısı
                                    · security/frame.py semantic_context pattern
                                    · _confidence_rules.txt  (< 0.5 → skip)
                                    · project_intelligence
                                    · prior_findings
```

---

## Simülasyon Bulguları (Kanıt)

İki simülasyon çalıştırıldı (Warden kaynak kodu, 494 dosya):

### Doğrulanan Gap'ler

| Gap ID | Field | Tespit |
|--------|-------|--------|
| `DEP-GAP-1` | `context.dependency_graph_forward` | **False Positive** — `pre_analysis_phase.py:382`'de `pipeline_context.X[key]=` ile yazılıyor; DDGVisitor kaçırıyor (`pipeline_context: Any` adı/tipi tanınmıyor) |
| `INJECT-GAP-1` | `context.code_graph` | **False Positive** — `pre_analysis_phase.py:526`'da `pipeline_context.code_graph = code_graph` ile yazılıyor; DDGVisitor kaçırıyor |
| `BASELINE-GAP-2` | `context.validated_issues` | STALE_SYNC candidate ✓ — **#124 tarafından da doğrulanıyor** (baseline filtering sonrası `validated_issues` güncellenmez → fortification stale data kullanır; ayrı bug fix path) |
| `PIPELINE-GAP-1` | `context.triage_decisions` | Intent-level → LLM gerekiyor |

> **Kök Neden:** `pre_analysis_phase.py::execute_async` imzası `pipeline_context: Any | None = None` kullanıyor.
> DDGVisitor iki koşuldan birini arar: (1) annotation `PipelineContext` ya (2) isim `context`/`ctx`.
> `pipeline_context: Any` her ikisini de kaçırıyor → bu dosyadan gelen tüm write'lar görünmez.

### Yeni Keşfedilen STALE_SYNC Adayları

```
context.findings + context.validated_issues          (3 fonksiyonda birlikte)
context.false_positives + context.validated_issues   (2 fonksiyonda birlikte)
context.false_positives + context.findings           (2 fonksiyonda birlikte)
context.classification_reasoning + context.selected_frames
context.findings + context.frame_results
```

Bu 5 çift LLM'e gönderilecek. LLM her birini bağımsız değerlendirecek.

### False Positive Kaynakları (Simülasyondan Öğrenildi)

| Kaynak | Örnek | Çözüm |
|--------|-------|-------|
| Typer Context | `context.args`, `context.invoked_subcommand` | `cli/commands/` dışla |
| gRPC Context | `context.set_code`, `context.set_details` | `grpc/generated/` + `grpc/servicer/` dışla |
| Semantic Search Context | `context.chunk_count`, `context.query_text` | `semantic_search/` dışla |
| PipelineContext metodları | `context.get_summary`, `context.add_phase_result` | Method blacklist |
| Dict erişimi | `context.get(key)` → `.get` attr | Attr blacklist |
| Class sabitleri | `context.MAX_CALLERS_IN_CONTEXT` | ALL_CAPS filtresi |
| Subscript yazma | `context.ast_cache[path] = result` | Subscript write visitor |
| Constructor field'ları | `pipeline_id`, `started_at`, `project_root` | Dataclass `__init__` parametrelerini "yazılmış" say |
| **`pipeline_context: Any` adlandırması** | `pipeline_context.code_graph`, `pipeline_context.dependency_graph_forward[k]` | `PIPELINE_CTX_NAMES` setine `"pipeline_context"` ekle — `pre_analysis_phase.py` bu adı kullanıyor |

---

## Aşama 1 — DDG Core (Domain + Builder)

> **Zorluk:** ⭐⭐ | **Risk:** Düşük — yeni dosyalar, mevcut koda dokunmuyor | **Bağımlılık:** Yok

### 1.1 Domain Model

**Konum:** `src/warden/analysis/domain/data_dependency_graph.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class WriteNode:
    field_name: str        # "context.validated_issues"
    file_path: str         # relative to project root
    line: int
    writer_func: str       # "result_aggregator.store_validation_results"
    is_conditional: bool   # if/else bloğu içinde mi?

@dataclass
class ReadNode:
    field_name: str
    file_path: str
    line: int
    reader_func: str

@dataclass
class DataDependencyGraph:
    writes: dict[str, list[WriteNode]] = field(default_factory=lambda: defaultdict(list))
    reads:  dict[str, list[ReadNode]]  = field(default_factory=lambda: defaultdict(list))
    # Dataclass constructor'da set edilen field'lar (subscript/init yazmaları dahil)
    init_fields: set[str] = field(default_factory=set)

    def dead_writes(self) -> dict[str, list[WriteNode]]:
        """WriteNode var, ReadNode sıfır — DEAD_WRITE."""
        return {f: w for f, w in self.writes.items() if f not in self.reads}

    def missing_writes(self) -> dict[str, list[ReadNode]]:
        """ReadNode var, WriteNode sıfır, constructor'da da yok — MISSING_WRITE."""
        return {
            f: r for f, r in self.reads.items()
            if f not in self.writes and f not in self.init_fields
        }

    def never_populated(self) -> list[str]:
        """Optional[X] tipli context field, hiç WriteNode yok."""
        # DeadDataFrame PipelineContext field listesiyle çapraz kontrol eder
        ...

    def co_write_candidates(self) -> dict[tuple[str, str], list[str]]:
        """
        {(field_a, field_b): [func_key, ...]}
        N-1 yerde birlikte yazılan ama bazı fonksiyonlarda ayrışan çiftler.
        StaleSyncFrame'in LLM'e gönderdiği ham veri.
        Minimum 2 ortak fonksiyon gerekir.
        """
        ...
```

### 1.2 DataDependencyBuilder

**Konum:** `src/warden/analysis/application/data_dependency_builder.py`

`CodeGraphBuilder` pattern'i — `context.ast_cache`'i alır, yeniden parse etmez.

```python
# Simülasyondan türetilmiş tam filtre spesifikasyonu:

EXCLUDED_DIR_PATTERNS = [
    "cli/commands/",    # Typer Context
    "grpc/generated/",  # gRPC generated stubs
    "grpc/servicer/",   # gRPC servicer mixins (simülasyon v2'de tespit edildi)
    "semantic_search/", # Custom context nesnesi
]

EXCLUDED_ATTRS = {
    # Pydantic / BaseDomainModel metodları
    "dict", "model_dump", "to_json", "to_llm_context", "json", "copy",
    "schema", "validate", "update_forward_refs",
    # PipelineContext metodları
    "get_summary", "get_context_for_phase", "get_llm_context_prompt",
    "add_phase_result", "add_llm_interaction",
    # Dict-like erişim
    "get", "items", "values", "keys", "pop", "clear",
    # Append-style yazmalar — WriteNode olarak ayrıca handle edilir
    "append", "extend", "update", "add",
}

WRITE_CALL_ATTRS = {"append", "extend", "update", "add"}  # context.X.append(y) → write

class DataDependencyBuilder:
    def __init__(self, ast_cache: dict, project_root: Path | None = None):
        self._ast_cache = ast_cache
        self._project_root = project_root
        self._graph = DataDependencyGraph()

    def build(self) -> DataDependencyGraph:
        # 1. PipelineContext dataclass constructor field'larını "yazılmış" kaydet
        self._register_init_fields()
        # 2. Her dosyayı ziyaret et
        for file_path, parse_result in self._ast_cache.items():
            if self._is_excluded(file_path):
                continue
            ast_root = self._extract_ast_root(parse_result)
            DDGVisitor(file_path, self._graph).visit(ast_root)
        return self._graph

    def _register_init_fields(self):
        """
        PipelineContext'in dataclass field'larını parse et.
        pipeline_id, started_at, project_root gibi constructor'da
        set edilenler "yazılmış" kabul edilir.
        """
        ctx_file = (self._project_root or Path()) / "pipeline/domain/pipeline_context.py"
        # ast.parse → ClassDef → fields with no default → init_fields
        ...

    def _is_excluded(self, file_path: str) -> bool:
        return any(pat in file_path for pat in EXCLUDED_DIR_PATTERNS)
```

**DDGVisitor'ın izlediği AST node'ları:**

```python
class DDGVisitor(ast.NodeVisitor):

    # Kabul edilen PipelineContext parametre adları.
    # pre_analysis_phase.py "pipeline_context: Any" kullandığından genişletildi.
    PIPELINE_CTX_NAMES = {"context", "ctx", "pipeline_context", "pipe_ctx"}

    def _extract_pipeline_ctx_params(self, node) -> set[str]:
        """
        Bu fonksiyonun PipelineContext tipli parametre adlarını döndür.
        Koşullar (herhangi biri yeterliydi):
          1. Annotation adı "PipelineContext" içeriyor (str/Subscript kontrol)
          2. Parametre adı PIPELINE_CTX_NAMES içinde

        Neden genişletildi: pre_analysis_phase.py::execute_async imzası
        `pipeline_context: Any | None = None` kullanıyor. Ne tip ne isim
        önceki kuralla eşleşiyordu → code_graph + dependency_graph_forward
        tüm write'ları görünmez oluyordu (false positive MISSING_WRITE).
        """

    def visit_Assign(self, node):
        # context.X = value → WriteNode
        # context.ast_cache[key] = value → subscript write → WriteNode for ast_cache

    def visit_AugAssign(self, node):
        # context.X += value → WriteNode

    def visit_Attribute(self, node):
        # context.X (Load) → ReadNode
        # ALL_CAPS attr → skip (class sabiti)
        # EXCLUDED_ATTRS → skip

    def visit_Call(self, node):
        # context.X.append(y) → WriteNode for context.X
```

### 1.3 Testler

```
tests/analysis/data_dependency/
  test_data_dependency_graph.py       — dead_writes(), missing_writes(), co_write_candidates()
  test_data_dependency_builder.py     — filtreler, AST → doğru node'lar
  test_ddg_filter.py                  — excluded dirs, method blacklist, ALL_CAPS, subscript
  fixtures/
    dead_write_fixture.py             — context.X yazılmış, hiç okunmuyor
    missing_write_fixture.py          — context.X okunuyor, hiç yazılmıyor
    stale_sync_fixture.py             — A+B 3/4 yerde birlikte, 1 yerde ayrışıyor
    false_positive_fixtures/
      typer_context_fixture.py        — context.args, context.invoked_subcommand
      grpc_context_fixture.py         — context.set_code, context.set_details
      method_call_fixture.py          — context.get_summary(), context.dict()
```

### Done Kriteri

```
DataDependencyBuilder(ast_cache).build() üzerinde:

  dead_write_fixture.py:
    → ddg.dead_writes() = {"context.unused": [WriteNode(...)]}
    → ddg.missing_writes() = {}

  stale_sync_fixture.py:
    → ddg.co_write_candidates() = {
        ("context.findings", "context.validated_issues"): ["func_a", "func_b", "func_c"]
      }

  false_positive_fixtures/:
    → ddg.dead_writes() = {}   (hiç false positive yok)
    → ddg.missing_writes() = {}

Gerçek warden kaynak kodu üzerinde (PIPELINE_CTX_NAMES fix sonrası):
    → context.dependency_graph_forward → WriteNode var (pre_analysis_phase.py:382, pipeline_context adıyla)
    → context.code_graph               → WriteNode var (pre_analysis_phase.py:526, pipeline_context adıyla)
    → context.validated_issues çifti   → co_write_candidates'da var

  NOT: PIPELINE_CTX_NAMES fix öncesi bu ikisi false positive MISSING_WRITE
  üretiyordu. Fix sonrası sadece gerçek gap'ler raporlanmalı.

Tüm unit testler pass.
```

---

## Aşama 2 — DDG Service + Pipeline Entegrasyonu

> **Zorluk:** ⭐⭐ | **Risk:** Düşük-Orta — 5 dosyaya küçük ekleme | **Bağımlılık:** Aşama 1

### 2.1 PipelineConfig

**`src/warden/pipeline/domain/models.py`** — `ci_mode` satırının yanına:

```python
ci_mode: bool = False
contract_mode: bool = False  # Yeni — data flow contract analysis (--contract-mode)
```

### 2.2 DataDependencyService

**`src/warden/analysis/services/data_dependency_service.py`**

`_populate_taint_paths_async` (satır 350–375) pattern'ini birebir kopyala:

```python
class DataDependencyService:
    def __init__(self, project_root: Path): ...

    async def analyze_all_async(
        self,
        ast_cache: dict[str, Any],
    ) -> DataDependencyGraph:
        builder = DataDependencyBuilder(ast_cache, self._project_root)
        return builder.build()  # sync, CPU-bound ama küçük codebases'de sorun değil
```

### 2.3 DataFlowAware Mixin

**`src/warden/validation/domain/mixins.py`** — dosyanın sonuna ekle:

```python
class DataFlowAware(ABC):
    """Frames that consume DataDependencyGraph data."""

    @abstractmethod
    def set_data_dependency_graph(self, ddg: "DataDependencyGraph") -> None: ...
```

### 2.4 PipelineContext

**`src/warden/pipeline/domain/pipeline_context.py`** — satır 146 sonrası:

```python
code_graph: Any | None = None
gap_report: Any | None = None
chain_validation: Any | None = None
data_dependency_graph: Any | None = None  # DataDependencyGraph (--contract-mode)
```

### 2.5 frame_runner.py

**`src/warden/pipeline/application/orchestrator/frame_runner.py`**
Mevcut TaintAware bloğunun (satır 334) hemen altına:

```python
if isinstance(frame, DataFlowAware):
    if hasattr(context, "data_dependency_graph") and context.data_dependency_graph:
        frame.set_data_dependency_graph(context.data_dependency_graph)
        logger.debug("ddg_injected", frame_id=frame.frame_id)
```

### 2.6 pipeline_phase_runner.py

**`src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py`**
Satır 72 (`await self._populate_taint_paths_async(...)`) hemen altına:

```python
# Phase 0.6: Data Dependency Graph (yalnızca --contract-mode)
if getattr(self.config, "contract_mode", False):
    await self._populate_data_dependency_graph_async(context)
```

```python
# Yeni private method — _populate_taint_paths_async (satır 350) ile aynı yapı:
async def _populate_data_dependency_graph_async(
    self, context: PipelineContext
) -> None:
    """Build DataDependencyGraph from ast_cache. Fail-open."""
    try:
        from warden.analysis.services.data_dependency_service import DataDependencyService
        service = DataDependencyService(project_root=self._project_root)
        # analyze_all_async → builder.build() çağırır (sync ama küçük codebase'de sorun değil)
        # _populate_taint_paths_async ile aynı async pattern:
        context.data_dependency_graph = await service.analyze_all_async(context.ast_cache)
        logger.info("ddg_populated", fields=len(context.data_dependency_graph.writes))
    except Exception as e:
        logger.warning("ddg_failed", error=str(e))
        # fail-open: DDG olmasa da pipeline durmuyor
```

### 2.7 bridge.py + scan.py

**`src/warden/cli_bridge/bridge.py`** — `ci_mode` satırlarını (215, 229–230) model al.
Asıl entry point `execute_pipeline_stream_async`'tır (`scan_async` legacy compat katmanıdır,
`scan.py` doğrudan `execute_pipeline_stream_async` çağırır):

```python
async def execute_pipeline_stream_async(
    self,
    ...,
    ci_mode: bool = False,
    contract_mode: bool = False,   # ← ekle
) -> ...:
    if ci_mode:
        self.orchestrator.config.ci_mode = True
    if contract_mode:
        self.orchestrator.config.contract_mode = True  # ← ekle
```

**`src/warden/cli/commands/scan.py`** — mevcut flag'lerin yanına (scan.py:762'deki
`bridge.execute_pipeline_stream_async(...)` çağrısına da `contract_mode=contract_mode` geçirilmeli):

```python
contract_mode: bool = typer.Option(
    False, "--contract-mode",
    help="Run data flow contract analysis (DEAD_WRITE, MISSING_WRITE, STALE_SYNC)",
),
```

### Done Kriteri

```
warden scan --contract-mode . (henüz frame yok)
  → context.data_dependency_graph is not None
  → ddg.missing_writes() içinde context.dependency_graph_forward var
  → frame_runner DataFlowAware frame'e inject etmeye hazır
  → Mevcut tüm testler pass (regression yok)
```

---

## Aşama 3 — DeadDataFrame + `--contract-mode`

> **Zorluk:** ⭐⭐ | **Risk:** Düşük — yeni frame, additive | **Bağımlılık:** Aşama 2
> **İlk kullanıcıya görünen değer bu aşamada.**

### Frame

**`src/warden/validation/frames/dead_data/dead_data_frame.py`**

`ArchitectureFrame` (satır 170–263) clone. LLM yok — saf DDG.

Dikkat: mevcut pattern'den birebir alınacak değerler:
- `category = FrameCategory.GLOBAL` (`ARCHITECTURE` yok, panel TS sync)
- `status = "passed"` / `"failed"` (string, enum değil — satır 205, 227)
- `is_blocker = False` (tüm dead data bulgular non-blocker)
- `duration = time.perf_counter() - start_time`

```python
class DeadDataFrame(ValidationFrame, DataFlowAware):
    frame_id = "dead_data"
    name = "Dead Data Detector"
    category = FrameCategory.GLOBAL
    # DDG proje geneli build edilir ama execute_async per-file çalışır
    # (ArchitectureFrame ile aynı lazy-build pattern).
    # ExecutionScope enum'u codebase'de yok — bu satır kaldırıldı.

    def set_data_dependency_graph(self, ddg: DataDependencyGraph) -> None:
        self._ddg = ddg

    async def execute_async(
        self, code_file: CodeFile, context: PipelineContext | None = None
    ) -> FrameResult:
        if not hasattr(self, "_ddg") or not self._ddg:
            return self._empty_result("ddg_not_injected")

        findings = []
        # DEAD_WRITE
        for field_name, nodes in self._ddg.dead_writes().items():
            for node in nodes:
                if node.file_path == code_file.path:
                    findings.append(Finding(
                        id=f"dead-write-{field_name}-{node.line}",
                        severity="medium",
                        message=f"Dead write: {field_name}",
                        location=f"{node.file_path}:{node.line}",
                        detail=(
                            f"`{field_name}` is written by `{node.writer_func}` "
                            f"but no consumer reads it across {len(self._ddg.reads)} tracked fields."
                        ),
                        line=node.line,
                        is_blocker=False,
                    ))
        # MISSING_WRITE — per-file: bu dosya okuyorsa ve hiç write yoksa
        for field_name, nodes in self._ddg.missing_writes().items():
            for node in nodes:
                if node.file_path == code_file.path:
                    findings.append(Finding(
                        id=f"missing-write-{field_name}-{node.line}",
                        severity="high",
                        message=f"Missing write: {field_name}",
                        location=f"{node.file_path}:{node.line}",
                        detail=(
                            f"`{field_name}` is read by `{node.reader_func}` "
                            f"but is never written anywhere in the codebase."
                        ),
                        line=node.line,
                        is_blocker=False,
                    ))
        status = "failed" if findings else "passed"
        return FrameResult(
            frame_id=self.frame_id, frame_name=self.name,
            status=status, duration=..., issues_found=len(findings),
            is_blocker=False, findings=findings,
            metadata={"dead_writes": len(self._ddg.dead_writes()),
                      "missing_writes": len(self._ddg.missing_writes())},
        )
```

### Testler

```
tests/validation/frames/test_dead_data_frame.py
tests/e2e/fixtures/contract_violations/
  dead_write_project/    — context.X yazılıyor ama hiç okunmuyor
  missing_write_project/ — context.X okunuyor ama hiç yazılmıyor
```

### Done Kriteri

```
warden scan --contract-mode tests/e2e/fixtures/contract_violations/dead_write_project/
  → [medium] dead-write: context.triage_decisions (result_aggregator.py:145)
  → [high]   missing-write: context.orphaned_field (fixture'da kasıtlı olarak yazılmayan field)

warden scan . (flag yok)
  → bu finding'ler çıkmıyor (opt-in koruması)

warden scan --contract-mode . (gerçek warden kodu — PIPELINE_CTX_NAMES fix sonrası)
  → context.dependency_graph_forward → false positive değil, WriteNode tespit edildi
  → context.code_graph               → false positive değil, WriteNode tespit edildi
  → context.validated_issues çifti   → co_write_candidates'da var (STALE_SYNC adayı)

  NOT: DEP-GAP-1 ve INJECT-GAP-1 false positive olduğu doğrulandı (2026-02-25).
  pre_analysis_phase.py "pipeline_context: Any" parametresiyle yazıyor.
  Fixture'daki missing-write testi için sentetik alan kullan.
```

→ **v2.4.0 olarak bağımsız release edilebilir.**

---

## Aşama 3.5 — Contract Mode Raporlama (Issue #174)

> **Zorluk:** ⭐⭐ | **Risk:** Düşük — mevcut altyapıya additive | **Bağımlılık:** Aşama 3 (#167), #166
> **v2.4.0'ın parçası.** Aşama 4 frame'leri bu raporlama altyapısını kullanır (ek değişiklik gerekmez).
> **Soft dep:** #156 (malformed SARIF findings bug — contract finding ID convention riski azaltıyor).

---

### Son Kullanıcı Simülasyonu

```
$ warden scan --contract-mode src/warden/

  Warden v2.4.0  •  494 files  •  contract mode
  ─────────────────────────────────────────────

  [Phase 0]   AST cache .............. ✓ 494 files
  [Phase 0.6] Data Dependency Graph .. ✓ 61 fields · 287 writes · 194 reads
  [Phase 1-4] Frames ................. ✓ 12 frames

  ╭──────────────────────────────────────────────────────────╮
  │  CONTRACT MODE SUMMARY                                   │
  │                                                          │
  │  Tracked   61 fields · 287 writes · 194 reads           │
  │                                                          │
  │  DEAD_WRITE      ██░░░░░░░░  2    (no LLM)              │
  │  MISSING_WRITE   ░░░░░░░░░░  0    (no LLM)              │
  │  STALE_SYNC      ████░░░░░░  2    (LLM ≥ 0.5)           │
  │  PROTOCOL_BREACH ██░░░░░░░░  1    (no LLM)              │
  │  ASYNC_RACE      ░░░░░░░░░░  0    (LLM)                 │
  │                                                          │
  │  5 contract violations  ·  0 blockers                   │
  ╰──────────────────────────────────────────────────────────╯

  [MED]  DEAD_WRITE    context.triage_cache
         result_aggregator.py:145 — store_triage_results() yazar, hiçbir consumer okumaz.
         47 tracked reader'da sıfır ReadNode.

  [MED]  DEAD_WRITE    context.classification_reasoning
         frame_selector.py:211 — set edildi, downstream frames kullanmıyor.

  [HIGH] STALE_SYNC    context.validated_issues ↔ context.findings
         findings_post_processor.py:89  confidence: 0.81
         "findings ile 3 yerde birlikte yazılıyor ama result_aggregator.aggregate()
          context.validated_issues'ı es geçiyor."

  [HIGH] STALE_SYNC    context.classification_reasoning ↔ context.selected_frames
         frame_runner.py:334  confidence: 0.73
         "Seçim reasoning'i kaydediliyor ama sonraki frame hangi frame'in seçildiğini bilmiyor."

  [HIGH] PROTOCOL_BREACH  DataFlowAware → FuzzFrame
         frame_runner.py:334 — FuzzFrame DataFlowAware implement ediyor ama
         frame_runner'da injection bloğu eksik.

  ─────────────────────────────────────────────
  Result  COMPLETED_WITH_FAILURES
  Exit    1

  💡 Tip: warden scan --contract-mode --output warden-contract.sarif src/
         GitHub Code Scanning'e yükle: Security → Code Scanning Alerts → "Contract"
```

---

### GitHub SARIF Entegrasyonu

**Mevcut durum:** `generator.py:314` sadece `id + shortDescription + helpUri` üretiyor.
Contract bulgular generic ruleId ile gömülüyor, GitHub'da ayırt edilemiyor.

**Gerekli enrichment:** `generator.py`'de rule kaydı sırasında `warden/contract/` prefix'i tespit edilip
ek metadata eklenmeli:

```python
# generator.py — mevcut rule kayıt bloğu (satır 312–322) içine ekle:

CONTRACT_RULE_META = {
    "warden/contract/DEAD_WRITE": {
        "shortDescription": "Dead write: context field is written but never read",
        "fullDescription": (
            "A PipelineContext field is assigned a value but no downstream frame "
            "or function reads it. The write is dead code — consuming logic is either "
            "missing or was removed without cleaning up the producer."
        ),
        "help_markdown": (
            "**Fix:** Either add a consumer that reads `{field}`, "
            "or remove the write if the field is no longer needed.\n\n"
            "See [Contract Mode docs](https://github.com/alperduzgun/warden-core/docs/contract-mode)."
        ),
        "tags": ["data-flow", "contract", "maintainability"],
        "precision": "high",           # DDG — deterministik, LLM yok
        "problem_severity": "warning",
    },
    "warden/contract/MISSING_WRITE": {
        "shortDescription": "Missing write: context field is read but never written",
        "fullDescription": (
            "A PipelineContext field is consumed by one or more frames but is never "
            "assigned anywhere in the codebase (excluding constructor defaults). "
            "The field will always be None/empty at read time."
        ),
        "help_markdown": (
            "**Fix:** Add a producer that populates `{field}` before the reading phase, "
            "or remove the read if the field is no longer part of the contract.\n\n"
            "See [Contract Mode docs](https://github.com/alperduzgun/warden-core/docs/contract-mode)."
        ),
        "tags": ["data-flow", "contract", "correctness"],
        "precision": "high",
        "problem_severity": "error",   # Runtime etkisi var
    },
    "warden/contract/STALE_SYNC": {
        "shortDescription": "Stale sync: co-written fields diverge in some code paths",
        "fullDescription": (
            "Two PipelineContext fields are written together in the majority of functions "
            "but one or more code paths update only one of them. This creates an "
            "inconsistent state where one field is stale relative to the other."
        ),
        "help_markdown": (
            "**Fix:** Ensure both fields are updated atomically, or document intentional "
            "divergence with an inline comment.\n\n"
            "See [Contract Mode docs](https://github.com/alperduzgun/warden-core/docs/contract-mode)."
        ),
        "tags": ["data-flow", "contract", "correctness"],
        "precision": "medium",         # LLM verified — olası FP var
        "problem_severity": "error",
    },
    "warden/contract/PROTOCOL_BREACH": {
        "shortDescription": "Protocol breach: mixin implemented but injection missing",
        "fullDescription": (
            "A ValidationFrame implements a DataFlowAware/TaintAware/LSPAware mixin "
            "but frame_runner.py does not inject the required dependency. "
            "The frame's set_*() method will never be called."
        ),
        "help_markdown": (
            "**Fix:** Add the corresponding `isinstance(frame, X)` injection block "
            "in `frame_runner.py`, following the TaintAware pattern at line 334.\n\n"
            "See [Contract Mode docs](https://github.com/alperduzgun/warden-core/docs/contract-mode)."
        ),
        "tags": ["data-flow", "contract", "correctness"],
        "precision": "high",
        "problem_severity": "error",
    },
    "warden/contract/ASYNC_RACE": {
        "shortDescription": "Async race: shared mutable context field accessed without lock",
        "fullDescription": (
            "A PipelineContext field is accessed in multiple concurrent asyncio tasks "
            "(gather/create_task) without synchronization. Under load this can cause "
            "lost updates or partial reads."
        ),
        "help_markdown": (
            "**Fix:** Protect the shared field with `asyncio.Lock`, or use a "
            "defensive copy before passing to concurrent tasks.\n\n"
            "See [Contract Mode docs](https://github.com/alperduzgun/warden-core/docs/contract-mode)."
        ),
        "tags": ["data-flow", "contract", "concurrency"],
        "precision": "medium",
        "problem_severity": "error",
    },
}
```

**Uygulama:** `generator.py`'deki mevcut rule kayıt bloğu şu anda 8 satır
(`id`, `shortDescription`, `helpUri`). Contract kurallar için bu bloğa
`CONTRACT_RULE_META` lookup eklenir:

```python
if rule_id not in rules_map:
    meta = CONTRACT_RULE_META.get(rule_id)       # None = security/resilience bulgusu
    rule = {
        "id": rule_id,
        "shortDescription": {
            "text": meta["shortDescription"] if meta else frame_name
        },
        "helpUri": "https://github.com/alperduzgun/warden-core/docs/rules",
    }
    if meta:
        rule["fullDescription"] = {"text": meta["fullDescription"]}
        rule["help"] = {"text": meta["help_markdown"], "markdown": meta["help_markdown"]}
        rule["properties"] = {
            "tags": meta["tags"],
            "precision": meta["precision"],
            "problem.severity": meta["problem_severity"],
        }
    run["tool"]["driver"]["rules"].append(rule)
    rules_map[rule_id] = rule
```

**GitHub Code Scanning'de sonuç:**

```
Security → Code Scanning Alerts → Filter: "warden"
┌──────────────────────────────────────────────────────────┐
│ Rule                          │ Severity │ Files │ Tags  │
├───────────────────────────────┼──────────┼───────┼───────┤
│ warden/contract/STALE_SYNC   │ Error    │   2   │ data- │
│ Stale sync: co-written fields │          │       │ flow  │
├───────────────────────────────┼──────────┼───────┼───────┤
│ warden/contract/DEAD_WRITE   │ Warning  │   2   │ main- │
│ Dead write: field written...  │          │       │ tain. │
├───────────────────────────────┼──────────┼───────┼───────┤
│ warden/contract/PROTOCOL_    │ Error    │   1   │ data- │
│ BREACH  Mixin impl. missing.. │          │       │ flow  │
└──────────────────────────────────────────────────────────┘

// Her alert'te GitHub "Fix guidance" tooltip gösterir:
"Fix: Add the corresponding isinstance(frame, X) injection block
 in frame_runner.py, following the TaintAware pattern at line 334."
```

---

### Finding ID Konvansiyonu

Contract finding ID'leri stable olmalı (SARIF `ruleId`'yi finding.id'den türetiyor):

| Frame | Finding ID formatı | ruleId (generator'da) |
|-------|-------------------|-----------------------|
| `DeadDataFrame` | `warden/contract/DEAD_WRITE` | `warden/contract/DEAD_WRITE` |
| `DeadDataFrame` | `warden/contract/MISSING_WRITE` | `warden/contract/MISSING_WRITE` |
| `StaleSyncFrame` | `warden/contract/STALE_SYNC` | `warden/contract/STALE_SYNC` |
| `ProtocolBreachFrame` | `warden/contract/PROTOCOL_BREACH` | `warden/contract/PROTOCOL_BREACH` |
| `AsyncRaceFrame` | `warden/contract/ASYNC_RACE` | `warden/contract/ASYNC_RACE` |

> **Not:** Mevcut `generator.py:297` → `rule_id = str(...).lower().replace(" ", "-")`
> Slash'lar korunuyor — `warden/contract/DEAD_WRITE` → `warden/contract/dead_write` olarak SARIF'e girer.
> GitHub bu format'ı kabul eder, category olarak ayrıştırır.

---

### Terminal Summary Paneli — Hook Noktası

**`scan.py`** — son çıktı bloğunda (`_display_llm_summary` çağrısının hemen altına):

```python
# Contract mode summary panel — frame result metadata'sından çekiliyor
if contract_mode and result_data:
    dead_data_frame = next(
        (f for f in result_data.get("frames", [])
         if f.get("frame_id") == "dead_data"),
        None
    )
    if dead_data_frame:
        _display_contract_summary(result_data, dead_data_frame.get("metadata", {}))
```

```python
def _display_contract_summary(result_data: dict, ddg_meta: dict) -> None:
    """Contract mode özet paneli — Rich panel, scan.py'nin mevcut stiliyle uyumlu."""
    from rich.panel import Panel

    dead  = ddg_meta.get("dead_writes", 0)
    miss  = ddg_meta.get("missing_writes", 0)
    fields = ddg_meta.get("tracked_fields", 0)
    writes = ddg_meta.get("total_writes", 0)
    reads  = ddg_meta.get("total_reads", 0)

    # Frame counts (diğer contract frame'lerden)
    stale  = sum(1 for f in result_data.get("frames", []) if f.get("frame_id") == "stale_sync")
    breach = sum(1 for f in result_data.get("frames", []) if f.get("frame_id") == "protocol_breach")
    race   = sum(1 for f in result_data.get("frames", []) if f.get("frame_id") == "async_race")

    def bar(n, total=5): return "█" * min(n, total) + "░" * (total - min(n, total))

    lines = [
        f"  Tracked   [cyan]{fields} fields · {writes} writes · {reads} reads[/cyan]",
        "",
        f"  DEAD_WRITE      [yellow]{bar(dead)}[/yellow]  {dead}    (no LLM)",
        f"  MISSING_WRITE   [red]{bar(miss)}[/red]  {miss}    (no LLM)",
        f"  STALE_SYNC      [red]{bar(stale)}[/red]  {stale}    (LLM ≥ 0.5)",
        f"  PROTOCOL_BREACH [red]{bar(breach)}[/red]  {breach}    (no LLM)",
        f"  ASYNC_RACE      [red]{bar(race)}[/red]  {race}    (LLM)",
        "",
        f"  [bold]{dead+miss+stale+breach+race} contract violations[/bold]  ·  0 blockers",
    ]
    console.print(Panel("\n".join(lines), title="CONTRACT MODE SUMMARY", border_style="cyan"))
```

`DeadDataFrame.execute_async`'taki mevcut `metadata` dict'ine DDG istatistikleri eklenmeli:

```python
metadata={
    "dead_writes":     len(self._ddg.dead_writes()),
    "missing_writes":  len(self._ddg.missing_writes()),
    "tracked_fields":  len(set(self._ddg.writes) | set(self._ddg.reads)),
    "total_writes":    sum(len(v) for v in self._ddg.writes.values()),
    "total_reads":     sum(len(v) for v in self._ddg.reads.values()),
},
```

---

### Done Kriteri

```
warden scan --contract-mode src/warden/ (terminal)
  → "CONTRACT MODE SUMMARY" paneli görünüyor
  → 5 bar satırı doğru sayıları gösteriyor
  → Her finding altında field adı + dosya:satır + açıklama var

warden scan --contract-mode --output warden-contract.sarif src/warden/
  → SARIF'te warden/contract/DEAD_WRITE rule'u fullDescription içeriyor
  → properties.tags = ["data-flow", "contract", "maintainability"]
  → properties.precision = "high"
  → help.markdown actionable fix içeriyor

GitHub Actions upload:
  - name: Upload Contract SARIF
    uses: github/codeql-action/upload-sarif@v3
    with:
      sarif_file: warden-contract.sarif
      category: warden-contract

  → Security → Code Scanning'de "Contract" kategorisi ayrı görünüyor
  → Güvenlik bulguları ile karışmıyor (category: warden-security vs warden-contract)
```

### Değiştirilen Dosyalar (Aşama 3.5)

| Dosya | Değişiklik |
|-------|-----------|
| `src/warden/reports/generator.py` | `CONTRACT_RULE_META` dict + rule kayıt bloğuna enrichment (≈30 satır) |
| `src/warden/cli/commands/scan.py` | `_display_contract_summary()` fonksiyon + çağrı (≈35 satır) |
| `src/warden/validation/frames/dead_data/dead_data_frame.py` | `metadata` dict'e 3 istatistik alanı ekleme |

---

## Aşama 4 — LLM-Destekli Frame'ler

> **Zorluk:** ⭐⭐⭐ | **Risk:** Orta — `_confidence_rules.txt` < 0.5 olanları siler
> **Bağımlılık:** Aşama 2

### 4.1 StaleSyncFrame

**`src/warden/validation/frames/stale_sync/stale_sync_frame.py`**

`security/frame.py` satır 261'deki `semantic_context` build pattern'ini kopyala.

**Akış:**
```
ddg.co_write_candidates()
  → {("context.findings", "context.validated_issues"): ["func_a", "func_b", "func_c"]}
      │
      ▼
  LLM'e gönderilen context (data_flow_contract.txt template):

  [DATA FLOW CONTEXT]
  Aşağıdaki field çifti 3 fonksiyonda birlikte yazılıyor:
    - frame_executor.execute_validation_with_strategy_async
    - findings_post_processor.verify_findings_async
    - result_aggregator.store_validation_results

  Ancak `result_aggregator.aggregate()` yalnızca `context.findings` yazıyor,
  `context.validated_issues` yazmıyor.

  Bu bir STALE_SYNC hatası mı yoksa kasıtlı bir ayrım mı?
      │
      ▼
  LLM confidence < 0.5 → skip (mevcut _confidence_rules.txt)
  LLM confidence ≥ 0.5 → STALE_SYNC finding
```

**`data_flow_contract.txt`** bu frame'le birlikte yazılır. Ayrı bir aşama değil.

Simülasyonda tespit edilen 5 STALE_SYNC adayı LLM'e gidecek:
- `findings + validated_issues` (BASELINE-GAP-2)
- `false_positives + validated_issues`
- `false_positives + findings`
- `classification_reasoning + selected_frames`
- `findings + frame_results`

### 4.2 ProtocolBreachFrame

**`src/warden/validation/frames/protocol_breach/protocol_breach_frame.py`**

LLM yok — saf AST:
1. `mixins.py` üzerinden tüm mixin subclass'larını bul (`TaintAware`, `LSPAware`, `DataFlowAware`)
2. `frame_runner.py` AST'ini parse et
3. Her mixin için `isinstance(frame, X)` + `frame.set_X()` çifti eksikse → `PROTOCOL_BREACH`

### 4.3 AsyncRaceFrame

**`src/warden/validation/frames/async_race/async_race_frame.py`**

1. AST: `asyncio.gather(...)` veya `asyncio.create_task(...)` çağrıları
2. Task'larda erişilen paylaşılan mutable object'ler (`context.findings` vb.)
3. `asyncio.Lock` veya defensive copy var mı?
4. Yoksa → LLM verify → `ASYNC_RACE`

### Done Kriteri

```
warden scan --contract-mode src/warden/
  → [high] STALE_SYNC: context.validated_issues — confidence: 0.81
           "findings ile 3 yerde birlikte yazılıyor ama result_aggregator'da yazılmıyor"
  → [high] PROTOCOL_BREACH: DataFlowAware → FuzzFrame injection eksik (frame_runner.py)
  → [high] ASYNC_RACE: context.findings (frame_executor.py) kilitsiz asyncio.gather

warden scan --contract-mode (false positive testi)
  → kasıtlı ayrımlar raporlanmıyor (LLM confidence < 0.5)
```

→ **v2.5.0 olarak release edilebilir.**

---

## Özet

| Aşama | Ne | Bağımlılık | Zorluk | Release |
|-------|----|-----------|--------|---------|
| 1 | DDG domain + builder + filtreler | Yok | ⭐⭐ | unit testler |
| 2 | DDG service + 5 dosyaya ekleme | 1 | ⭐⭐ | integration test |
| 3 | `DeadDataFrame` + `--contract-mode` | 2 | ⭐⭐ | **v2.4.0** |
| 3.5 | Terminal summary paneli + SARIF enrichment | 3 | ⭐⭐ | **v2.4.0** |
| 4a | `StaleSyncFrame` + `data_flow_contract.txt` | 2 | ⭐⭐⭐ | **v2.5.0** |
| 4b | `ProtocolBreachFrame` | 2 | ⭐⭐ | v2.5.0 ile |
| 4c | `AsyncRaceFrame` | 2 | ⭐⭐⭐ | v2.5.0 ile |

---

## Değiştirilen / Eklenen Dosyalar

### Değiştirilen (küçük ekleme)
| Dosya | Değişiklik |
|-------|-----------|
| `src/warden/pipeline/domain/models.py` | `contract_mode: bool = False` |
| `src/warden/pipeline/domain/pipeline_context.py` | `data_dependency_graph: Any \| None = None` |
| `src/warden/validation/domain/mixins.py` | `DataFlowAware` class ekleme |
| `src/warden/pipeline/application/orchestrator/frame_runner.py` | `DataFlowAware` injection bloğu (5 satır) |
| `src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py` | `_populate_data_dependency_graph_async` + çağrı |
| `src/warden/cli_bridge/bridge.py` | `contract_mode` param + config set |
| `src/warden/cli/commands/scan.py` | `--contract-mode` typer flag + `_display_contract_summary()` |
| `src/warden/reports/generator.py` | `CONTRACT_RULE_META` + SARIF rule enrichment |

### Yeni Dosyalar
| Dosya | Aşama |
|-------|-------|
| `src/warden/analysis/domain/data_dependency_graph.py` | 1 |
| `src/warden/analysis/application/data_dependency_builder.py` | 1 |
| `src/warden/analysis/services/data_dependency_service.py` | 2 |
| `src/warden/validation/frames/dead_data/dead_data_frame.py` | 3 |
| `src/warden/validation/frames/stale_sync/stale_sync_frame.py` | 4a |
| `src/warden/llm/prompts/templates/data_flow_contract.txt` | 4a ile |
| `src/warden/validation/frames/protocol_breach/protocol_breach_frame.py` | 4b |
| `src/warden/validation/frames/async_race/async_race_frame.py` | 4c |
| `tests/analysis/data_dependency/` (dizin) | 1 |
| `tests/validation/frames/test_dead_data_frame.py` | 3 |
| `tests/e2e/fixtures/contract_violations/` (dizin) | 3 |

---

## Teknik Referanslar

| Dosya | Rol |
|-------|-----|
| `src/warden/validation/domain/frame.py` | ValidationFrame ABC — `execute_async(code_file, context=None) → FrameResult` |
| `src/warden/validation/domain/enums.py:93` | `FrameCategory` — GLOBAL kullan, ARCHITECTURE yok |
| `src/warden/pipeline/application/orchestrator/pipeline_phase_runner.py:350` | `_populate_taint_paths_async` — DDG service için kopyalanacak pattern |
| `src/warden/analysis/services/code_graph_builder.py` | `DataDependencyBuilder` için yapısal referans |
| `src/warden/validation/frames/architecture/architecture_frame.py:170` | `DeadDataFrame` için clone edilecek frame |
| `src/warden/validation/frames/security/frame.py:261` | `semantic_context` build — `StaleSyncFrame` bunu izler |
| `src/warden/llm/prompts/templates/shared/_confidence_rules.txt` | < 0.5 → raporlama — LLM frame'lerde geçerli |
| `src/warden/pipeline/domain/pipeline_context.py:138` | `ast_cache` — DDG builder'ın kullandığı kaynak |
| `src/warden/pipeline/application/orchestrator/frame_runner.py:334` | TaintAware injection — `DataFlowAware` için kopyalanacak |

---

*Son güncelleme: 2026-02-25 — İki simülasyon sonrası, tüm bulgular dahil edildi.*
*2026-02-25 (rev2) — Uyumluluk simülasyonu sonrası 3 hata düzeltildi:*
*  (1) Teknik Ref: taint/service.py:350 → pipeline_phase_runner.py:350*
*  (2) Teknik Ref: analysis/application/code_graph_builder.py → analysis/services/code_graph_builder.py*
*  (3) Aşama 2.7: bridge.scan() → execute_pipeline_stream_async() (asıl entry point)*
*2026-02-25 (rev3) — Aşama 3.5 eklendi: terminal summary paneli simülasyonu, GitHub SARIF enrichment,*
*  CONTRACT_RULE_META (5 kural × fullDescription/help.markdown/tags/precision), finding ID konvansiyonu.*
*2026-02-25 (rev4) — Issue #174 oluşturuldu. BASELINE-GAP-2'ye #124 cross-ref eklendi.*
*  Bağımlılık: #156 (SARIF malformed bug) soft dep olarak işaretlendi.*
