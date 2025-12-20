# Warden Validation Frame System - Architecture

> **Modular Frame System + Pluggable Discovery = Extensible Validation**

**Last Updated:** 2025-12-20

---

## 🎯 System Overview

Warden kullanır bir **Pluggable Validation Frame System**:
- **Modular**: Her validation strategy ayrı bir frame (modül)
- **Pluggable**: Community custom frame'ler ekleyebilir
- **Extensible**: Yeni frame'ler Warden Core'u değiştirmeden eklenir

---

## 🏗️ Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  USER LAYER                                                  │
│  - Developer writes code                                     │
│  - Warden scans code                                         │
│  - Receives validation results                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  ORCHESTRATION LAYER                                         │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │  FrameExecutor                                     │     │
│  │  - Discovers available frames                      │     │
│  │  - Selects applicable frames                       │     │
│  │  - Executes frames in parallel                     │     │
│  │  - Aggregates results                              │     │
│  │  - Handles timeouts & errors                       │     │
│  └────────────────────────────────────────────────────┘     │
│                                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  FRAME ABSTRACTION LAYER (Core Architecture)                │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │  ValidationFrame (ABC)                       │            │
│  │  ┌──────────────────────────────────────┐   │            │
│  │  │  Metadata                            │   │            │
│  │  │  - name: str                         │   │            │
│  │  │  - category: FrameCategory           │   │            │
│  │  │  - priority: FramePriority           │   │            │
│  │  │  - is_blocker: bool                  │   │            │
│  │  │  - applicability: List[Language]     │   │            │
│  │  └──────────────────────────────────────┘   │            │
│  │                                              │            │
│  │  ┌──────────────────────────────────────┐   │            │
│  │  │  Methods                             │   │            │
│  │  │  - execute(code_file) → FrameResult  │   │            │
│  │  │  - is_applicable(lang) → bool        │   │            │
│  │  └──────────────────────────────────────┘   │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
│  ┌─────────────────────────────────────────────┐            │
│  │  Models                                      │            │
│  │  - FrameResult (status, findings, duration)  │            │
│  │  - Finding (severity, message, location)     │            │
│  │  - CodeFile (path, content, language)        │            │
│  └─────────────────────────────────────────────┘            │
│                                                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  FRAME IMPLEMENTATION LAYER                                  │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Built-in     │  │ Official     │  │ Community    │      │
│  │ Frames       │  │ Extensions   │  │ Frames       │      │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤      │
│  │ Security     │  │ Dockerfile   │  │ MyCompany    │      │
│  │ Chaos        │  │ Kubernetes   │  │ CustomAI     │      │
│  │ Fuzz         │  │ Terraform    │  │ TeamStandard │      │
│  │ Property     │  │ CloudConfig  │  │ ...          │      │
│  │ Stress       │  │ ...          │  │              │      │
│  │ Architectural│  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│       ▲                  ▲                  ▲               │
│       │                  │                  │               │
│  Shipped with       Published by        Created by         │
│  Warden Core        Warden Team         Community          │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  PLUGIN DISCOVERY LAYER (Distribution Mechanism)            │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │  PluginLoader                                      │     │
│  │                                                     │     │
│  │  Discovery Sources:                                │     │
│  │  1. Built-in frames (warden.validation.frames.*)   │     │
│  │  2. Entry points (PyPI: "warden.frames")           │     │
│  │  3. Local directory (~/.warden/plugins/)           │     │
│  │  4. Environment (WARDEN_PLUGIN_PATHS)              │     │
│  │                                                     │     │
│  │  Validation:                                       │     │
│  │  - Check inheritance (extends ValidationFrame)     │     │
│  │  - Check required attributes (name, execute, ...)  │     │
│  │  - Check version compatibility                     │     │
│  │  - Deduplicate (by frame_id)                       │     │
│  └────────────────────────────────────────────────────┘     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔄 Execution Flow

### 1. Initialization (Startup)

```
Warden Starts
    ↓
PluginLoader.discover_all()
    ↓
    ├─ Scan built-in frames
    ├─ Scan PyPI entry points
    ├─ Scan ~/.warden/plugins/
    └─ Scan WARDEN_PLUGIN_PATHS
    ↓
Validate frames (inheritance, attributes, version)
    ↓
Deduplicate (by frame_id)
    ↓
Register frames in FrameExecutor
    ↓
System Ready ✅
```

### 2. Validation Execution (Per File)

```
User: warden scan my_file.py
    ↓
FrameExecutor receives CodeFile
    ↓
Filter applicable frames (language, framework)
    ├─ SecurityFrame.is_applicable("python") → True
    ├─ ChaosFrame.is_applicable("python") → True
    ├─ DockerfileFrame.is_applicable("python") → False (skip)
    └─ MyCompanyFrame.is_applicable("python") → True
    ↓
Sort frames by priority (critical → high → medium → low)
    ├─ SecurityFrame (priority: critical)
    ├─ MyCompanyFrame (priority: high)
    └─ ChaosFrame (priority: medium)
    ↓
Execute frames in parallel (with timeout)
    ├─ SecurityFrame.execute(code_file)
    ├─ MyCompanyFrame.execute(code_file)
    └─ ChaosFrame.execute(code_file)
    ↓
Collect results (FrameResult from each)
    ├─ SecurityFrame: status=failed, findings=[SQL injection]
    ├─ MyCompanyFrame: status=warning, findings=[Forbidden import]
    └─ ChaosFrame: status=passed, findings=[]
    ↓
Check blockers (is_blocker=True && status=failed)
    ├─ SecurityFrame is blocker → BLOCK PR ❌
    ↓
Aggregate & return results
    ↓
Display to user
```

