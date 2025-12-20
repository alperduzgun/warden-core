# Warden C# to Python Migration Session

## 📌 PATH CONFIGURATION

**IMPORTANT:** This file uses generic path placeholders. Replace them with your actual paths:

```bash
<WARDEN_PANEL_PATH>   → Path to warden-panel-development (Svelte frontend)
<WARDEN_CSHARP_PATH>  → Path to warden-csharp (C# legacy backend)
<PROJECT_ROOT>        → Path to this project (warden-core Python)

Example:
<WARDEN_PANEL_PATH>   → /Users/yourname/warden-panel-development
<WARDEN_CSHARP_PATH>  → /Users/yourname/warden-csharp
<PROJECT_ROOT>        → /Users/yourname/warden-core
```

**For Claude Code:** When executing commands, replace placeholders with actual paths.

---

## 📌 DEVELOPMENT CONTEXT (Claude Code için)

**NOT:** Bu proje uzun soluklu bir geliştirme. Kullanıcının local'inde mem0 kurulu ve Claude Code session'ları arasında context tutmak için kullanılıyor.

### 🚨 SESSION BAŞINDA İLK İŞ (ZORUNLU)

```bash
# 1. ÖNCE context'i yükle
/mem-context

# 2. Critical files'ı oku (3 dosya - MANDATORY!)
cat temp/session-start.md
cat temp/warden_core_rules.md
cat temp/warden_quick_reference.md

# 3. Gerekirse spesifik search
/mem-search "warden core"
```

**WHY:**
- Memory: Önceki session'da ne yapıldığını, hangi kararların alındığını hatırla!
- Critical Files: Migration rules, Python standards, C# Warden architecture'ını öğren!

### Kurallar:
1. **Session BAŞINDA `/mem-context` çalıştır** - Nerede kaldığını hatırla (MANDATORY!)
2. **Her önemli adımda `/mem-save` kullan** - Session arası context kaybolmasın
3. **Kararları kaydet** - Neden bu yolu seçtiğini unutma
4. **Blocker'ları kaydet** - Takıldığın yerleri not al

### Mem0 Commands
```bash
# Session başında
/mem-context                    # Load all relevant context
/mem-search "specific topic"    # Search for specific info

# Çalışma sırasında
/mem-save "Important decision or progress"

# Session sonunda
/mem-save "Session summary: completed X, next Y"
```

---

## 🎯 Mission
Migrate Warden from C# to Python while preserving functionality and improving maintainability.

## ⚠️ CRITICAL PRINCIPLE: WARDEN IS A REPORTER, NOT A CODE MODIFIER

**Warden NEVER modifies code automatically!**
- ✅ Warden analyzes code
- ✅ Warden detects issues
- ✅ Warden generates reports with suggestions
- ❌ Warden does NOT auto-fix code
- ❌ Warden does NOT modify source files
- ❌ Warden does NOT apply patches

**LLM Usage:**
- LLM can provide better descriptions/explanations
- LLM can suggest fixes (as text recommendations)
- LLM does NOT generate modified code
- Final decision is ALWAYS with the developer

---

## 📁 Critical Paths

### Source (C# Project - LEGACY)
```
<WARDEN_CSHARP_PATH>/
├── src/Warden.Core/           # Core business logic
├── src/Warden.CLI/            # CLI implementation
├── tests/                     # Test suite
└── docker/                    # Docker configurations
```

**WARNING:** Bu proje biraz eski. Feature'ların güncel hali için Panel'e bakılmalı!

### Reference (Svelte Panel - SOURCE OF TRUTH)
```
<WARDEN_PANEL_PATH>/
├── src/lib/types/            # TypeScript type definitions (REFERENCE!)
│   ├── warden.ts             # Issue, Report, Metrics models
│   ├── pipeline.ts           # Pipeline execution models
│   ├── frame.ts              # Validation frames
│   └── custom-rule.ts        # Rule definitions
├── src/routes/               # UI pages (feature reference)
│   ├── pipelines/            # Pipeline builder & runs
│   ├── projects/             # Project management
│   └── settings/             # Configuration
├── API_DESIGN.md             # Backend API specification
└── .session-notes*.md        # Latest features & decisions
```

### Target (Python Project)
```
<PROJECT_ROOT>/
├── src/warden/               # Main package (struktur TBD)
├── tests/                     # Python tests (pytest)
└── docs/                      # Documentation
```

**IMPORTANT:** Python mimarisi henüz belirlenmedi. C#'deki yapıyı birebir taklit etme!
- Panel requirements'ı karşılayacak
- Python best practices'e uygun olacak
- Modern, temiz, test edilebilir olacak
- Ama kesin yapı implementation sırasında belirlenecek

