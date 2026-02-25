# Contract Mode — Implementation Roadmap

> Dependency chain, sıralama ve her issue için doğrulama adımları.
> Son güncelleme: 2026-02-25 rev2 — #174 oluşturuldu, Pareto sıralaması eklendi, #124/#156 cross-ref

---

## PR Workflow Kuralı

> **Her issue için zorunlu akış:**

```
Issue açık
    │
    ▼
feat/<issue-no>-<kısa-açıklama> branch'i oluştur
    │
    ▼
Implementasyon + issue doğrulama adımları pass
    │
    ▼
PR aç → main'e değil, dev'e
  title: "<type>(<scope>): <açıklama> (closes #N)"
  body:  doğrulama çıktısı + test sonuçları
    │
    ▼
Code review (en az 1 approval)
    │
    ▼
Squash & merge → dev
    │
    ▼
Issue otomatik kapanır (closes #N)
```

**Branch adlandırma:**
```
feat/162-ddg-domain-model
feat/163-ddg-builder-fp-filters
feat/174-contract-reporting
fix/130-prior-findings-reset
...
```

**PR kuralları:**
- Her issue → tek PR (1-1 eşleme)
- PR açılmadan implement kabul edilmez
- Doğrulama adımlarının çıktısı PR açıklamasına yapıştırılır
- Release issue'ları (#169, #173) → PR değil, tag + release notes
- Squash merge: commit history temiz kalır

---

## Dependency Chain

```
#175, #176 (SecurityFrame bug fix'ler — v2.4.0 pre-req)
       │
       ▼
#162 → #163 → #164 → #165 → #166
                               │
                               ▼
                     #167 → #168 → #174 → v2.4.0 (#169)
                               │         [soft: #156]
                       [fix #130, #139]
                               │
                     #171 → #170 → #172 → v2.5.0 (#173)
```

## Pareto Sıralaması

> %20 iş → %80 değer. Her blok bir önceki olmadan release edilemez.

| Blok | Issue'lar | Değer / Çaba | Neden önce |
|------|-----------|-------------|------------|
| **Bug Fix (pre-v2.4.0)** | #175, #176 | Kritik / Düşük | SecurityFrame test suite'i broken — release blocker |
| **Blok 1** | #162–#164 | Yüksek / Düşük | DDG altyapısı — her şeyin temeli, pure new code |
| **Blok 2** | #165–#166 | Yüksek / Düşük | Additive pipeline wiring, zero regression risk |
| **Blok 3a** | #167–#168 | Çok yüksek / Düşük | İlk kullanıcıya görünen değer, no LLM, deterministik |
| **Blok 3b** | #174 | Yüksek / Düşük | Reporting olmadan bulgular gömülü kalır, CI'da görünmez |
| **v2.4.0** | #169 | — | Blok 3b bitmeden release yok |
| **Blok 4a** | #171 | Orta / Düşük | AST-only, yüksek precision, en kolay LLM-free frame |
| **Blok 4b** | #170 | Yüksek / Orta | 5 bilinen STALE_SYNC adayı, gerçek impact |
| **Blok 4c** | #172 | Orta / Yüksek | En karmaşık (asyncio + lock detection), en az acil |
| **v2.5.0** | #173 | — | Tüm Blok 4 bitmeden release yok |

---

## Blok 1 — DDG Core (Phase 1)

### #162 — DataDependencyGraph domain model
**Dosya:** `src/warden/analysis/domain/data_dependency_graph.py`
**Blocker:** —

**Doğrulama:**
```python
# Python REPL'de çalıştır
from warden.analysis.domain.data_dependency_graph import (
    WriteNode, ReadNode, DataDependencyGraph
)
from collections import defaultdict

ddg = DataDependencyGraph(
    writes=defaultdict(list, {
        "context.unused": [WriteNode("context.unused", "foo.py", 10, "func_a", False)]
    }),
    reads=defaultdict(list),
    init_fields=set(),
)

assert ddg.dead_writes() == {"context.unused": ddg.writes["context.unused"]}
assert ddg.missing_writes() == {}
print("✓ #162 doğrulandı")
```
```bash
python3 -m pytest tests/analysis/data_dependency/test_data_dependency_graph.py -v
# Tüm testler PASS
```

---

