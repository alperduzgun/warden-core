# Project Auto-Configuration Implementation

## Overview

Implemented automatic project configuration system that creates `.warden/project.toml` on first run with auto-detected language, SDK version, and framework. Subsequent runs use cached values for improved performance.

## Implementation Date

2025-12-21

## Features Implemented

### 1. Auto-Detection System

**File:** `src/warden/config/project_detector.py` (542 lines)

Detects:
- **Project Name**: From package.json, pyproject.toml, Cargo.toml, or directory name
- **Primary Language**: By counting source files (`.py`, `.js`, `.java`, etc.)
- **SDK Version**: From version files:
  - Python: pyproject.toml, .python-version
  - Java: pom.xml, build.gradle
  - Node.js: package.json, .nvmrc
  - .NET: .csproj, global.json
  - Go: go.mod
  - Rust: rust-toolchain, Cargo.toml
  - Ruby: .ruby-version, Gemfile
- **Framework**: Using existing FrameworkDetector (Django, Flask, FastAPI, React, Spring Boot, etc.)
- **Project Type**: application, library, microservice, or monorepo

**Supported Languages:**
- Python
- JavaScript/TypeScript
- Java
- C#
- Go
- Rust
- C/C++
- Ruby
- PHP
- Swift
- Kotlin

### 2. Configuration Model

**File:** `src/warden/config/project_config.py` (130 lines)

**ProjectConfig Dataclass:**
```python
@dataclass
class ProjectConfig:
    name: str
    language: str
    sdk_version: str | None
    framework: str | None
    project_type: str = "application"
    detected_at: datetime
    custom_settings: dict[str, Any]
```

**Features:**
- TOML serialization (manual, no dependencies)
- TOML deserialization (using tomllib/tomli)
- Validation (checks language support, project type)
- File I/O operations

**Example .warden/project.toml:**
```toml
[project]
name = "warden-core"
language = "python"
sdk_version = "3.11"
framework = "fastapi"
project_type = "monorepo"
detected_at = "2025-12-21T19:27:55.605826"
```

### 3. Configuration Manager

**File:** `src/warden/config/project_manager.py` (180 lines)

**ProjectConfigManager Class:**
```python
class ProjectConfigManager:
    async def load_or_create() -> ProjectConfig
    async def load() -> ProjectConfig
    async def create_and_save() -> ProjectConfig
    async def save(config: ProjectConfig)
    async def update(**kwargs) -> ProjectConfig
    async def delete()
    async def reset() -> ProjectConfig
```

**Key Features:**
- Automatically creates `.warden/` directory
- Detects if config exists
- On first run: auto-detects and saves config
- On subsequent runs: loads cached config
- Provides CRUD operations for config

### 4. CLI Commands

#### a. warden init

**File:** `src/warden/cli/commands/init.py` (230 lines)

**Features:**
- Interactive mode: prompts user for each setting
- Auto mode: auto-detects everything (`--auto`)
- Force mode: overwrite existing config (`--force`)
- Displays detected values as defaults
- Validates before saving
- Shows next steps after creation

**Usage:**
```bash
warden init                    # Interactive setup
warden init --auto             # Auto-detect all
warden init ./my-project       # Init specific directory
warden init --force            # Overwrite existing
```

#### b. warden validate (updated)

**File:** `src/warden/cli/commands/validate.py`

**Changes:**
- Imports ProjectConfigManager
- Finds project root by looking for markers (.git, pyproject.toml, etc.)
- Loads or creates project config
- Uses detected language and framework
- Displays project info in header

**Enhanced Output:**
```
╭── Validation Session ──╮
│ Warden Code Validation │
│ Project: warden-core   │  ← NEW
│ File: test.py          │
│ Language: python       │
│ Framework: fastapi     │  ← NEW
│ SDK: 3.11              │  ← NEW
│ Size: 188 bytes        │
╰────────────────────────╯
```

#### c. warden scan (updated)

**File:** `src/warden/cli/commands/scan.py`

**Changes:**
- Imports ProjectConfigManager
- Loads or creates project config for scan directory
- Displays comprehensive project info in header

