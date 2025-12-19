# Warden Core - Python Backend Kodlama Standartları ve Mimari Kararlar

> **Proje:** warden-core (Python Backend)
> **Son Güncelleme:** 2025-12-19
> **Durum:** PRODUCTION RULES - KESİN KURALLAR

---

## 📋 KODLAMA STANDARTLARI (NON-NEGOTIABLE)

### 1. Kod Organizasyon Kuralları (KRİTİK)

#### 1.1 Dosya Boyut Limiti
- ⚠️ **Maksimum 500 satır per Python file**
- Bu sınırı aşan dosyalar MUTLAKA modüllere bölünmeli
- Exception yok - bu kural ihlal edilemez

#### 1.2 Modül Organizasyonu
- ✅ Her modül tek bir sorumluluk (Single Responsibility)
- ✅ İlgili fonksiyonlar aynı modülde
- ❌ God modules/files YASAK

#### 1.3 Import Organizasyonu
```python
# ✅ GOOD: Organized imports
# Standard library
import os
from datetime import datetime
from typing import List, Optional

# Third-party
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Local
from warden.models.issue import WardenIssue
from warden.utils.sanitize import sanitize_input

# ❌ BAD: Disorganized, wildcard imports
from warden.models import *
import sys, os, json
```

#### 1.4 Naming Conventions (PEP 8)
```python
# ✅ GOOD
class CodeAnalyzer:        # PascalCase for classes
    pass

def analyze_code():        # snake_case for functions
    pass

MAX_RETRIES = 3           # UPPER_CASE for constants
user_name = "John"        # snake_case for variables
_internal_cache = {}      # Leading underscore for private

# ❌ BAD
class code_analyzer:      # Wrong case
def AnalyzeCode():        # Wrong case
maxRetries = 3            # Wrong case
```

---

### 2. Geliştirme Prensipleri (ALWAYS FOLLOW)

#### 2.1 KISS (Keep It Simple, Stupid)
- Basit, net çözümler > karmaşık olanlar
- Okumayı zorlaştıran clever code'dan kaçın
- Her fonksiyon/class anlaşılır olmalı
- List comprehension güzel ama 3 satırdan uzun olursa for loop kullan

#### 2.2 DRY (Don't Repeat Yourself)
- Ortak pattern'leri reusable utility/function'lara çıkar
- Code duplication görürsen HEMEN refactor et
- Aynı logic 2. kez yazılırken dur ve düşün

#### 2.3 SOLID Principles
1. **Single Responsibility:** Her class/function tek bir şey yapmalı
2. **Open-Closed:** Extension'a açık, modification'a kapalı
3. **Liskov Substitution:** Alt sınıflar üst sınıfın yerine geçebilmeli
4. **Interface Segregation:** Client'lar kullanmadıkları interface'lere depend etmemeli
5. **Dependency Inversion:** High-level modules low-level'a depend etmemeli

#### 2.4 YAGNI (You Aren't Gonna Need It)
- Sadece şu an gerekeni yap
- Over-engineering yapma
- "Belki ilerde lazım olur" düşüncesinden kaçın

---

### 3. Type Hints (ZORUNLU)

#### 3.1 Her Function Type Hint'li Olmalı
```python
# ✅ GOOD: Full type hints
from typing import List, Optional, Dict

def analyze_file(file_path: str, max_issues: int = 10) -> List[WardenIssue]:
    """Analyze a file and return issues."""
    pass

def get_user(user_id: str) -> Optional[User]:
    """Get user by ID, returns None if not found."""
    pass

# ❌ BAD: No type hints
def analyze_file(file_path, max_issues=10):
    pass
```

#### 3.2 Complex Types
```python
from typing import List, Dict, Optional, Union, Literal
from dataclasses import dataclass

# ✅ Type aliases for complex types
IssueDict = Dict[str, Union[str, int, List[str]]]
StatusType = Literal['running', 'success', 'failed']

@dataclass
class PipelineRun:
    id: str
    status: StatusType
    issues: List[WardenIssue]
    metadata: Optional[Dict[str, str]] = None
```