### #163 — DataDependencyBuilder + DDGVisitor + FP filters
**Dosya:** `src/warden/analysis/application/data_dependency_builder.py`
**Blocker:** #162

**Doğrulama:**
```bash
# Unit testler
python3 -m pytest tests/analysis/data_dependency/test_data_dependency_builder.py -v
python3 -m pytest tests/analysis/data_dependency/test_ddg_filter.py -v

# Kritik: PIPELINE_CTX_NAMES fix — gerçek warden kodu üzerinde
python3 - <<'EOF'
import ast, sys
from pathlib import Path
sys.path.insert(0, "src")
from warden.analysis.application.data_dependency_builder import DataDependencyBuilder

# pre_analysis_phase.py'yi doğrudan parse et
src = Path("src/warden/pipeline/application/orchestrator/pre_analysis_phase.py").read_text()
tree = ast.parse(src)
from warden.analysis.domain.data_dependency_graph import DataDependencyGraph
from collections import defaultdict
ddg = DataDependencyGraph(writes=defaultdict(list), reads=defaultdict(list), init_fields=set())
from warden.analysis.application.data_dependency_builder import DDGVisitor
DDGVisitor("pre_analysis_phase.py", ddg).visit(tree)

assert "context.code_graph" in ddg.writes, "FAIL: code_graph WriteNode bulunamadı"
assert "context.dependency_graph_forward" in ddg.writes, "FAIL: dependency_graph_forward WriteNode bulunamadı"
print("✓ #163 doğrulandı — PIPELINE_CTX_NAMES fix çalışıyor")
EOF
```

---

### #164 — DDG unit tests + fixtures
**Blocker:** #162, #163

**Doğrulama:**
```bash
python3 -m pytest tests/analysis/data_dependency/ -v --tb=short

# False positive kontrolü
python3 -m pytest tests/analysis/data_dependency/test_ddg_filter.py -v -k "false_positive"

# Coverage
python3 -m pytest tests/analysis/data_dependency/ --cov=warden.analysis.domain --cov=warden.analysis.application --cov-report=term-missing
# Target: >90% coverage
```

---

## Blok 2 — Pipeline (Phase 2)

### #165 — DataFlowAware mixin + DataDependencyService
**Dosyalar:** `mixins.py`, `data_dependency_service.py`
**Blocker:** #163, #164

**Doğrulama:**
```python
# Import kontrolü
from warden.validation.domain.mixins import DataFlowAware
from warden.analysis.services.data_dependency_service import DataDependencyService
import inspect, abc
assert isinstance(DataFlowAware, type)
assert abc.ABC in DataFlowAware.__mro__
print("✓ DataFlowAware import OK")
```
```bash
# Mevcut testler kırılmadı mı?
python3 -m pytest tests/ -x -q --ignore=tests/e2e
# Tüm testler PASS (regression yok)
```

---

### #166 — Pipeline wiring (contract_mode flag, scan CLI, frame_runner, phase_runner, bridge)
**Blocker:** #165

**Doğrulama:**
```bash
# CLI flag var mı?
warden scan --help | grep contract-mode
# → --contract-mode  Run data flow contract analysis...

# DDG populate ediliyor mu? (henüz frame yok, ama None olmamalı)
python3 - <<'EOF'
import asyncio, sys
sys.path.insert(0, "src")
from warden.cli_bridge.bridge import WardenBridge

async def check():
    bridge = WardenBridge(".")
    # Minimal scan — sadece AST + DDG
    ctx = await bridge._build_context_async(contract_mode=True)
    assert ctx.data_dependency_graph is not None, "FAIL: DDG None"
    ddg = ctx.data_dependency_graph
    assert len(ddg.writes) > 0, "FAIL: DDG boş"
    print(f"✓ #166 doğrulandı — DDG populated: {len(ddg.writes)} fields tracked")

asyncio.run(check())
EOF

# Regression
python3 -m pytest tests/ -x -q
```

---

## Blok 3 — DeadDataFrame + v2.4.0

### #167 — DeadDataFrame (DEAD_WRITE, MISSING_WRITE, NEVER_POPULATED)
**Dosya:** `src/warden/validation/frames/dead_data/dead_data_frame.py`
**Blocker:** #166