### 3. Community Frame Addition (New Frame)

```
Developer creates custom frame
    ↓
Extends ValidationFrame
    class MyFrame(ValidationFrame):
        name = "My Custom Check"
        async def execute(self, code_file):
            # Custom logic
    ↓
Packages as Python package
    pyproject.toml:
      [tool.poetry.plugins."warden.frames"]
      myframe = "my_package.frame:MyFrame"
    ↓
Publishes to PyPI
    poetry publish
    ↓
User installs
    pip install warden-frame-myframe
    ↓
Warden auto-discovers (entry point)
    PluginLoader finds it on next scan
    ↓
Frame runs alongside built-ins! ✅
```

---

## 🧩 Key Concepts

### 1. Modularity (Frame System)

Each frame is a **self-contained module**:
- **Independent**: Doesn't depend on other frames
- **Single Responsibility**: One validation concern per frame
- **Composable**: Mix & match frames as needed
- **Reusable**: Same frame works across projects

**Example:**
```python
# SecurityFrame only cares about security
class SecurityFrame(ValidationFrame):
    async def execute(self, code_file):
        # Check SQL injection
        # Check XSS
        # Check secrets
        # Doesn't care about performance, architecture, etc.
```

### 2. Pluggability (Discovery System)

Frames can come from **anywhere**:
- **Built-in**: Shipped with Warden Core
- **PyPI**: `pip install warden-frame-X`
- **Local**: `~/.warden/plugins/myframe/`
- **Git**: `pip install git+https://...`

**Example:**
```bash
# User installs community frame
pip install warden-frame-company-standards

# Warden discovers it automatically (no config needed!)
warden scan ./src
# → Runs: Security, Chaos, Fuzz, Property, Stress, CompanyStandards
```

### 3. Extensibility (Open/Closed Principle)

Warden is:
- **Open for extension**: Community can add frames
- **Closed for modification**: Core code doesn't change

**Example:**
```python
# Add new frame WITHOUT touching Warden Core
class AICodeReviewFrame(ValidationFrame):
    name = "AI Code Review"

    async def execute(self, code_file):
        # Call GPT-4 for review
        # Return findings
```

---

## 📊 Frame Types

### Built-in Frames (Core)

| Frame | Purpose | Priority | Blocker |
|-------|---------|----------|---------|
| SecurityFrame | SQL injection, XSS, secrets | Critical | ✅ Yes |
| ChaosFrame | Network failures, timeouts | High | ❌ No |
| FuzzFrame | Edge cases, malformed input | High | ❌ No |
| PropertyFrame | Idempotency, invariants | Medium | ❌ No |
| StressFrame | Load testing, memory leaks | Low | ❌ No |
| ArchitecturalFrame | SOLID, design patterns | Low | ❌ No |

### Official Extensions (Warden Team)

| Frame | Purpose | Install |
|-------|---------|---------|
| DockerfileFrame | Dockerfile best practices | `pip install warden-frame-dockerfile` |
| KubernetesFrame | K8s manifest validation | `pip install warden-frame-kubernetes` |
| TerraformFrame | IaC security & best practices | `pip install warden-frame-terraform` |

### Community Frames (User-created)

| Frame | Purpose | Install |
|-------|---------|---------|
| MyCompanyFrame | Company coding standards | `pip install warden-frame-mycompany` |
| AIReviewFrame | GPT-4 code review | `pip install warden-frame-ai-review` |
| PerformanceFrame | Performance bottleneck detection | `pip install warden-frame-performance` |

---

## 🎯 Benefits

### For Users

1. **Comprehensive Validation**: Run multiple checks in parallel
2. **Customizable**: Enable/disable frames per project
3. **Extensible**: Add custom checks without forking Warden
4. **Fast**: Parallel execution with timeout protection

### For Community

1. **Easy to Create**: Extend `ValidationFrame`, implement `execute()`
2. **Easy to Share**: Publish to PyPI, auto-discovered
3. **Reusable**: Write once, use in all projects
4. **Collaborative**: Share best practices via frames

### For Warden Core

1. **Clean Architecture**: Frame abstraction decouples validation logic
2. **Maintainable**: Add frames without modifying core
3. **Testable**: Each frame is independently testable
4. **Scalable**: Unlimited frames without core bloat

---

## 🔐 Safety & Security

### Plugin Validation

Before execution, each frame is validated:
```python
✅ Extends ValidationFrame (inheritance check)
✅ Has required attributes (name, execute, ...)
✅ Compatible version (min/max Warden version)
✅ No malicious imports (optional scan)
```

### Execution Sandboxing

Each frame runs with:
```python
✅ Timeout (default 30s, configurable)
✅ Error isolation (frame crash doesn't crash Warden)
✅ Resource limits (future: memory, CPU)
✅ Read-only by default (no file writes unless approved)
```

---

## 📝 Summary

**Q: What is the Frame System?**
A: Modular validation architecture where each validation strategy is an independent frame.

**Q: What is the Plugin System?**
A: Discovery mechanism that allows community to add custom frames.

**Q: Are they the same?**
A: No, they're **complementary layers** of the same system:
   - Frame System = Core architecture (abstraction)
   - Plugin System = Distribution mechanism (loading)
   - Together = **Pluggable Frame System**

**Q: Why this design?**
A:
- **Modularity**: Each frame is independent
- **Extensibility**: Community can add frames
- **Maintainability**: Core code stays clean
- **Flexibility**: Mix & match frames per project

---

**Status:** Architecture validated - Ready for implementation
**Next:** Implement built-in frames (Security, Chaos, Fuzz, Property, Stress, Architectural)
