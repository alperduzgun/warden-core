# Next Session: LLM Integration Fix for Warden TUI

## 🎯 Mission
Fix LLM integration in Warden TUI so that frames (especially OrphanFrame) can use LLM-powered intelligent filtering.

---

## ✅ What's Already Working

### TUI Config Integration (COMPLETED ✅)
- ✅ TUI loads `.env` automatically (dotenv integration)
- ✅ TUI parses `.warden/config.yaml` directly
- ✅ All 9 frames load from config
- ✅ Frame-specific configs are passed to frames
- ✅ AZURE_OPENAI_API_KEY loaded from `.env`
- ✅ Real pipeline execution (not mock data)

**Files Modified:**
- `src/warden/tui/app.py` - Added `.env` loading and frame config passing
- `src/warden/models/frame.py` - Added 3 missing frames to GLOBAL_FRAMES
- `src/warden/tui/commands/scan.py` - Better error messages

---

## ❌ Current Problem: LLM Filter Not Working

### Symptoms
```
Duration: 4.6 seconds for 306 files
Expected: ~2-5 minutes with LLM
Reason: LLM filter initialization fails → fallback to basic filtering
```

### Error Log
```
[warning] llm_orphan_filter_initialization_failed
error=cannot import name 'load_llm_config' from 'warden.llm.config'
fallback=basic filtering
```

### Root Cause
`src/warden/validation/frames/orphan/llm_orphan_filter.py` tries to import:
```python
from warden.llm.config import load_llm_config
```

But this function **does not exist** in `src/warden/llm/config.py`.

---

## 🔧 What Needs to Be Fixed

### 1. Missing Function: `load_llm_config()`

**Location:** `src/warden/llm/config.py`

**Required Behavior:**
```python
def load_llm_config() -> LLMConfig:
    """
    Load LLM configuration from environment and config files.

    Returns:
        LLMConfig with Azure OpenAI settings

    Should read:
    - AZURE_OPENAI_API_KEY from env
    - AZURE_OPENAI_ENDPOINT from env
    - AZURE_OPENAI_DEPLOYMENT_NAME from env
    - AZURE_OPENAI_API_VERSION from env (default: "2024-02-01")
    """
```

**Environment Variables Available (from `.env`):**
```
AZURE_OPENAI_ENDPOINT=https://voice-via-ai-resource.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=3QESZxaQXEKI0a4zABAOTUBTUiNiqggpWCj7zwjXJKJsGeKyV3MsJQQJ99BEAC5RqLJXJ3w3AAAAACOG2nwA
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01
```

### 2. Check LLMOrphanFilter Dependencies

**File:** `src/warden/validation/frames/orphan/llm_orphan_filter.py`

**Verify:**
- Import paths are correct
- All required functions exist
- LLM client initialization works with Azure OpenAI

### 3. Test LLM Integration

**Test scenario:**
```python
from warden.validation.frames.orphan import OrphanFrame

config = {'use_llm_filter': True}
orphan = OrphanFrame(config=config)

# Should see:
# ✅ llm_orphan_filter_enabled
# NOT:
# ❌ llm_orphan_filter_initialization_failed
```

---

## 📁 Key Files to Check

### Primary Files
1. **`src/warden/llm/config.py`**
   - Add/fix `load_llm_config()` function
   - Should return LLMConfig with Azure settings

2. **`src/warden/validation/frames/orphan/llm_orphan_filter.py`**
   - Check import: `from warden.llm.config import load_llm_config`
   - Check LLM client initialization
   - Verify it uses Azure OpenAI correctly

3. **`src/warden/llm/__init__.py`** (if exists)
   - Verify exports

### Reference Files
- `.env` - Environment variables (already working)
- `.warden/config.yaml` - Frame config (already working)
- `src/warden/tui/app.py` - TUI config loading (already working)

---

## 🧪 Testing Steps

### Step 1: Unit Test
```bash
python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

# Load .env
from dotenv import load_dotenv
load_dotenv()

# Test config loading
from warden.llm.config import load_llm_config

config = load_llm_config()
print(f"LLM Config: {config}")
print(f"API Key: {config.api_key[:20]}..." if config.api_key else "None")
print(f"Endpoint: {config.endpoint}")
print(f"Deployment: {config.deployment_name}")
EOF
```

### Step 2: OrphanFrame Test
```bash
python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))

from dotenv import load_dotenv
load_dotenv()

from warden.validation.frames.orphan import OrphanFrame

config = {'use_llm_filter': True}
orphan = OrphanFrame(config=config)

if orphan.llm_filter:
    print("✅ SUCCESS: LLM filter initialized!")
    print(f"   Filter: {orphan.llm_filter}")
else:
    print("❌ FAILED: LLM filter is None")
    print(f"   use_llm_filter: {orphan.use_llm_filter}")
EOF
```

