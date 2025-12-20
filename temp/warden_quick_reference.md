# Warden Quick Reference - Core Concepts

> **Purpose:** Essential Warden concepts for Python migration
> **Last Updated:** 2025-12-21
> **Status:** Condensed reference (original: warden_project_context.md)

---

## 🎯 VISION

### Problem
```
2024+ World: Developer → AI generates code → "looks good" → merge
Result: Untested, fragile code reaches production
```

### Solution: Warden
```
"AI writes code. Warden guards production."

Developer → AI generates code → WARDEN validates → Safe PR
```

### Motto
> "Happy path is a myth. Warden proves your code survives reality."

---

## 🧠 CORE PRINCIPLES

```yaml
philosophy:
  - "Working" ≠ "Production-ready"
  - Happy path is a myth, edge cases are real
  - AI code is untrusted until proven
  - Fail fast, fail loud, fail safe

principles:
  - KISS: Keep It Simple, Stupid
  - DRY: Don't Repeat Yourself
  - SOLID: Single responsibility, Open-closed, etc.
  - YAGNI: You Aren't Gonna Need It

safety_rules:
  - Fail fast, fail loud
  - Dispose properly (resources, connections, handles)
  - Ensure idempotency where applicable
  - Strict types everywhere
  - Assume ALL inputs are malicious
  - Sanitize early, validate often
  - Never trust AI-generated code blindly

observability:
  - Structured logging for every failure mode
  - Correlation IDs for tracing
  - Metrics for critical paths
```

---

## 🔬 VALIDATION STRATEGIES (6 Frames)

### Frame-Based Architecture
- Each strategy = independent `ValidationFrame` implementation
- Parallel execution with priority ordering
- Pluggable pattern (easy to add new frames)
- User sees "Validation Strategies" not "frames"

### 1. Security Analysis (Priority: CRITICAL - Blocker)
```yaml
when:
  - ALL code (mandatory check)
  - User input handling
  - Authentication/Authorization
  - Data storage

detect:
  - SQL injection patterns
  - XSS vulnerabilities
  - Credential exposure (API keys, passwords)
  - Insecure deserialization
  - Path traversal
  - Command injection
  - Hardcoded secrets

verify:
  - Input sanitization present
  - Parameterized queries used
  - Secrets not in code
  - Authentication properly implemented
```

### 2. Chaos Engineering (Resilience)
```yaml
when:
  - Distributed systems
  - Async/await heavy code
  - External API calls
  - Database connections

simulate:
  - Network failures / timeouts
  - Connection drops mid-operation
  - Dependent service outages
  - Race conditions

verify:
  - Graceful degradation
  - Retry mechanisms with backoff
  - Circuit breaker patterns
  - Fallback behaviors
  - No cascading failures
```

### 3. Fuzz Testing (Edge Cases)
```yaml
when:
  - User input handling
  - JSON/XML parsing
  - File processing
  - Query string parsing

inject:
  - null, empty, whitespace
  - Max-length strings (1MB+)
  - Unicode edge cases (emoji, RTL, zero-width)
  - Malformed JSON/XML
  - SQL injection attempts
  - XSS payloads
  - Negative numbers, MAX_INT, MIN_INT

verify:
  - No crashes
  - No unhandled exceptions
  - Proper error messages
  - Type safety maintained
```

### 4. Property-Based Testing (Logic)
```yaml
when:
  - Mathematical calculations
  - Business rules
  - State machines
  - Data transformations

verify_properties:
  - Idempotency: f(f(x)) == f(x)
  - Commutativity: f(a,b) == f(b,a)
  - Associativity: f(f(a,b),c) == f(a,f(b,c))
  - Identity: f(x, identity) == x
  - Invariant preservation
  - Round-trip: decode(encode(x)) == x
```

### 5. Stress Testing (Scale)
```yaml
when:
  - Loops processing collections
  - Streaming data
  - Real-time features
  - High-frequency operations

simulate:
  - 10K, 100K, 1M iterations
  - Concurrent access (100, 1000 threads)
  - Memory pressure
  - GC pressure

verify:
  - No memory leaks
  - Stable memory footprint
  - Acceptable latency (P99)
  - No thread starvation
  - Proper resource cleanup
```

### 6. Architectural Consistency (File Organization)
```yaml
when:
  - New files created
  - Code refactoring
  - Project structure changes

detect:
  - XxxFrame not in /Xxx/ directory
  - Package-by-layer anti-patterns
  - File/directory naming mismatches
  - Namespace-directory structure misalignment

verify:
  - Consistent file organization
  - Clear architectural boundaries
  - Proper separation of concerns
```

---

## 🏗️ ARCHITECTURE OVERVIEW

