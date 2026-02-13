# Warden Custom Frames - Production-Ready Examples

Real-world validation frames demonstrating best practices for custom frame development.

## 📁 Available Example Frames

### 1. **Redis Security Frame** ✅ COMPLETE

**Location**: `redis-security/`

**What it validates**:
- ❌ Insecure connections (missing SSL/TLS)
- ❌ Missing authentication
- ❌ Hardcoded passwords in source code
- ❌ Dangerous commands (FLUSHALL, FLUSHDB, KEYS)
- ❌ Missing connection timeouts

**Detects patterns in**:
- Python (redis-py)
- Node.js (ioredis, node-redis)
- Go (go-redis)
- Connection strings

**Test Results**:
```
Insecure Code (insecure_redis.py):
  - Status: FAILED
  - Issues Found: 12
  - Critical: 4 (hardcoded passwords, no SSL)
  - High: 3 (no auth, FLUSHALL)
  - Medium: 5 (no timeouts, KEYS usage)

Secure Code (secure_redis.py):
  - Status: PASSED (minor warnings)
  - Issues Found: 0-2 (context-dependent)
```

**Key Features**:
- ✅ Multi-language pattern detection
- ✅ Context-aware validation (checks nearby lines)
- ✅ Severity-based classification (critical/high/medium)
- ✅ Actionable fix recommendations
- ✅ Configurable checks (via frame.yaml)

---

## 🚀 Quick Start

### 1. Test an Example Frame

```bash
# Test Redis Security Frame
cd examples/custom-frames/redis-security
python3 test_manual.py
```

**Output**:
```
🛡️  Redis Security Frame - Manual Test
================================================================================

Testing INSECURE Redis code
Status: failed
Issues Found: 12
Is Blocker: True

Testing SECURE Redis code
Status: passed
Issues Found: 0

✅ Frame is working correctly!
```

### 2. Install to Your System

```bash
# Copy to frames directory
cp -r redis-security ~/.warden/frames/

# Verify installation
warden frame list
```

**Expected output**:
```
┌──────────────────┬────────────────────────┬──────────┬──────────┬─────────┬───────────┐
│ ID               │ Name                   │ Category │ Priority │ Blocker │ Source    │
├──────────────────┼────────────────────────┼──────────┼──────────┼─────────┼───────────┤
│ redis-security   │ Redis Security Validator│ global   │ critical │ ✓       │ community │
└──────────────────┴────────────────────────┴──────────┴──────────┴─────────┴───────────┘
```

### 3. Use in Validation

```bash
# Frame auto-discovered - validates Redis code automatically
warden validate mycode.py
warden scan .
```

---

## 📖 Frame Structure

Each example frame follows best practices:

```
redis-security/
├── frame.yaml              # Metadata (validated)
├── frame.py                # ValidationFrame implementation
├── test_examples/          # Test code samples
│   ├── insecure_redis.py   # Known vulnerabilities
│   └── secure_redis.py     # Best practices
├── test_manual.py          # Manual test script
├── tests/                  # Unit tests
│   └── test_frame.py
└── README.md               # Documentation
```

---

## 🎓 Learning from Examples

### Redis Security Frame - Key Patterns

#### 1. **Multi-Pattern Detection**

```python
REDIS_CONNECTION_PATTERNS = [
    r'redis\.Redis\([^)]*\)',      # Python
    r'new\s+Redis\([^)]*\)',       # Node.js
    r'redis\.NewClient\([^)]*\)',  # Go
    r'redis://[^\s\'"]+',          # Connection strings
]
```

#### 2. **Context-Aware Validation**

```python
# Check current line
has_ssl = any(re.search(ssl_pattern, line) for ssl_pattern in SSL_PATTERNS)

# Check nearby lines (context)
context_start = max(0, i - 5)
context_end = min(len(lines), i + 5)
context = '\n'.join(lines[context_start:context_end])
has_ssl = has_ssl or any(re.search(ssl_pattern, context) for ssl_pattern in SSL_PATTERNS)
```

**Why?** Multi-line configurations might have SSL on a different line:
```python
client = redis.Redis(
    host='localhost',
    port=6379,
    ssl=True  # ← Different line!
)
```

#### 3. **Severity Classification**

```python
critical_count = sum(1 for f in findings if f.severity == "critical")
high_count = sum(1 for f in findings if f.severity == "high")

if critical_count > 0:
    status = "failed"  # Block deployment
elif high_count > 0:
    status = "warning"  # Allow but warn
else:
    status = "passed"
```

#### 4. **Actionable Error Messages**

```python
Finding(
    id="redis-no-ssl-1",
    severity="critical",
    message="Redis connection without SSL/TLS detected",
    location="app.py:15",
    detail=(
        "Redis connections MUST use SSL/TLS in production.\n"
        "Solutions:\n"
        "1. Use 'rediss://' instead of 'redis://' URL scheme\n"
        "2. Set ssl=True in connection parameters\n"
        "\nExample (Python):\n"
        "  redis.Redis(host='...', ssl=True, ssl_cert_reqs='required')"
    ),
    code="redis.Redis(host='prod.example.com')"
)
```