---

## 🚨 CRITICAL RULE: Panel First, C# Second

### Feature Implementation Workflow
```
1. Feature ihtiyacı ortaya çıktığında
   ↓
2. /Users/ibrahimcaglar/warden-panel-development/src/lib/types/ kontrol et
   ↓
3. İlgili TypeScript type'ı bul (warden.ts, pipeline.ts, frame.ts)
   ↓
4. API_DESIGN.md'de API contract'ına bak
   ↓
5. .session-notes*.md'de implementation detaylarına bak
   ↓
6. Python'a çevir (TypeScript modellerini 1:1 Python'a map'le)
   ↓
7. SONRA (opsiyonel) C# koduna bakabilirsin (SECONDARY reference)
```

### Before Implementing ANY Feature - Checklist
```bash
# 1. Panel Types kontrol
cat <WARDEN_PANEL_PATH>/src/lib/types/warden.ts
cat <WARDEN_PANEL_PATH>/src/lib/types/pipeline.ts
cat <WARDEN_PANEL_PATH>/src/lib/types/frame.ts

# 2. API Design kontrol
cat <WARDEN_PANEL_PATH>/API_DESIGN.md

# 3. Latest Session Notes kontrol
cat <WARDEN_PANEL_PATH>/.session-notes*.md

# 4. C# (SADECE gerekirse - SECONDARY)
find <WARDEN_CSHARP_PATH>/src -name "*FeatureName*"
```

---

## 🎯 Feature Status Map

### Panel'de MEVCUT (Implemented ✅)

**1. Issues System**
- TypeScript: `warden.ts` - WardenIssue, IssueSeverity, IssueState
- Python Models: WardenIssue, IssueSeverity, IssueState, StateTransition

**2. Pipeline System**
- TypeScript: `pipeline.ts` - PipelineRun, Step, SubStep, ValidationTestDetails
- Python Models: PipelineRun, Step, SubStep, ValidationTestDetails, PipelineSummary

**3. Validation Frames (6 adet)**
- TypeScript: `frame.ts`
- Frames: Security, Chaos, Fuzz, Property, Stress, Architectural
- Python Models: ValidationFrame (base), TestResult, TestAssertion

**4. Custom Rules**
- TypeScript: `custom-rule.ts`
- Python Models: CustomRule

**5. Reports & Metrics**
- TypeScript: `warden.ts` - GuardianReport, DashboardMetrics
- Python Models: GuardianReport, DashboardMetrics

### Panel'de PLANNED (🔜)
- Multi-Project Support
- Real-Time Updates (WebSocket)
- User Authentication

### C#'de VAR ama Panel'de YOK (⚠️)
- AST Analysis (Multi-Language) → Python'da basit versiyonla başla
- Memory System (Qdrant) → Python'da implement et
- Training Data Export → Python'da ekle, Panel Phase 2'de gelecek

---

## 🔧 Translation Rules

### Naming Convention Rules

| Aspect | TypeScript/C# | Python |
|--------|---------------|--------|
| Class Name | PascalCase | PascalCase |
| Function/Method | camelCase | snake_case |
| Variable | camelCase | snake_case |
| Constant | UPPER_CASE | UPPER_CASE |
| Private Field | _fieldName | _field_name |
| Interface | ICodeAnalyzer | CodeAnalyzer (ABC/Protocol) |

### Type Mapping Rules

| TypeScript/C# | Python |
|---------------|--------|
| string | str |
| number | int / float |
| boolean | bool |
| Date | datetime |
| Array<T> / List<T> | List[T] |
| Dictionary<K,V> | Dict[K, V] |
| T? / T \| null | Optional[T] |
| 'a' \| 'b' \| 'c' | Literal['a', 'b', 'c'] |
| enum | Enum |
| interface | @dataclass / Protocol |

### Critical JSON Rules

**Rule 1: Panel JSON is camelCase, Python internal is snake_case**
- Python model field: `file_path: str`
- JSON to Panel: `"filePath": "test.py"`
- JSON from Panel: `"filePath"` → `file_path`

**Rule 2: Enum values MUST match Panel exactly**
- Panel: `IssueSeverity.Critical = 0`
- Python: `IssueSeverity.CRITICAL = 0`

**Rule 3: Date format is ISO 8601**
- Python: `datetime.now().isoformat()`
- Panel: `"2025-12-19T17:30:00.123456"`

**Rule 4: Every model needs to_json() and from_json()**
- `to_json()` → camelCase for Panel
- `from_json()` → Parse camelCase to snake_case