#### 3.3 Avoid `Any`
```python
from typing import Any

# ❌ BAD: Using Any
def process_data(data: Any) -> Any:
    pass

# ✅ GOOD: Specific types
def process_data(data: Dict[str, str]) -> List[WardenIssue]:
    pass
```

---

### 4. SAFETY FIRST Kuralları

#### 4.1 Fail Fast
```python
# ✅ GOOD: Early validation
def process_user(user_id: str) -> User:
    if not user_id or len(user_id) == 0:
        raise ValueError("Invalid user_id")

    if not user_id.isalnum():
        raise ValueError("user_id must be alphanumeric")

    # Process...

# ❌ BAD: Late validation
def process_user(user_id: str) -> User:
    # ... 100 lines of code ...
    if not user_id:
        raise ValueError("Too late!")
```

#### 4.2 Resource Cleanup (Context Managers)
```python
# ✅ GOOD: Automatic cleanup
from pathlib import Path

def read_file(file_path: Path) -> str:
    with open(file_path) as f:
        return f.read()

# Async version
async def read_file_async(file_path: Path) -> str:
    async with aiofiles.open(file_path) as f:
        return await f.read()

# ❌ BAD: Manual cleanup (error-prone)
def read_file(file_path: Path) -> str:
    f = open(file_path)
    content = f.read()
    f.close()  # What if exception before this?
    return content
```

#### 4.3 Idempotency
- Operasyonlar retry-safe olmalı
- Aynı işlem 2 kez çalışsa problem olmamalı
- Side-effect'ler kontrol edilmeli

```python
# ✅ GOOD: Idempotent
def save_issue(issue: WardenIssue) -> None:
    # Check if exists, update or insert
    existing = get_issue(issue.id)
    if existing:
        update_issue(issue)
    else:
        insert_issue(issue)

# ❌ BAD: Not idempotent
def save_issue(issue: WardenIssue) -> None:
    # Always insert, fails on retry!
    insert_issue(issue)
```

#### 4.4 Error Handling
```python
# ✅ GOOD: Specific exceptions
from typing import Optional

def get_user(user_id: str) -> User:
    if not user_id:
        raise ValueError("user_id cannot be empty")

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return user
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

# ❌ BAD: Bare except, swallowing errors
def get_user(user_id: str) -> Optional[User]:
    try:
        return db.query(User).filter(User.id == user_id).first()
    except:  # Never do this!
        return None
```

---

### 5. Panel JSON Compatibility (KRİTİK)

#### 5.1 camelCase for JSON, snake_case for Python
```python
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

class IssueSeverity(Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3

@dataclass
class WardenIssue:
    # Python internal: snake_case
    id: str
    file_path: str        # NOT filePath
    code_snippet: str     # NOT codeSnippet
    first_detected: datetime
    severity: IssueSeverity

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase)."""
        return {
            'id': self.id,
            'filePath': self.file_path,        # snake_case → camelCase
            'codeSnippet': self.code_snippet,
            'firstDetected': self.first_detected.isoformat(),
            'severity': self.severity.value    # Enum → int
        }

    @classmethod
    def from_json(cls, data: dict) -> 'WardenIssue':
        """Parse Panel JSON (camelCase) to Python."""
        return cls(
            id=data['id'],
            file_path=data['filePath'],        # camelCase → snake_case
            code_snippet=data['codeSnippet'],
            first_detected=datetime.fromisoformat(data['firstDetected']),
            severity=IssueSeverity(data['severity'])
        )
```

#### 5.2 Enum Values MUST Match Panel
```python
# ✅ MUST match Panel TypeScript exactly
class IssueSeverity(Enum):
    CRITICAL = 0  # Panel: Critical = 0
    HIGH = 1      # Panel: High = 1
    MEDIUM = 2    # Panel: Medium = 2
    LOW = 3       # Panel: Low = 3

class IssueState(Enum):
    OPEN = 0      # Panel: Open = 0
    RESOLVED = 1  # Panel: Resolved = 1
    SUPPRESSED = 2  # Panel: Suppressed = 2
```