**Enhanced Output:**
```
╭─────── Scan Session ───────╮
│ Warden Project Scan        │
│ Project: warden-core       │  ← NEW
│ Directory: /path/to/dir    │
│ Language: python           │  ← NEW
│ Framework: fastapi         │  ← NEW
│ SDK: 3.11                  │  ← NEW
│ Type: monorepo             │  ← NEW
│ Extensions: .py            │
│ Started: 2025-12-21 19:27  │
╰────────────────────────────╯
```

### 5. CLI Registration

**File:** `src/warden/cli/main.py`

**Changes:**
- Added `init` command import
- Registered init command in main app
- Updated usage documentation

**New Command Structure:**
```
warden init                 # NEW: Initialize project
warden validate <file>      # ENHANCED: Uses project config
warden scan <directory>     # ENHANCED: Uses project config
warden report
warden providers
```

## Technical Decisions

### 1. TOML Format

**Why TOML?**
- Human-readable configuration format
- Standard in Python ecosystem (pyproject.toml)
- Native support in Python 3.11+ (`tomllib`)
- Simple to parse and write

**Implementation:**
- Reading: `tomllib` (built-in Python 3.11+)
- Writing: Manual string formatting (no dependencies)

### 2. Auto-Detection Strategy

**Language Detection:**
- Count source files by extension
- Filter out common ignore directories (node_modules, venv, etc.)
- Return most common language

**SDK Detection:**
- Check version files in priority order
- Extract version using regex
- Return None if not found

**Framework Detection:**
- Reuse existing FrameworkDetector
- Check dependencies and imports
- Special handling for Spring Boot vs Spring

**Project Type:**
- Monorepo: Has lerna.json, nx.json, or multiple package.json
- Library: Has classifiers or package entry points
- Microservice: Has Dockerfile or K8s manifests
- Default: application

### 3. Caching Strategy

**First Run:**
1. Check if `.warden/project.toml` exists
2. If not, auto-detect all metadata
3. Create `.warden/` directory
4. Save config to `.warden/project.toml`
5. Log detection results

**Subsequent Runs:**
1. Check if `.warden/project.toml` exists
2. If yes, load from file
3. Use cached values
4. Log config loaded

**Benefits:**
- Fast startup (no re-detection)
- Consistent behavior
- User can manually edit config
- Can force re-detection with `warden init --force`

## Testing Results

### Test 1: warden init --auto

**Command:**
```bash
python -m warden.cli.main init run --auto
```

**Result:**
```
✓ Project configuration created!
            Project Configuration
╭──────────────────────┬─────────────────────╮
│ Name                 │ warden-core         │
│ Language             │ python              │
│ SDK Version          │ 3.11                │
│ Framework            │ fastapi             │
│ Project Type         │ monorepo            │
│ Detected At          │ 2025-12-21 19:27:55 │
╰──────────────────────┴─────────────────────╯

Saved to: /Users/ibrahimcaglar/warden-core/.warden/project.toml
```

**Detection Accuracy:**
- ✅ Name: Correct (from pyproject.toml)
- ✅ Language: Correct (Python files detected)
- ✅ SDK: Correct (from pyproject.toml `python = "^3.11"`)
- ✅ Framework: Correct (FastAPI in dependencies)
- ✅ Type: Correct (monorepo - has apps/ and packages/)

### Test 2: Second Run (Cache Test)

**Command:**
```bash
python -m warden.cli.main init run --auto
```

**Result:**
```
Warning: .warden/project.toml already exists!
Location: /Users/ibrahimcaglar/warden-core/.warden/project.toml
[Shows existing config table]
Do you want to overwrite it? [y/n] (n):
```

**Behavior:**
- ✅ Detected existing config
- ✅ Loaded and displayed cached values
- ✅ Asked for confirmation before overwrite
- ✅ Default is to keep existing config

### Test 3: validate Command with Cache

**Command:**
```bash
python -m warden.cli.main validate run test_sample.py
```