**Doğrulama:**
```bash
# Frame import + temel yapı
python3 - <<'EOF'
from warden.validation.frames.dead_data.dead_data_frame import DeadDataFrame
from warden.validation.domain.mixins import DataFlowAware
frame = DeadDataFrame()
assert isinstance(frame, DataFlowAware)
assert frame.frame_id == "dead_data"
assert frame.is_blocker == False
print("✓ Frame yapısı OK")
EOF

# DDG inject edilmezse graceful skip
python3 - <<'EOF'
import asyncio, sys
sys.path.insert(0, "src")
from warden.validation.frames.dead_data.dead_data_frame import DeadDataFrame
from warden.validation.domain.models import CodeFile

async def check():
    frame = DeadDataFrame()
    # DDG inject edilmedi
    result = await frame.execute_async(CodeFile(path="foo.py", content=""))
    assert result.status == "passed"
    assert result.issues_found == 0
    print("✓ DDG inject edilmezse graceful skip")

asyncio.run(check())
EOF

# Opt-in koruması — flag olmadan çalışmamalı
warden scan . 2>&1 | grep -c "dead-write\|missing-write"
# → 0 (flag olmadan finding çıkmamalı)
```

---

### #168 — DeadDataFrame tests + E2E fixtures
**Blocker:** #167

**Doğrulama:**
```bash
# Unit testler
python3 -m pytest tests/validation/frames/test_dead_data_frame.py -v

# E2E: dead_write fixture
warden scan --contract-mode tests/e2e/fixtures/contract_violations/dead_write_project/
# → En az 1 [medium] dead-write finding
# → [high] missing-write finding

# E2E: temiz proje
warden scan --contract-mode tests/e2e/fixtures/contract_violations/clean_project/ 2>/dev/null
# → 0 dead-write/missing-write finding

# Gerçek warden kodu — false positive yok
warden scan --contract-mode src/warden/ 2>&1 | grep -E "DEAD_WRITE|MISSING_WRITE" | grep -v "context.dependency_graph_forward\|context.code_graph"
# → (boş — bu ikisi artık false positive değil)

# Full test suite
python3 -m pytest tests/ -x -q
```

---

### #174 — Contract Mode terminal summary paneli + SARIF enrichment
**Dosyalar:** `scan.py`, `reports/generator.py`, `dead_data_frame.py` (metadata)
**Blocker:** #167, #166
**Soft dep:** #156 (malformed SARIF bug — contract ID convention riski azaltıyor ama fix edilmişse güvenli)

**Doğrulama:**
```bash
# Terminal summary paneli
warden scan --contract-mode src/warden/ 2>&1 | grep -A 12 "CONTRACT MODE SUMMARY"
# → Panel görünüyor, 5 satır (DEAD_WRITE, MISSING_WRITE, STALE_SYNC, PROTOCOL_BREACH, ASYNC_RACE)

# SARIF enrichment
warden scan --contract-mode --output warden-contract.sarif src/warden/
python3 - <<'EOF'
import json
sarif = json.load(open("warden-contract.sarif"))
rules = sarif["runs"][0]["tool"]["driver"]["rules"]
contract_rules = [r for r in rules if "contract" in r.get("id","")]
for r in contract_rules:
    assert "fullDescription" in r, f"Missing fullDescription: {r['id']}"
    assert "help" in r, f"Missing help: {r['id']}"
    assert "tags" in r.get("properties", {}), f"Missing tags: {r['id']}"
print(f"✓ {len(contract_rules)} contract rule enriched")
EOF

# Regression
python3 -m pytest tests/ -x -q
# → tüm testler PASS
```

---

### #169 — release: v2.4.0 ✦
**Blocker:** **#175, #176** (SecurityFrame bug fix'ler), #162–#168, **#174** hepsi

**Doğrulama:**
```bash
# Tüm testler CI matrix'te pass
python3 -m pytest tests/ -q
# → 1083+ pass, 0 fail

# Smoke test
warden scan --contract-mode src/warden/ 2>&1 | tail -20

# Version bump
python3 -c "import warden; print(warden.__version__)"
# → 2.4.0

# CHANGELOG ve DATA_FLOW_CONTRACTS.md güncellendi mi?
grep "2.4.0" CHANGELOG.md
grep "DeadDataFrame\|DEAD_WRITE" DATA_FLOW_CONTRACTS.md
```

---

## SecurityFrame Bug Fix'ler (v2.4.0 pre-req) 🚨