#### 5.3 Date Format (ISO 8601)
```python
from datetime import datetime

# ✅ GOOD: ISO 8601
def serialize_date(dt: datetime) -> str:
    return dt.isoformat()

# Panel expects: "2025-12-19T17:30:00.123456"
now = datetime.now()
json_date = now.isoformat()  # "2025-12-19T17:30:00.123456"
```

---

### 6. Security (ASSUME MALICIOUS INPUTS)

#### 6.1 Input Validation
```python
from pathlib import Path

# ✅ GOOD: Validate everything
def read_user_file(file_path: str) -> str:
    # Validate path
    if not file_path:
        raise ValueError("file_path cannot be empty")

    path = Path(file_path)

    # Prevent path traversal
    if ".." in file_path:
        raise ValueError("Path traversal not allowed")

    # Check file exists
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Check size
    if path.stat().st_size > 10 * 1024 * 1024:  # 10MB
        raise ValueError("File too large")

    with open(path) as f:
        return f.read()

# ❌ BAD: No validation
def read_user_file(file_path: str) -> str:
    with open(file_path) as f:  # Path traversal, arbitrary file read!
        return f.read()
```

#### 6.2 SQL Injection Prevention
```python
# ✅ GOOD: Parameterized queries
from sqlalchemy import text

def get_user(user_id: str) -> User:
    query = text("SELECT * FROM users WHERE id = :user_id")
    result = db.execute(query, {"user_id": user_id})
    return result.first()

# ❌ BAD: String concatenation
def get_user(user_id: str) -> User:
    query = f"SELECT * FROM users WHERE id = '{user_id}'"  # SQL INJECTION!
    result = db.execute(query)
    return result.first()
```

#### 6.3 Command Injection Prevention
```python
import subprocess
from shlex import quote

# ✅ GOOD: Array arguments, no shell
def run_analyzer(file_path: str) -> str:
    result = subprocess.run(
        ['analyzer', '--file', file_path],
        shell=False,  # IMPORTANT!
        capture_output=True,
        text=True
    )
    return result.stdout

# ⚠️ ACCEPTABLE: If shell needed, quote everything
def run_analyzer(file_path: str) -> str:
    safe_path = quote(file_path)
    result = subprocess.run(
        f'analyzer --file {safe_path}',
        shell=True,
        capture_output=True
    )
    return result.stdout

# ❌ BAD: Shell injection
def run_analyzer(file_path: str) -> str:
    result = subprocess.run(
        f'analyzer --file {file_path}',  # INJECTION!
        shell=True,
        capture_output=True
    )
    return result.stdout
```

#### 6.4 Secrets Management
```python
import os
from dotenv import load_dotenv

# ✅ GOOD: Environment variables
load_dotenv()

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
if not QDRANT_API_KEY:
    raise ValueError("QDRANT_API_KEY not set")

# ❌ BAD: Hardcoded secrets
QDRANT_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."  # NEVER!
```

---

### 7. Memory Management (KRİTİK - SESSION CONTINUITY)

#### 7.1 `/mem-save` Kullanım Kuralı
- ⚠️ **Her önemli adımda `/mem-save` ZORUNLU**
- Session'lar arası context kaybını önler
- Claude Code unutabilir, memory unutmaz

#### 7.2 Ne Zaman `/mem-save` Kullanılmalı?

**ZORUNLU Durumlar:**
1. **Yeni bir feature/module tamamlandığında**
   ```bash
   /mem-save "Warden Core: WardenIssue model implemented. Panel JSON compat tested. Next: Pipeline models."
   ```

2. **Önemli mimari karar alındığında**
   ```bash
   /mem-save "Warden Core: FastAPI seçildi. Reason: Modern, async support, automatic OpenAPI docs. Alternative: Flask rejected (sync only)."
   ```

3. **Bug fix yapıldığında**
   ```bash
   /mem-save "Warden Core: JSON serialization bug fixed. Enum values were strings instead of ints. Panel now receives correct format."
   ```