**Result:**
```
2025-12-21 19:28:16 [info] project_config_found config_path=.../.warden/project.toml
2025-12-21 19:28:16 [info] project_config_loaded framework=fastapi language=python ...

╭── Validation Session ──╮
│ Warden Code Validation │
│ Project: warden-core   │
│ File: test_sample.py   │
│ Language: python       │
│ Framework: fastapi     │
│ SDK: 3.11              │
│ Size: 188 bytes        │
╰────────────────────────╯
```

**Behavior:**
- ✅ Found existing config
- ✅ Loaded cached values
- ✅ Used project name in header
- ✅ Used framework from config
- ✅ Used SDK version from config

## File Structure

```
src/warden/config/
├── __init__.py
├── project_config.py      # NEW: Config model + TOML serialization
├── project_detector.py    # NEW: Auto-detection service
└── project_manager.py     # NEW: Config lifecycle manager

src/warden/cli/commands/
├── init.py                # NEW: warden init command
├── validate.py            # UPDATED: Uses ProjectConfig
└── scan.py                # UPDATED: Uses ProjectConfig

src/warden/cli/
└── main.py                # UPDATED: Registers init command

.warden/
└── project.toml           # NEW: Auto-generated config
```

## Usage Guide

### For End Users

**Initial Setup:**
```bash
cd my-project
warden init --auto
```

**Manual/Interactive Setup:**
```bash
warden init
# Answer prompts with detected defaults
```

**Validation (uses cached config):**
```bash
warden validate myfile.py
```

**Scanning (uses cached config):**
```bash
warden scan
```

**Reset Configuration:**
```bash
warden init --force --auto
```

### For Developers

**Load Config in Code:**
```python
from pathlib import Path
from warden.config.project_manager import ProjectConfigManager

manager = ProjectConfigManager(Path.cwd())
config = await manager.load_or_create()

print(f"Language: {config.language}")
print(f"Framework: {config.framework}")
```

**Manual Detection:**
```python
from pathlib import Path
from warden.config.project_detector import ProjectDetector

detector = ProjectDetector(Path.cwd())
language = await detector.detect_language()
sdk = await detector.detect_sdk_version(language)
framework = await detector.detect_framework()
```

## Benefits

1. **Zero-Config First Run**: Auto-detects everything
2. **Fast Subsequent Runs**: Uses cached values
3. **User Editable**: Can manually edit `.warden/project.toml`
4. **Consistent**: Same config across validate/scan commands
5. **Extensible**: Easy to add new detection logic
6. **No Dependencies**: Uses built-in tomllib, manual TOML writing
7. **Cross-Language**: Supports 12+ languages
8. **Project-Aware**: Commands now know project context

## Future Enhancements

Possible improvements:
1. Add `warden config show` to display current config
2. Add `warden config edit` to modify config interactively
3. Support `.warden/project.toml` templates
4. Auto-update SDK version on change
5. Detect multiple languages in polyglot projects
6. Integration with CI/CD environment detection
7. Cloud platform detection (AWS, GCP, Azure)
8. Dependency version detection beyond SDK

## Migration Guide

**For Existing Users:**

No breaking changes! The system automatically:
1. Creates config on first run
2. Uses sensible defaults
3. Works with existing workflows

**Manual Migration:**
```bash
# Just run init in your project
cd your-project
warden init --auto

# Or keep using warden without init
# (it will auto-create config on validate/scan)
```

## Summary

Successfully implemented a complete project auto-configuration system that:
- ✅ Auto-detects language, SDK, framework, and project type
- ✅ Creates `.warden/project.toml` on first run
- ✅ Caches config for fast subsequent runs
- ✅ Provides `warden init` command for manual setup
- ✅ Integrates with validate and scan commands
- ✅ Supports 12+ programming languages
- ✅ Uses zero external dependencies (tomllib built-in)
- ✅ Tested and working on warden-core project

**User Experience:**
```bash
# First time in project
$ warden scan
[Auto-detects: Python 3.11, FastAPI, monorepo]
[Creates .warden/project.toml]
[Runs scan with detected config]

# Second time
$ warden scan
[Loads .warden/project.toml - instant!]
[Runs scan with cached config]
```

**Result:** Users get intelligent, context-aware validation without manual configuration! 🎉