> Bu iki bug SecurityFrame'in test suite'ini broken halde bırakıyor.
> `python3 -m pytest tests/` çalıştırıldığında 5 test fail ediyor.
> v2.4.0 release'i öncesi fix edilmeli.

### #175 — `_aggregate_findings` taint_context parametresi kaldırıldı, testler güncellenmedi
**Dosya:** `src/warden/validation/frames/security/frame.py`, `tests/validation/frames/security/test_machine_context.py`
**Blocker:** —
**Etki:** 3 test `TypeError: _aggregate_findings() got an unexpected keyword argument 'taint_context'`

**Kök neden:** `taint_context` parametresi TaintAware mixin pattern'e geçildiğinde method imzasından kaldırıldı. Testler eski çağrı convention'ını kullanmaya devam ediyor.

**Fix:** Testleri güncelle — `taint_context=` argümanını kaldır, TaintAware injection pattern'ini kullan.

**Doğrulama:**
```bash
python3 -m pytest tests/validation/frames/security/test_machine_context.py::TestAggregateFindings -v
# → 3 test PASS (TypeError yok)
```

---

### #176 — `html.escape()` MachineContext field'larına sızıyor
**Dosya:** `src/warden/validation/frames/security/frame.py:360`
**Blocker:** —
**Etki:** 2 test fail — `'` → `&#x27;` olarak döner, downstream consumer'lar bozuk veri alır

**Kök neden:** `html.escape()` prompt injection koruması için uygulanıyor ama escaped değerler findings/MachineContext'e yazılıyor. LLM prompt'u için scopelanmalıydı.

**Fix:**
```python
# frame.py:360 civarı
# Sadece LLM prompt için escape et, finding'e yazma:
llm_msg = html.escape(raw_msg[:200])
llm_severity = html.escape(raw_severity[:20])
# raw_msg / raw_severity → finding storage'a gider
```

**Doğrulama:**
```bash
python3 -m pytest tests/validation/frames/security/test_machine_context.py::TestLLMStructuredOutput -v
# → 2 test PASS (&#x27; yok)

# Full machine_context suite:
python3 -m pytest tests/validation/frames/security/test_machine_context.py -v
# → tüm testler PASS
```

---

## Araya Giren Bug Fix'ler (v2.4.0 → v2.5.0)