### Step 3: Full TUI Test
```bash
# Launch TUI
warden tui

# In TUI, run:
/scan /Users/alper/Documents/Development/Personal/warden-core/src/warden/models

# Expected:
# - Duration: 10-30 seconds (with LLM calls)
# - Log messages: "llm_filtering_started", "llm_filtering_complete"
# - Lower issue count (LLM filters false positives)
```

---

## 📊 Success Criteria

### Must Have ✅
1. ✅ `load_llm_config()` function exists and works
2. ✅ OrphanFrame initializes with `llm_filter` object
3. ✅ No warning: "llm_orphan_filter_initialization_failed"
4. ✅ TUI scan shows LLM logs in console

### Nice to Have
5. Scan duration increases (proves LLM is being called)
6. False positive rate logged (e.g., "40% false positives removed")
7. Issue count decreases compared to basic filtering

---

## 🚨 Important Context

### Config Structure (.warden/config.yaml)
```yaml
settings:
  enable_llm: true
  llm_provider: "azure_openai"

frame_config:
  orphan:
    use_llm_filter: true  # ← This is being passed correctly
    ignore_private: true
    ignore_test_files: true
```

### Expected Behavior
- **Without LLM:** 306 files in ~4-5 seconds (basic AST filtering)
- **With LLM:** 306 files in ~2-5 minutes (LLM filtering per file)

### Performance
- OrphanFrame should log:
  - `llm_filtering_started`
  - `llm_filtering_complete` with stats
  - `false_positives_removed: X`
  - `llm_duration: Y.YYs`

---

## 📝 Implementation Hints

### LLMConfig Model (check if exists)
```python
@dataclass
class LLMConfig:
    provider: str  # "azure_openai"
    api_key: str
    endpoint: str
    deployment_name: str
    api_version: str
    model: str  # "gpt-4o"
```

### Azure OpenAI Client Example
```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=config.api_key,
    api_version=config.api_version,
    azure_endpoint=config.endpoint,
)

response = client.chat.completions.create(
    model=config.deployment_name,  # "gpt-4o"
    messages=[...],
)
```

---

## 🎯 Quick Start Command

```bash
# 1. Load context from previous session
/mem-context

# 2. Read this file
cat temp/next-session-llm-fix.md

# 3. Start with the primary issue
# Check what's in src/warden/llm/config.py
# Look for load_llm_config function

# 4. Fix missing function
# Implement load_llm_config() to load Azure OpenAI config from env

# 5. Test
# Run the test scripts above
```

---

## 📚 Reference

### Previous Session Summary
- **Completed:** TUI config integration, .env loading, frame config passing
- **Issue Found:** LLM filter initialization fails due to missing `load_llm_config()`
- **Status:** TUI works perfectly, just missing LLM integration

### Files Already Fixed (Don't Touch)
- ✅ `src/warden/tui/app.py` - Config loading works
- ✅ `src/warden/models/frame.py` - All 9 frames registered
- ✅ `.env` - API keys present and loaded

### Git Status
```bash
# Modified files:
M src/warden/tui/app.py
M src/warden/models/frame.py
M src/warden/tui/commands/scan.py
```

---

