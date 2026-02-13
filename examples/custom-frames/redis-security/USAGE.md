# Redis Security Frame - Usage Guide

## 🚀 Quick Start

### 1. Install Frame

```bash
# Copy to Warden frames directory
cp -r examples/custom-frames/redis-security ~/.warden/frames/

# Verify installation
warden frame list
```

Expected output:
```
┌──────────────────┬─────────────────────────┬──────────┬──────────┬─────────┬───────────┐
│ ID               │ Name                    │ Category │ Priority │ Blocker │ Source    │
├──────────────────┼─────────────────────────┼──────────┼──────────┼─────────┼───────────┤
│ redis-security   │ Redis Security Validator│ global   │ critical │ ✓       │ community │
└──────────────────┴─────────────────────────┴──────────┴──────────┴─────────┴───────────┘
```

### 2. Enable in Project

Edit your project's `.warden/config.yaml`:

```yaml
frames:
  # Built-in frames
  - security
  - chaos
  # ... other frames ...

  # Custom frames (uncomment to enable)
  - redis-security     # ← Add this line
```

### 3. Validate Your Code

```bash
# Validate specific file
warden validate app.py

# Scan entire project
warden scan .

# Scan specific directory
warden scan src/database/
```

---

## 📋 What It Detects

### Critical Issues ⛔

#### 1. Hardcoded Passwords

**Bad**:
```python
redis_client = redis.Redis(
    host='production.redis.com',
    password='MySecretPassword123'  # ❌ CRITICAL
)
```

**Good**:
```python
import os

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST'),
    password=os.getenv('REDIS_PASSWORD')  # ✅ Environment variable
)
```

#### 2. No SSL/TLS

**Bad**:
```python
# Insecure connection
client = redis.from_url('redis://user:pass@prod.redis.com:6379')  # ❌ CRITICAL
```

**Good**:
```python
# Secure connection with SSL
client = redis.from_url('rediss://user:pass@prod.redis.com:6380')  # ✅ SSL enabled
# or
client = redis.Redis(host='...', ssl=True, ssl_cert_reqs='required')  # ✅ Explicit SSL
```

### High Issues ⚠️

#### 3. No Authentication

**Bad**:
```python
# No password
client = redis.Redis(host='localhost', port=6379)  # ❌ HIGH
```

**Good**:
```python
client = redis.Redis(
    host='localhost',
    port=6379,
    password=os.getenv('REDIS_PASSWORD')  # ✅ Password required
)
```

#### 4. Dangerous Commands

**Bad**:
```python
# Catastrophic data loss!
client.FLUSHALL()  # ❌ HIGH - Deletes ALL keys in ALL databases
client.FLUSHDB()   # ❌ HIGH - Deletes all keys in current database
```

**Good**:
```python
# Safe deletion - specific keys only
keys_to_delete = ['cache:user:123', 'session:abc']
client.delete(*keys_to_delete)  # ✅ Targeted deletion
```

### Medium Issues 📝

#### 5. Missing Timeouts

**Bad**:
```python
# Can hang forever
client = redis.Redis(host='remote-server.com')  # ❌ MEDIUM
```

**Good**:
```python
client = redis.Redis(
    host='remote-server.com',
    socket_timeout=5,           # ✅ Socket timeout
    socket_connect_timeout=5    # ✅ Connection timeout
)
```

#### 6. KEYS Command (Production)

**Bad**:
```python
# Blocks Redis in production!
all_keys = client.keys('*')  # ❌ MEDIUM - Use SCAN instead
```

**Good**:
```python
# Safe iteration
def get_all_keys(pattern='*'):
    cursor = 0
    keys = []
    while True:
        cursor, partial_keys = client.scan(cursor, match=pattern, count=100)
        keys.extend(partial_keys)
        if cursor == 0:
            break
    return keys  # ✅ Non-blocking
```

---

## ⚙️ Configuration

### Default Configuration

Frame runs with these defaults (defined in `frame.yaml`):

```yaml
config_schema:
  check_ssl:
    type: "boolean"
    default: true
    description: "Check SSL/TLS requirement"

  check_auth:
    type: "boolean"
    default: true
    description: "Check authentication requirement"

  check_dangerous_commands:
    type: "boolean"
    default: true
    description: "Check for dangerous Redis commands"

  check_hardcoded_passwords:
    type: "boolean"
    default: true
    description: "Check for hardcoded passwords"

  check_timeouts:
    type: "boolean"
    default: true
    description: "Check connection timeout configuration"
```

### Custom Configuration

Override defaults in `.warden/config.yaml`:

```yaml
frame_config:
  redis-security:
    check_ssl: true                    # Enable SSL check
    check_auth: true                   # Enable auth check
    check_dangerous_commands: false    # Disable dangerous command check
    check_hardcoded_passwords: true    # Enable hardcoded password check
    check_timeouts: true               # Enable timeout check
```