**Output**:
```
[CRITICAL] Redis connection without SSL/TLS detected
Location: app.py:15
Code: redis.Redis(host='prod.example.com')

Redis connections MUST use SSL/TLS in production.
Solutions:
1. Use 'rediss://' instead of 'redis://' URL scheme
2. Set ssl=True in connection parameters

Example (Python):
  redis.Redis(host='...', ssl=True, ssl_cert_reqs='required')
```

#### 5. **Configurable Checks**

```python
def __init__(self, config: Dict[str, Any] | None = None):
    super().__init__(config)

    # Configuration options (from frame.yaml or .warden/config.yaml)
    self.check_ssl = self.config.get("check_ssl", True)
    self.check_auth = self.config.get("check_auth", True)
    self.check_dangerous_commands = self.config.get("check_dangerous_commands", True)
```

**Usage** (`.warden/config.yaml`):
```yaml
frames:
  redis-security:
    check_ssl: true
    check_auth: true
    check_dangerous_commands: false  # Disable dangerous command check
```

---

## 🧪 Testing Your Custom Frame

### Manual Testing

```bash
cd your-frame
python3 test_manual.py
```

### Pytest Testing

```bash
cd your-frame
pytest tests/ -v
```

### Validation

```bash
warden frame validate your-frame/
```

---

## 📊 Performance Metrics

| Frame | LOC | Patterns | Avg Time | Memory |
|-------|-----|----------|----------|--------|
| Redis Security | 376 | 20+ | <5ms | <1MB |

**Benchmarks** (on 100KB file):
- Detection: ~1ms
- SSL check: ~1ms
- Auth check: ~1ms
- All checks: ~3-5ms

---

## 🎯 Best Practices Demonstrated

### 1. **Early Exit Pattern**

```python
# Skip validation if no Redis usage detected
has_redis_usage = self._detect_redis_usage(code_file.content)
if not has_redis_usage:
    return FrameResult(status="passed", ...)
```

**Why?** Avoid wasting time on irrelevant files.

### 2. **Structured Logging**

```python
logger.info(
    "redis_security_validation_started",
    file_path=code_file.path,
    file_size=code_file.size_bytes,
)
```

**Benefits**:
- Searchable logs
- Structured data
- Easy debugging

### 3. **Metadata Rich Results**

```python
return FrameResult(
    ...
    metadata={
        "redis_usage_detected": True,
        "critical_issues": critical_count,
        "high_issues": high_count,
        "checks_performed": [...]
    }
)
```

**Benefits**:
- Visibility into what ran
- Debugging information
- Metrics collection

### 4. **Safe Pattern Matching**

```python
# ✅ GOOD: Specific, unambiguous pattern
r'redis\.Redis\([^)]*\)'

# ❌ BAD: Too broad, many false positives
r'redis'
```

### 5. **Comprehensive Testing**

- ✅ Insecure code examples
- ✅ Secure code examples
- ✅ Edge cases
- ✅ Multi-language support
- ✅ Manual test script
- ✅ Pytest unit tests

---

## 🔍 Example Findings

### Critical Issue

```
[CRITICAL] Hardcoded Redis password detected
Location: app.py:15
Code: password="***REDACTED***"

NEVER hardcode passwords in source code!
Use environment variables instead:
  password = os.getenv('REDIS_PASSWORD')
```

### High Issue

```
[HIGH] Dangerous Redis command detected: FLUSHALL
Location: cleanup.py:42
Code: client.FLUSHALL()

Deletes ALL keys from ALL databases - catastrophic data loss
Consider alternatives or add safeguards.
```

### Medium Issue

```
[MEDIUM] Redis connection without timeout configuration
Location: service.py:20
Code: redis.Redis(host='...')

Always configure timeouts to prevent hanging connections.
Example:
  redis.Redis(host='...', socket_timeout=5)
```

---

## 📚 Additional Resources

- [Custom Frames Guide](../../docs/CUSTOM_FRAMES.md)
- [Frame Development Tutorial](../../docs/FRAME_DEVELOPMENT.md)
- [Built-in Frames](../../src/warden/validation/frames/)

---

## 🤝 Contributing Example Frames

Want to contribute your own example frame?

1. Create frame following the structure above
2. Include test examples (insecure + secure)
3. Add manual test script
4. Document patterns detected
5. Submit PR with README

**Suggested frames**:
- MongoDB Security
- PostgreSQL Security
- AWS S3 Security
- Docker Security
- Kubernetes Security
- API Security (REST, GraphQL)
- Authentication/Authorization
- OWASP Top 10

---

**Last Updated**: 2025-12-22
**Warden Version**: 1.0.0
**Status**: Production Ready