### #130 — prior_findings per-file reset
**Neden şimdi:** StaleSyncFrame (#170) LLM prompt'una prior_findings gidiyor.
Bug aktifse önceki dosyadan gelen finding'ler yeni dosya analizini kirletiyor.

**Doğrulama:**
```bash
python3 -m pytest tests/pipeline/orchestrator/ -v -k "prior_findings"
# Yeni test: aynı frame iki farklı dosyada çalıştırıldığında prior_findings sıfırlanıyor mu?
```

### #139 — 6 frames missing context parameter
**Neden şimdi:** AsyncRaceFrame (#172) `context.project_intelligence` kullanacak.
Context eksikse FP filtrelemesi yok.

**Doğrulama:**
```bash
python3 -m pytest tests/validation/frames/ -v -k "context"
# 6 frame için context parametresi geçiliyor ve alınıyor
```

---

## Blok 4 — LLM Frame'ler (Phase 4)

### #171 — ProtocolBreachFrame (AST-only)
**Dosya:** `src/warden/validation/frames/protocol_breach/protocol_breach_frame.py`
**Blocker:** #166

**Doğrulama:**
```bash
# Kendi kendini test eder: DataFlowAware inject edilmezse bunu raporlamalı
warden scan --contract-mode src/warden/pipeline/application/orchestrator/ 2>&1 | grep "PROTOCOL_BREACH"
# → (DataFlowAware injection eksikse finding çıkar)

# Temiz durum: tüm mixin'ler doğru inject edilmiş
python3 -m pytest tests/validation/frames/test_protocol_breach_frame.py -v
```

---

### #170 — StaleSyncFrame (LLM)
**Dosya:** `src/warden/validation/frames/stale_sync/stale_sync_frame.py`
**Blocker:** #166
**Soft dep:** #130 fix edilmiş olmalı

**Doğrulama:**
```bash
# LLM olmadan çalışıyor mu? (confidence < 0.5 → skip)
python3 -m pytest tests/validation/frames/test_stale_sync_frame.py -v

# Gerçek warden kodu üzerinde (LLM gerekiyor)
warden scan --contract-mode src/warden/ 2>&1 | grep "STALE_SYNC"
# → context.validated_issues için finding bekleniyor (confidence ≥ 0.5 ise)

# Simülasyonda tespit edilen 5 adaydan en az 1'i raporlanmalı
warden scan --contract-mode src/warden/ --output json 2>/dev/null | \
  python3 -c "import json,sys; f=json.load(sys.stdin); print([x for x in f.get('findings',[]) if 'STALE_SYNC' in x.get('id','')])"
```

---

### #172 — AsyncRaceFrame (LLM)
**Dosya:** `src/warden/validation/frames/async_race/async_race_frame.py`
**Blocker:** #166
**Soft dep:** #139 fix edilmiş olmalı

**Doğrulama:**
```bash
python3 -m pytest tests/validation/frames/test_async_race_frame.py -v

# Bilinen aday: frame_executor.py — kilitsiz asyncio.gather
warden scan --contract-mode src/warden/pipeline/application/ 2>&1 | grep "ASYNC_RACE"
# → context.findings için finding bekleniyor

# False positive: Lock ile korunan gather raporlanmamalı
# (test fixture'ında Lock'lu örnek var, finding çıkmamalı)
```

---

### #173 — release: v2.5.0 ✦
**Blocker:** #169, #170, #171, #172

**Doğrulama:**
```bash
python3 -m pytest tests/ -q
# → tüm testler pass

# 6 gap tipi çalışıyor mu?
warden scan --contract-mode src/warden/ --output json 2>/dev/null | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
gaps = {f['gap_type'] for f in data.get('findings', []) if 'gap_type' in f}
print('Tespit edilen gap tipleri:', gaps)
"

python3 -c "import warden; print(warden.__version__)"
# → 2.5.0
```

---

## Hızlı Referans

| Issue | Konu | Blocker | Pareto | Doğrulama Özeti |
|-------|------|---------|--------|-----------------|
| `#175` | `_aggregate_findings` taint_context TypeError | — | 🚨 release blocker | 3 test PASS, TypeError yok |
| `#176` | html.escape MachineContext sızması | — | 🚨 release blocker | 2 test PASS, &#x27; yok |
| **#162** | DDG domain model | — | ⭐ temel | REPL + unit test |
| **#163** | DataDependencyBuilder + PIPELINE_CTX_NAMES | #162 | ⭐ temel | AST parse, FP fix doğrulandı |
| **#164** | DDG tests + fixtures | #162, #163 | ⭐ temel | pytest + >90% coverage |
| **#165** | DataFlowAware + service | #163, #164 | ⭐ temel | import + regression yok |
| **#166** | Pipeline wiring | #165 | ⭐ temel | CLI flag + DDG populated |
| **#167** | DeadDataFrame | #166 | 🎯 %80 değer | opt-in + graceful skip |
| **#168** | DeadDataFrame tests | #167 | 🎯 %80 değer | E2E fixtures + FP yok |
| **#174** | Terminal summary + SARIF enrichment | #167, #166 | 🎯 %80 değer | panel görünür + SARIF tags |
| **#169** | **v2.4.0 release** | #162–#168, #174 | ✦ release | full CI + smoke test |
| `#130` | prior_findings cross-file bug | — | bug fix | per-file reset test |
| `#139` | 6 frames missing context param | — | bug fix | context param geçiliyor |
| **#171** | ProtocolBreachFrame (AST-only) | #166 | ⚡ hızlı kazan | kendi kendini test eder |
| **#170** | StaleSyncFrame (LLM) | #166, #130 | 💡 yüksek değer | LLM confidence + 5 aday |
| **#172** | AsyncRaceFrame (LLM) | #166, #139 | 📦 tamamlayıcı | frame_executor aday |
| **#173** | **v2.5.0 release** | #169–#172 | ✦ release | 6 gap tipi aktif |

> **Not — #124 (validated_issues stale bug):** Bu issue BASELINE-GAP-2 STALE_SYNC tespitini **doğruluyor**.
> `context.validated_issues` baseline filtering sonrasında güncellenmez → fortification stale data kullanır.
> StaleSyncFrame (#170), bu gap'i LLM ile de tespit edecek. #124 bağımsız bug fix olarak devam eder.