4. **Session sonu (devam edilecekse)**
   ```bash
   /mem-save "Warden Core: Session end. Completed: Issue models, JSON serialization. Next: Pipeline execution engine, validation frames."
   ```

5. **Blocker/issue bulunduğunda**
   ```bash
   /mem-save "Warden Core: BLOCKER - Qdrant Cloud connection fails. Workaround: Using local Qdrant. TODO: Check API key, network."
   ```

6. **Panel integration test edildiğinde**
   ```bash
   /mem-save "Warden Core: Panel integration tested. JSON format matches Panel TypeScript types. camelCase conversion working correctly."
   ```

#### 7.3 Memory Save Formatı
```
Warden Core: [Kısa başlık]
- Ne yapıldı (completed)
- Ne yapılacak (next)
- Kararlar (decisions, optional)
- Blockerlar (issues, optional)
```

---

### 8. Observability (TRANSPARENCY)

#### 8.1 Structured Logging
```python
import structlog

logger = structlog.get_logger()

# ✅ GOOD: Context-rich logging
logger.info(
    "analysis_started",
    file_path=file_path,
    analyzer="roslyn",
    expected_issues=10
)

logger.error(
    "analysis_failed",
    file_path=file_path,
    error=str(e),
    error_type=type(e).__name__,
    stack_trace=traceback.format_exc()
)

# ❌ BAD: Generic logging
logger.info("Starting analysis")
logger.error(f"Error: {e}")
```

#### 8.2 Log Levels
```python
logger.debug("cache_hit", key=cache_key)        # Development
logger.info("request_processed", duration=0.5)  # Normal flow
logger.warning("rate_limit_approaching", remaining=10)  # Potential issue
logger.error("database_connection_failed", retries=3)  # Failure
logger.critical("disk_space_full", available_mb=0)  # System failure
```

#### 8.3 Performance Metrics
```python
import time

# ✅ GOOD: Track performance
def analyze_code(code: str) -> AnalysisResult:
    start = time.perf_counter()

    result = _do_analysis(code)

    duration = time.perf_counter() - start

    if duration > 1.0:
        logger.warning(
            "slow_analysis",
            duration=duration,
            code_length=len(code)
        )

    return result
```

---

### 9. Async/Await Best Practices

#### 9.1 Use Async for I/O
```python
import aiofiles
from httpx import AsyncClient

# ✅ GOOD: Async I/O
async def read_file(file_path: str) -> str:
    async with aiofiles.open(file_path) as f:
        return await f.read()

async def fetch_data(url: str) -> dict:
    async with AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# ❌ BAD: Sync I/O in async function
async def read_file(file_path: str) -> str:
    with open(file_path) as f:  # Blocking!
        return f.read()
```

#### 9.2 Don't Mix Sync and Async
```python
# ✅ GOOD: Consistent async
async def process_pipeline(pipeline_id: str) -> PipelineResult:
    config = await load_config(pipeline_id)
    issues = await analyze_code(config.file_path)
    return await save_results(issues)

# ❌ BAD: Mixed sync/async
async def process_pipeline(pipeline_id: str) -> PipelineResult:
    config = load_config_sync(pipeline_id)  # Blocking!
    issues = await analyze_code(config.file_path)
    save_results_sync(issues)  # Blocking!
    return result
```

---

### 10. Testing (MANDATORY)

#### 10.1 Every Module Has Tests
```python
# src/warden/models/issue.py
@dataclass
class WardenIssue:
    pass

# tests/test_issue.py
import pytest
from warden.models.issue import WardenIssue, IssueSeverity

def test_issue_to_json():
    issue = WardenIssue(
        id="W001",
        file_path="test.py",
        severity=IssueSeverity.CRITICAL
    )

    json_data = issue.to_json()

    assert json_data['id'] == "W001"
    assert json_data['filePath'] == "test.py"  # camelCase
    assert json_data['severity'] == 0  # Enum value

def test_issue_from_json():
    json_data = {
        'id': 'W001',
        'filePath': 'test.py',
        'severity': 0
    }

    issue = WardenIssue.from_json(json_data)

    assert issue.id == "W001"
    assert issue.file_path == "test.py"  # snake_case
    assert issue.severity == IssueSeverity.CRITICAL
```