### Python Project Structure (Flexible - NOT Final!)
```
<PROJECT_ROOT>/
├── src/warden/
│   ├── core/
│   │   ├── models/              # Warden models (Panel-compatible JSON)
│   │   ├── analysis/            # Code analysis engine
│   │   ├── classification/      # Code characteristic detection
│   │   ├── validation/          # Validation frames (6 strategies)
│   │   ├── pipeline/            # Orchestration
│   │   └── memory/              # Context storage (optional)
│   ├── tui/                     # Terminal UI (Textual)
│   ├── api/                     # REST API (FastAPI)
│   └── cli/                     # CLI commands
├── tests/                       # Pytest tests
├── docs/                        # Documentation
└── temp/                        # Session files (this file!)
```

**IMPORTANT:** This is NOT a blueprint to copy! Python architecture is flexible.
- Panel requirements drive structure
- Python best practices apply
- Modern, clean, testable code
- Exact structure emerges during implementation

---

## 📦 CORE MODELS (Panel-Compatible)

### WardenIssue
```python
@dataclass
class WardenIssue:
    id: str
    file_path: str                 # Python: snake_case
    code_snippet: str
    severity: IssueSeverity        # Enum(CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3)
    first_detected: datetime

    def to_json(self) -> dict:
        """Panel JSON: camelCase"""
        return {
            'id': self.id,
            'filePath': self.file_path,     # → camelCase
            'codeSnippet': self.code_snippet,
            'severity': self.severity.value  # → int
        }
```

### ValidationFrame
```python
class ValidationFrame(ABC):
    """Base class for all validation strategies"""

    @abstractmethod
    async def execute(
        self,
        file: CodeFile,
        characteristics: CodeCharacteristics
    ) -> ValidationFrameResult:
        pass
```

---

## 🔧 WORKFLOW

### Full Pipeline (warden start)
```
1. Analysis    → Detect issues, score code
2. Classification → Identify code characteristics
3. Validation  → Run appropriate validation frames
4. Report      → Generate findings
```

### Individual Commands
```bash
warden analyze <file>      # Code analysis only
warden classify <file>     # Suggest validation strategies
warden validate <file>     # Run validation frames
warden scan <directory>    # Full project scan
warden report              # Generate report
```

---

## 🎯 MIGRATION PRIORITIES

### What to Focus On
1. **Panel JSON Compatibility** - Critical!
   - Python models: snake_case internally
   - JSON output: camelCase for Panel
   - Enum values match exactly
   - ISO 8601 dates

2. **Validation Frames** - Core value
   - 6 validation strategies
   - Pluggable architecture
   - Priority-based execution
   - Panel-compatible results

3. **Core Models** - Foundation
   - WardenIssue, PipelineRun, ValidationFrame
   - to_json() / from_json() methods
   - Type hints everywhere

4. **Simple First** - Iterate
   - Start minimal
   - Add features incrementally
   - Test Panel integration early
   - Don't over-engineer

### What to Defer
- Memory system (optional)
- Training data export (Phase 2)
- Advanced analytics (later)
- Multi-language AST (start simple)

---

## ⚠️ CRITICAL WARNINGS

### 1. Panel is Source of Truth
```
Priority: Panel TypeScript Types > Python Best Practices > C# Code
```

### 2. Don't Copy C# Architecture
- C# project is legacy
- Don't replicate folder structure 1:1
- Take general principles only
- Design Python-native architecture

### 3. JSON Compatibility is Critical
- Test every model's to_json() / from_json()
- Enum values must match Panel exactly
- Date format: ISO 8601
- camelCase in JSON, snake_case in Python

### 4. Keep Models Simple
- Implement what Panel needs
- No over-engineering
- Validate early with Panel team

---

## 📚 REFERENCE LOCATIONS

**Panel (Source of Truth):**
- TypeScript types: `<WARDEN_PANEL_PATH>/src/lib/types/`
- API contracts: `<WARDEN_PANEL_PATH>/API_DESIGN.md`
- Latest features: `<WARDEN_PANEL_PATH>/.session-notes*.md`

**C# (Secondary Reference):**
- Core logic: `<WARDEN_CSHARP_PATH>/src/Warden.Core/`
- Use for: General concepts, validation ideas
- Don't use for: Exact implementation, architecture

**Python (Target):**
- Project root: `<PROJECT_ROOT>/`
- Session files: `<PROJECT_ROOT>/temp/`
- Source code: `<PROJECT_ROOT>/src/warden/`

---

## 🚀 QUICK START CHECKLIST

Before implementing any feature:
1. ✅ Check Panel TypeScript types
2. ✅ Read API_DESIGN.md
3. ✅ Review .session-notes for latest
4. ✅ Design Python model (Panel-compatible JSON)
5. ✅ Implement & test
6. ✅ Validate with Panel

---

**Last Updated:** 2025-12-21
**Status:** ACTIVE - Essential reference for migration
**Full Context:** See temp/warden_project_context.md (2000+ lines, optional deep dive)