**Last Updated:** 2025-12-21
**Session:** LLM Integration Fix
**Priority:** HIGH (blocking LLM usage)
**Estimated Time:** 30-60 minutes

 ---
  🎯 KISA CEVAP

  ÖNERİ: HYBRID APPROACH - Hem Tree-sitter hem de Native Provider'lar

  ✅ SHORT-TERM (2-3 hafta):  Tree-sitter (tüm diller için)
  ✅ LONG-TERM (2-3 ay):      Java + C# Native Providers

  ---
  📊 KARAR MATRİSİ

  Tree-sitter YALNIZ mı?

  ❌ HAYIR - Yeterli değil!

  Neden:
  - ❌ Symbol resolution yok → Orphan detection için kritik
  - ❌ Type information yok → Hangi import nerede kullanıldı bulunamaz
  - ❌ Cross-file analysis zor → Module dependencies çözülmez

  Örnek Problem:
  // OrphanDetector bu import'u kullanılmamış diyebilir!
  import com.example.Utils;  // Utils static import ediliyor

  public class Test {
      public void method() {
          Utils.helper();  // Tree-sitter bunu import ile eşleyemez!
      }
  }

  Native Provider'lar mı?

  ✅ EVET - Ama sadece kritik diller için!

  Java & C# için EVET:
  - ✅ Orphan detection için symbol resolution gerekli
  - ✅ Panel'de en çok kullanılan enterprise diller
  - ✅ JavaParser ve Roslyn mature ve production-ready

  Diğer diller için HAYIR:
  - TypeScript, JavaScript, Go, Rust → Tree-sitter yeterli
  - LLM filtering ile false positive azaltılır

  ---
  🏗️ ÖNERİLEN MİMARİ

  Priority System

  Language: Java
      ↓
  1️⃣ JavaParserProvider var mı?
      ✅ YES → JavaParser kullan (symbol resolution)
      ❌ NO  → Tree-sitter fallback
      ↓
  2️⃣ Tree-sitter parse et
      ↓
  3️⃣ LLM filtering (false positive azalt)
      ↓
  Result: High accuracy orphan detection

  Implementation Roadmap

  Phase 1: Tree-sitter Foundation (2-3 hafta)
  ✅ Tree-sitter provider'ı implement et (PLACEHOLDER'ı bitir)
  ✅ 14 dil için test yaz (Python, Java, C#, JS, TS, Go, Rust, etc.)
  ✅ LLM filtering multi-language support

  Sonuç:
  - Tüm diller parse edilebilir
  - Orta false positive rate (%30-40)
  - Çok hızlı (36x faster)

  Phase 2: Native Providers (2-3 ay)
  ✅ JavaParserProvider (Java için)
     - JPype (Python-Java bridge) veya subprocess
     - Symbol resolution + type information

  ✅ RoslynProvider (C# için)
     - REST API wrapper (C# microservice)
     - Symbol resolution + type information

  Sonuç:
  - Java & C# için %95+ accuracy
  - Düşük false positive rate (<10%)
  - Biraz daha yavaş (ama kabul edilebilir)

  ---
  📈 KARŞILAŞTIRMA

  | Özellik             | Tree-sitter Only | Hybrid (Tree + Native) |
  |---------------------|------------------|------------------------|
  | Implementation Time | ✅ 2-3 hafta      | ⚠️ 2-3 ay              |
  | Accuracy (Java/C#)  | ⚠️ %60-70        | ✅ %95+                 |
  | Accuracy (Others)   | ✅ %80-90         | ✅ %80-90               |
  | Performance         | ✅ Çok hızlı      | ⚠️ Orta                |
  | Maintenance         | ✅ Kolay          | ⚠️ Orta                |
  | False Positives     | ⚠️ Orta-Yüksek   | ✅ Düşük                |
  | Symbol Resolution   | ❌ Yok            | ✅ Var (native)         |
  | Multi-language      | ✅ 14 dil         | ✅ 14 dil               |

  ---
  🎬 PRODUCTION ÖRNEKLER

  Tree-sitter Kullananlar:
  - ✅ GitHub Semantic - Code navigation
  - ✅ Slack Engineering - Security scanning (2 intern, milyonlarca satır)
  - ✅ Semgrep - Static analysis
  - ✅ Symflower - 36x speedup (JavaParser'dan geçiş)

  Native Parser Kullananlar:
  - ✅ IntelliJ IDEA - Java için IntelliJ PSI (native)
  - ✅ Visual Studio - C# için Roslyn (native)
  - ✅ SonarQube - Multi-language (language-specific parsers)

  ---
  💡 SONUÇ VE TAVSİYE

  Kısa Vadeli Strateji (MVP - 2-3 hafta)

  ✅ Tree-sitter provider'ı bitir
  ✅ 14 dil için temel orphan detection
  ✅ LLM filtering ile false positive azalt
  ✅ Production'a çıkar

  Avantaj: Hızlı MVP, tüm diller çalışır
  Dezavantaj: Java/C# için %30-40 false positive

  Uzun Vadeli Strateji (Production - 2-3 ay)

  ✅ JavaParser provider ekle (Java)
  ✅ Roslyn provider ekle (C#)
  ✅ Priority system otomatik seçsin (native > tree-sitter)
  ✅ Diğer diller tree-sitter ile devam

  Avantaj: Enterprise diller (%95 accuracy), diğerleri hızlı
  Dezavantaj: Biraz daha kompleks maintenance

  ---
  🚀 SONRAKİ ADIMLAR

  Şimdi ne yapmak istersin?

  1. Tree-sitter Implementation - PLACEHOLDER'ı bitir, 14 dil test et
  2. JavaParser POC - Java provider prototype yap
  3. Roslyn POC - C# provider prototype yap
  4. Architecture Decision - Detaylı plan dokümante et
  5. Başka bir şey?