---

## 📋 Python Implementation Principles

### DO ✅
- Use dataclasses for models
- Use type hints everywhere (typing module)
- Use async/await for I/O operations
- Use pathlib.Path (not string paths)
- Use structlog for logging
- Write docstrings (Google style)
- Use pytest for testing
- Use black for formatting
- Use ruff for linting
- Keep single responsibility per class
- Panel JSON uyumluluğunu test et

### DON'T ❌
- Don't use `import *`
- Don't use mutable default arguments
- Don't ignore type hints
- Don't mix tabs and spaces
- Don't use global variables
- Don't create God classes
- Don't write functions >50 lines
- Don't guess Panel JSON format (kontrol et!)

---

## 🔌 Core Dependencies

### Required Libraries
- qdrant-client (vector DB)
- openai (embeddings)
- pydantic (validation)
- structlog (logging)
- click (CLI)
- aiofiles (async file ops)
- pyyaml (config)
- httpx (async HTTP)
- pytest (testing)
- black (formatting)
- ruff (linting)

---

## 📊 Migration Strategy

### Core Principles
1. **Panel-First**: Her feature'ı Panel types'tan başlat
2. **Iterative**: Büyük bang değil, küçük adımlar
3. **Flexible**: Mimari ihtiyaca göre şekillensin
4. **Tested**: Her adımda test yaz
5. **Documented**: Kararları dokümante et

### Genel Yaklaşım
1. Panel'den başla (TypeScript types)
2. Python model'leri oluştur (Panel uyumlu JSON)
3. Business logic'i implement et
4. Test yaz
5. CLI/API ekle
6. Iterate!

### Component'ler (Sıralı Değil!)
- Core Models (Panel uyumlu JSON serialize/deserialize)
- Issue System (temel veri yapısı)
- Pipeline Execution (orchestration)
- Validation Frames (test stratejileri)
- Memory System (Qdrant - opsiyonel)
- Analysis Engine (kod analizi)
- CLI (kullanıcı interface)

**NOT:** Yukarıdaki liste sadece component'leri gösterir. Implementasyon sırası ve mimari proje gidişatına göre belirlenir.

---

## ⚠️ CRITICAL WARNINGS

### 1. Panel is Source of Truth
```
Priority: Panel TypeScript Types > Python Best Practices > C# Implementation
```

### 2. Don't Copy C# Architecture
C# projesi eski ve bazı yapıları değişmesi gerekiyor:
- C#'deki klasör yapısını birebir taklit etme
- C#'deki interface/class hiyerarşisini kopyalama
- Sadece genel mantık ve prensipleri al
- Python'a özgü, modern bir mimari tasarla

### 3. Always Check Panel First
Her feature için:
1. Panel types dizinine bak
2. API_DESIGN.md oku
3. Session notes oku
4. C# sadece genel mantık için referans (specific implementation değil!)

### 4. JSON Compatibility is Critical
- Python internally: snake_case
- JSON to/from Panel: camelCase
- Test her model için JSON serialize/deserialize

### 5. Enum Values Must Match Exactly
Panel'deki enum değerleri değiştirilmemeli!

### 6. Keep Models Simple
Over-engineering yapma. Panel'de ne varsa onu implement et.

### 7. Architecture is Flexible
- Kesin mimari yok, ihtiyaca göre şekillenecek
- C#'teki "Analysis/Classification/Validation" klasör yapısı sadece bir örnek
- Python'da daha iyi bir yapı bulabilirsin
- Önemli olan: Panel uyumlu, test edilebilir, temiz kod

---

## 🎯 Quick Reference Commands

### Panel Feature Check
```bash
# Feature var mı?
grep -r "FeatureName" <WARDEN_PANEL_PATH>/src/lib/types/

# Latest implementation notes
cat <WARDEN_PANEL_PATH>/.session-notes*.md | grep -A 10 "FeatureName"
```

### C# Reference Check (Secondary)
```bash
# Sadece Panel'de bulamazsanız
find <WARDEN_CSHARP_PATH>/src -name "*FeatureName*"
```

---

## 📞 Support Resources

- Panel TypeScript Types: `<WARDEN_PANEL_PATH>/src/lib/types/`
- API Contracts: `<WARDEN_PANEL_PATH>/API_DESIGN.md`
- Latest Features: `<WARDEN_PANEL_PATH>/.session-notes*.md`
- C# Reference: `<WARDEN_CSHARP_PATH>/src/Warden.Core/`

---

## 🌿 Git Branching Strategy