**Example**: Disable dangerous command check for development:

```yaml
# .warden/config.yaml
frame_config:
  redis-security:
    check_dangerous_commands: false  # Allow FLUSHALL in dev
```

---

## 📊 Example Output

### Failed Validation

```bash
$ warden validate app.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Frame: Redis Security Validator
Status: FAILED ⛔
Duration: 3ms
Issues: 4 (2 critical, 1 high, 1 medium)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[CRITICAL] Hardcoded Redis password detected
  Location: app.py:15
  Code: password="***REDACTED***"

  NEVER hardcode passwords in source code!
  Use environment variables instead:
    password = os.getenv('REDIS_PASSWORD')

[CRITICAL] Redis connection without SSL/TLS detected
  Location: app.py:20
  Code: redis.from_url('redis://...')

  Redis connections MUST use SSL/TLS in production.
  Solutions:
  1. Use 'rediss://' instead of 'redis://'
  2. Set ssl=True in connection parameters

[HIGH] Dangerous Redis command detected: FLUSHALL
  Location: app.py:42
  Code: client.FLUSHALL()

  Deletes ALL keys from ALL databases - catastrophic data loss
  Consider alternatives or add safeguards.

[MEDIUM] Redis connection without timeout configuration
  Location: app.py:20
  Code: redis.Redis(host='...')

  Always configure timeouts to prevent hanging connections.
  Example:
    redis.Redis(host='...', socket_timeout=5)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Validation BLOCKED - Critical issues found
```

### Passed Validation

```bash
$ warden validate secure_app.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Frame: Redis Security Validator
Status: PASSED ✅
Duration: 2ms
Issues: 0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All Redis security checks passed!
```

---

## 🧪 Testing

### Run Manual Tests

```bash
cd ~/.warden/frames/redis-security
python3 test_manual.py
```

Output:
```
🛡️  Redis Security Frame - Manual Test
================================================================================

Testing INSECURE Redis code
Status: failed
Issues Found: 12
Critical: 4, High: 3, Medium: 5

Testing SECURE Redis code
Status: passed
Issues Found: 0

✅ Frame is working correctly!
```

### Run Unit Tests

```bash
cd ~/.warden/frames/redis-security
pytest tests/ -v
```

---

## 🎯 Best Practices

### ✅ Production-Ready Redis Configuration

```python
import os
import redis

# Complete secure configuration
client = redis.Redis(
    # Connection
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', '6380')),
    db=int(os.getenv('REDIS_DB', '0')),

    # Security
    password=os.getenv('REDIS_PASSWORD'),
    ssl=True,
    ssl_cert_reqs='required',

    # Performance & Reliability
    socket_timeout=5,
    socket_connect_timeout=5,
    socket_keepalive=True,
    retry_on_timeout=True,
    health_check_interval=30
)
```

### ✅ Safe Key Iteration

```python
def scan_keys_safe(pattern='*'):
    """Safe alternative to KEYS command."""
    cursor = 0
    keys = []
    while True:
        cursor, partial_keys = client.scan(
            cursor,
            match=pattern,
            count=100
        )
        keys.extend(partial_keys)
        if cursor == 0:
            break
    return keys
```

### ✅ Environment Variables

```bash
# .env file (never commit to git!)
REDIS_HOST=production-redis.example.com
REDIS_PORT=6380
REDIS_PASSWORD=your-secure-password-here
REDIS_DB=0
```

```python
# Load from .env
from dotenv import load_dotenv
import os

load_dotenv()

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST'),
    password=os.getenv('REDIS_PASSWORD')
)
```

---

## 🔧 Troubleshooting

### Frame Not Found

```bash
warden frame list
# If redis-security not listed:

# 1. Check installation
ls -la ~/.warden/frames/redis-security

# 2. Validate frame
warden frame validate ~/.warden/frames/redis-security

# 3. Check logs
warden validate --verbose app.py
```

### Frame Not Running

Check `.warden/config.yaml`:

```yaml
frames:
  - redis-security  # ← Must be uncommented
```

### False Positives

Comments or string literals triggering checks:

```python
# This comment mentions FLUSHALL  # ← May trigger warning
```

**Solution**: Improve patterns in future versions or use suppression:

```python
# warden-suppress: redis-security-dangerous-command
client.FLUSHALL()  # Intentional for test cleanup
```

---

## 📚 Additional Resources

- [Custom Frames Guide](../../../docs/CUSTOM_FRAMES.md)
- [Frame Development Tutorial](../../../docs/FRAME_DEVELOPMENT.md)
- [Examples README](../README.md)

---

**Last Updated**: 2025-12-22
**Frame Version**: 1.0.0
**Warden Version**: 1.0.0