#### 10.2 Test Panel JSON Compatibility
```python
# tests/test_panel_integration.py
import pytest
from warden.models.issue import WardenIssue

def test_panel_json_roundtrip():
    """Ensure Panel can parse our JSON."""
    original = WardenIssue(
        id="W001",
        file_path="test.py",
        code_snippet="def foo(): pass",
        severity=IssueSeverity.CRITICAL
    )

    # Serialize to Panel JSON
    json_data = original.to_json()

    # Panel expectations
    assert 'filePath' in json_data  # camelCase
    assert 'file_path' not in json_data  # NOT snake_case
    assert isinstance(json_data['severity'], int)  # NOT Enum

    # Deserialize back
    parsed = WardenIssue.from_json(json_data)

    assert parsed.id == original.id
    assert parsed.file_path == original.file_path
```

---

## 🏗️ MİMARİ KARARLAR

### 1. Tech Stack

#### Backend
- **Language:** Python 3.11+
- **Framework:** FastAPI (async support, automatic OpenAPI)
- **Type Checking:** mypy (strict mode)
- **Formatting:** black
- **Linting:** ruff
- **Testing:** pytest + pytest-asyncio

#### Dependencies
- **Vector DB:** Qdrant (cloud or local)
- **Embeddings:** OpenAI / Azure OpenAI
- **Validation:** Pydantic
- **Logging:** structlog
- **HTTP Client:** httpx (async)
- **File I/O:** aiofiles (async)

### 2. Panel Integration (SOURCE OF TRUTH)

#### Reference Paths
```
Panel TypeScript Types: /Users/ibrahimcaglar/warden-panel-development/src/lib/types/
- warden.ts          → Issue, Report, Metrics models
- pipeline.ts        → Pipeline execution models
- frame.ts           → Validation frames
```

#### Implementation Order
1. Check Panel TypeScript type
2. Implement Python model (snake_case internally)
3. Add to_json() / from_json() (camelCase conversion)
4. Test Panel JSON compatibility
5. Implement business logic

### 3. Don't Copy C# Architecture

⚠️ **CRITICAL:** C# project (warden-csharp) is LEGACY
- C#'deki klasör yapısını birebir taklit etme
- C#'deki interface/class hiyerarşisini kopyalama
- Sadece genel mantık ve prensipleri al
- Python'a özgü, modern bir mimari tasarla

### 4. Architecture is Flexible

- Kesin mimari yok, ihtiyaca göre şekillenecek
- Python'da daha iyi bir yapı bulabilirsin
- Önemli olan: Panel uyumlu, test edilebilir, temiz kod

---

## 🎯 PROJE HEDEFI

**Anti-fragile, self-healing, transparent Python backend** - stress altında daha iyi çalışan sistem.

### Karakteristikler
- **Anti-fragile:** Hatalar sistemi güçlendirir
- **Self-healing:** Otomatik recovery mekanizmaları
- **Transparent:** Her adım loglanır ve görülebilir
- **Resilient:** Network/service failures'a dayanıklı
- **Secure:** Her input potansiyel tehdit olarak görülür
- **Observable:** Her failure mode trace edilebilir
- **Panel-Compatible:** TypeScript types ile 100% uyumlu JSON

---

## 📝 NOTLAR

### Version History
- **v1.0.0** - Initial Python backend rules (2025-12-19)

### Enforcement
Bu kurallar **ihlal edilemez**. Code review'da bu kurallara uygunluk kontrol edilmelidir.

### Updates
Kurallar değiştiğinde bu dosya güncellenmeli ve `/mem-save` ile memory'e kaydedilmelidir.

---

**Son Güncelleme:** 2025-12-19
**Durum:** ACTIVE - Tüm yeni kod bu kurallara uymalı
**Panel Reference:** /Users/ibrahimcaglar/warden-panel-development/src/lib/types/