### Branch Structure
```
prod     (production)    → Stable releases only
  ↑
staging  (pre-prod)      → Testing & QA
  ↑
dev      (development)   → Daily development (default)
  ↑
main     (integration)   → Integration branch
```

### Branch Purposes

**`dev` (Development)**
- Daily development work
- Feature branches merge here
- Unstable, rapid changes
- CI/CD runs tests

**`staging` (Pre-Production)**
- QA & testing environment
- Merge from `dev` when features complete
- Mimics production
- Integration testing

**`prod` (Production)**
- Production releases only
- Merge from `staging` after QA approval
- Tagged releases (v1.0.0, v1.1.0)
- Stable, zero breaking changes

**`main` (Integration)**
- Integration branch (optional)
- Can be used as hotfix base
- Or keep in sync with `dev`

### Workflow

```bash
# Daily development
git checkout dev
git pull origin dev
# ... code changes ...
git add .
git commit -m "feat: Add feature X"
git push origin dev

# Ready for testing
git checkout staging
git merge dev
git push origin staging
# ... QA tests ...

# Ready for production
git checkout prod
git merge staging
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin prod --tags
```

### Protection Rules (Recommended)

- `prod`: Require PR approval, no direct push
- `staging`: Require PR approval
- `dev`: Allow direct push (fast iteration)
- `main`: Optional protection

---

**Last Updated**: 2025-12-19
**Migration Status**: 🚀 Ready to Start - session-start.md created
**Panel Reference**: Latest (check .session-notes for date)
**Git Branches**: ✅ dev, staging, prod created and pushed to remote

---

## 📝 Session Log

### 2025-12-19 - Initial Setup
**Decision:** Python mimarisi kesin belirlenmedi, esnek olacak
- ✅ session-start.md oluşturuldu (migration guide)
- ✅ warden_core_rules.md oluşturuldu (Python coding standards)
- ✅ Panel (warden-panel-development) SOURCE OF TRUTH olarak belirlendi
- ✅ C# (warden-csharp) sadece genel mantık için referans
- ✅ Priority: Panel TypeScript Types > Python Best Practices > C# Implementation
- ✅ Session start checklist eklendi (5 step workflow)
- ✅ `/mem-context` STEP 1 olarak eklendi (mandatory)
- ⚠️ IMPORTANT: C# yapısını birebir kopyalama!

**Files Created:**
- `<PROJECT_ROOT>/temp/session-start.md`
- `<PROJECT_ROOT>/temp/warden_core_rules.md`
- `<PROJECT_ROOT>/temp/warden_quick_reference.md`

**Session Workflow:**
1. `/mem-context` (load previous context)
2. Read session-start.md + warden_core_rules.md
3. Check Panel for latest features
4. Code with Panel-first approach
5. `/mem-save` at session end

---

## 🚀 Session Start Checklist

### STEP 1: Load Memory Context (FIRST!)
```bash
# Load previous session context
/mem-context
```
**⚠️ DO THIS FIRST!** Önceki session'ları hatırla, nerede kaldığını bil.

### STEP 2: Read Critical Files (MANDATORY)
```bash
# 1. Session start guide (migration strategy)
cat temp/session-start.md

# 2. Python coding rules (standards & best practices)
cat temp/warden_core_rules.md

# 3. Warden quick reference (core concepts - condensed version)
cat temp/warden_quick_reference.md
```

**WHY MANDATORY:**
- `session-start.md` → Migration strategy, Panel-first approach, critical paths, feature workflow
- `warden_core_rules.md` → Python standards, Panel JSON compatibility, security rules, type hints
- `warden_quick_reference.md` → Core concepts, validation strategies, architecture overview (condensed)

**⚠️ DO NOT SKIP:** These files contain critical rules that MUST be followed.

### STEP 3: Before Starting Any Code
- [ ] ✅ `/mem-context` çalıştırıldı (context loaded)
- [ ] ✅ session-start.md okundu (migration rules)
- [ ] ✅ warden_core_rules.md okundu (coding standards)
- [ ] ✅ warden_quick_reference.md okundu (core concepts)
- [ ] Check Panel types for latest changes
- [ ] Check .session-notes for new features
- [ ] Review API_DESIGN.md if needed
- [ ] Confirm feature exists in Panel
- [ ] Plan Python implementation
- [ ] Start coding (Panel → Python, NOT C# → Python)

### STEP 4: During Session
- Use `/mem-save` after important decisions/completions
- Update session log in this file if major changes

### STEP 5: Session End
```bash
/mem-save "Warden Core: Session summary - Completed: X, Next: Y, Decisions: Z"
```
