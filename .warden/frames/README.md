# Custom Validation Frames

This directory contains **project-specific** custom validation frames for warden-core.

## 📁 Directory Structure

```
.warden/frames/
├── demo-security/          # Demo security validator
│   ├── frame.yaml          # Metadata + Config Schema
│   └── frame.py            # ValidationFrame implementation
│
└── env-security/           # Environment security validator
    ├── frame.yaml
    ├── frame.py
    └── README.md
```

## 🔍 How It Works

### 1. Auto-Discovery
Warden automatically discovers frames from **two locations**:

**Global (all projects):**
```
~/.warden/frames/
```

**Project-specific (this project only):**
```
/Users/alper/Documents/Development/Personal/warden-core/.warden/frames/
```

### 2. Config Auto-Generation
Each frame has a `frame.yaml` with a `config_schema` section:

```yaml
config_schema:
  enabled:
    type: "boolean"
    default: true
  my_setting:
    type: "string"
    default: "value"
```

Warden automatically generates default config from this schema!

### 3. Config Override
Override in `.warden/config.yaml`:

```yaml
frames:
  - security
  - demo-security      # Enable this frame

frames_config:
  demo-security:
    enabled: true
    # Only override what you need
    my_setting: "custom_value"
```

## 📋 Available Frames

### demo-security
**Purpose:** Demo frame showing config auto-generation
**Checks:**
- Hardcoded passwords
- SQL injection patterns

**Config (auto-generated):**
- `check_hardcoded_passwords` (default: true)
- `check_sql_injection` (default: true)
- `password_patterns` (default: ["password", "passwd", "pwd"])
- `severity_level` (default: "high")

### env-security
**Purpose:** Production-ready environment variable security
**Checks:**
- Hardcoded credentials (API keys, tokens, secrets)
- Missing environment variable validation
- Insecure default values

**Config (auto-generated - 8 fields!):**
- `check_hardcoded_credentials` (default: true)
- `check_missing_env_validation` (default: true)
- `check_insecure_defaults` (default: true)
- `sensitive_patterns` (default: ["API_KEY", "SECRET", ...])
- `allowed_default_values` (default: ["localhost", ...])
- `severity_level` (default: "critical")
- And more...

## 🚀 Usage

### Enable in Config
Edit `.warden/config.yaml`:

```yaml
frames:
  - security
  - chaos
  - demo-security      # Add this
  - env-security       # Add this
```

### Test Frame Discovery
```bash
python3 << 'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))

from warden.validation.infrastructure.frame_registry import FrameRegistry

registry = FrameRegistry()
frames = registry.discover_all()

print(f"Total: {len(frames)}")
for fid in ["demosecurity", "envsecurity"]:
    if fid in registry.registered_frames:
        print(f"✅ {fid}")
EOF
```

### Run Validation
```bash
warden scan .
```

## 📝 Creating New Frames

### 1. Create Directory
```bash
mkdir -p .warden/frames/my-frame
```

### 2. Create frame.yaml
```yaml
name: "My Frame"
id: "my-frame"
version: "1.0.0"
author: "Your Name"
description: "What it does"

category: "global"
priority: "medium"
scope: "file_level"
is_blocker: false

config_schema:
  enabled:
    type: "boolean"
    default: true

tags:
  - "custom"
```

### 3. Create frame.py
```python
from warden.validation.domain.frame import ValidationFrame, FrameResult, CodeFile
from warden.validation.domain.enums import FrameCategory, FramePriority, FrameScope

class MyFrame(ValidationFrame):
    name = "My Frame"
    description = "What it does"
    category = FrameCategory.GLOBAL
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False
    version = "1.0.0"

    async def execute(self, code_file: CodeFile) -> FrameResult:
        # Your validation logic here
        return FrameResult(...)
```

### 4. Add to config.yaml
```yaml
frames:
  - my-frame

frames_config:
  my-frame:
    enabled: true
```

### 5. Done!
Warden will auto-discover and run it!

## ✅ Benefits

- ✅ **Auto-Discovery:** No manual registration
- ✅ **Auto-Config:** Config generated from frame.yaml
- ✅ **Project-Specific:** Only applies to this project
- ✅ **Version Controlled:** Part of your repo
- ✅ **Customizable:** Override any config setting

## 📚 Documentation

See individual frame README files for detailed documentation:
- `env-security/README.md` - Full production example

---

**Last Updated:** 2025-12-26
**Warden Version:** 1.0.0+
