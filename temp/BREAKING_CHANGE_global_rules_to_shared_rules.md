# BREAKING CHANGE: `global_rules` → `shared_rules`

> **Status:** Proposed for MVP v1.0.0
> **Date:** 2025-12-23
> **Severity:** BREAKING CHANGE
> **Reason:** Prevent user confusion and improve API clarity
> **Timeline:** Before MVP release (pre-production)

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Real-World User Confusion](#real-world-user-confusion)
4. [Current Implementation Analysis](#current-implementation-analysis)
5. [Why This Needs to Change](#why-this-needs-to-change)
6. [Proposed Solution](#proposed-solution)
7. [Breaking Changes](#breaking-changes)
8. [Migration Guide](#migration-guide)
9. [Implementation Plan](#implementation-plan)
10. [Backward Compatibility Strategy](#backward-compatibility-strategy)
11. [Timeline](#timeline)

---

## 🎯 Executive Summary

**Current Problem:**
- The `global_rules` naming suggests "runs automatically on all frames"
- Users expect global rules to execute globally without manual attachment
- Actual behavior: `global_rules` is just a "shareability marker" for rules that can be used by multiple consumers (frames, services, LLM)

**Proposed Solution:**
- Rename `global_rules` → `shared_rules`
- Add clear documentation and inline comments
- Provide migration guide and deprecation warnings

**Impact:**
- **BREAKING CHANGE** for existing users
- **Critical for MVP**: Better to fix now than after public release
- **User Experience**: Eliminates confusion before widespread adoption

---

## ❌ Problem Statement

### Misleading Terminology

The term `global_rules` is **semantically incorrect** and causes user confusion:

**What Users Think:**
```yaml
global_rules:
  - no-secrets  # "This will run on ALL frames automatically"
```

**What Actually Happens:**
```yaml
global_rules:
  - no-secrets  # "This CAN BE attached to multiple frames (but you must attach it manually)"

frame_rules:
  security:
    pre_rules:
      - no-secrets  # ← Manual attachment required!
```

### The Core Issue

"Global" in software typically means:
- ✅ "Applies everywhere automatically"
- ✅ "Runs without explicit invocation"
- ✅ "Has universal scope"

But `global_rules` in Warden means:
- ❌ "Can be shared across multiple consumers" (not automatic execution)
- ❌ "Must be manually attached to frames/services/LLM" (requires explicit invocation)
- ❌ "Is a shareability permission flag" (not a scope indicator)

---

## 🔍 Real-World User Confusion

### Case Study: Azure SWA Deployment Rule

**Scenario:**
A user wanted to create a deployment validation rule for Azure Static Web Apps and asked:

> "Should this rule go in `global_rules` or `frame_rules`?"

**User's Mental Model (Incorrect):**
```yaml
# Option 1: Global (user thinks this will run on all frames)
global_rules:
  - azure-swa-deployment-health  # ❌ User expects: "Runs everywhere"

# Option 2: Frame-specific (user thinks this only runs once)
frame_rules:
  architecture:
    pre_rules:
      - azure-swa-deployment-health  # ✅ Correct, but user is confused why
```

**User's Questions:**
1. "What's the difference between `global_rules` and `frame_rules.pre_rules`?"
2. "If I add a rule to `global_rules`, does it run automatically?"
3. "Why do I need to add a rule to both `global_rules` AND `frame_rules`?"

**Root Cause:**
The name `global_rules` **implies automatic execution**, but the **actual behavior is manual attachment**.

---

### Documentation vs Implementation Mismatch

**Documentation Claims (USER_GUIDE_PRE_POST_RULES.md:1008-1040):**
```yaml
# Global rules (apply to ALL frames, PRE-execution)
global_rules:
  - no-secrets        # Check for secrets in all frames
  - file-size-limit   # Resource limit for all frames

# Execution order:
# 1. Global rules (initialized in CustomRuleValidator)  ← MISLEADING!
# 2. Frame PRE rules (frame-specific checks)
# 3. Frame validation logic executes
# 4. Frame POST rules (result verification)
```

**Actual Implementation (orchestrator.py:62):**
```python
# Global rules are initialized but NEVER executed automatically!
self.rule_validator = CustomRuleValidator(self.config.global_rules)

# Only frame_rules.pre_rules and frame_rules.post_rules are executed
pre_violations = await self._execute_rules(frame_rules.pre_rules, code_file)
post_violations = await self._execute_rules(frame_rules.post_rules, code_file)
```

**The Problem:**
- Documentation says: "Global rules run on ALL frames"
- Code reality: "Global rules are just a reusability marker"

---

## 🔬 Current Implementation Analysis

### Code Evidence

**File: `src/warden/pipeline/application/orchestrator.py`**

```python
# Line 62: Global rules are initialized
self.rule_validator = CustomRuleValidator(self.config.global_rules)

# Lines 285-321: Only frame-specific rules are executed
async def _execute_frame(self, pipeline, frame, frame_exec, code_files):
    # Get frame-specific rules
    frame_rules = self.config.frame_rules.get(frame.frame_id)

    # Execute PRE rules (frame-specific)
    pre_violations = await self._execute_rules(
        frame_rules.pre_rules,  # ← Only frame rules!
        code_file,
    )

    # Execute POST rules (frame-specific)
    post_violations = await self._execute_rules(
        frame_rules.post_rules,  # ← Only frame rules!
        code_file,
    )
```

**Observation:**
- `self.rule_validator` is created with `global_rules` but **never called**
- Only `frame_rules.pre_rules` and `frame_rules.post_rules` are executed
- `global_rules` acts as a **reusability whitelist**, not an execution list

---

### Actual Behavior

**What `global_rules` Really Does:**

```yaml
rules:
  - id: "no-secrets"
  - id: "azure-swa"

global_rules:
  - no-secrets  # ← "no-secrets can be used in multiple frames"

frame_rules:
  security:
    pre_rules:
      - no-secrets     # ✅ OK (in global_rules, can be reused)

  architecture:
    pre_rules:
      - no-secrets     # ✅ OK (in global_rules, can be reused)
      - azure-swa      # ❌ ERROR (not in global_rules, can't reuse)
```

**Validation Logic (Implied):**
```python
# If a rule is used in multiple frames:
if rule_id not in global_rules and usage_count > 1:
    raise ValidationError(f"Rule '{rule_id}' is used in {usage_count} frames but not in global_rules")
```

**Conclusion:**
`global_rules` is a **reusability permission list**, not a **global execution list**.

---

## 💡 Why This Needs to Change

### 1. Semantic Correctness

**Current (Incorrect):**
- "Global" implies universal automatic execution
- Users expect: "Add to global_rules → runs everywhere"
- Reality: "Add to global_rules → can be reused, but must attach manually"

**Proposed (Correct):**
- "Reusable" clearly indicates the purpose
- Users understand: "Add to reusable_rules → can attach to multiple frames"
- Reality matches expectation

---

### 2. Prevent User Errors

**Common Mistake:**
```yaml
# User adds rule to global_rules expecting it to run everywhere
global_rules:
  - my-critical-security-check  # ❌ User expects: "Runs on all frames"

# User forgets to attach to frames
frame_rules:
  security:
    pre_rules: []  # ❌ Rule doesn't run! User doesn't realize.
```

**With `reusable_rules`:**
```yaml
# User understands: "This rule CAN be reused, but I must attach it"
reusable_rules:
  - my-critical-security-check  # ✅ Clear: "Reusable, not automatic"

# User knows they must attach
frame_rules:
  security:
    pre_rules:
      - my-critical-security-check  # ✅ Explicit attachment
```

---

### 3. Documentation Alignment

**Current Mismatch:**
- Docs say: "Global rules apply to ALL frames"
- Code does: "Global rules are a reusability marker"
- **Users are confused**

**After Rename:**
- Docs will say: "Reusable rules can be attached to multiple frames"
- Code does: "Reusable rules are a reusability marker"
- **Perfect alignment**

---

### 4. API Clarity for MVP

**Why Fix Before MVP:**
- ✅ **No existing users yet** → Breaking change is safe
- ✅ **Prevents technical debt** → Better to fix now than maintain legacy
- ✅ **Sets correct expectations** → First impressions matter
- ✅ **Reduces support burden** → Less confusion = fewer questions

**If We Wait Until After MVP:**
- ❌ **Breaking change affects production users**
- ❌ **Need to maintain two APIs** (old + new)
- ❌ **Deprecation period required** (6+ months)
- ❌ **Migration pain for early adopters**

---

## ✅ Proposed Solution

### 1. Rename: `global_rules` → `shared_rules`

**Before:**
```yaml
global_rules:
  - no-secrets
  - file-size-limit

frame_rules:
  security:
    pre_rules:
      - no-secrets
```

**After:**
```yaml
shared_rules:
  - no-secrets
  - file-size-limit

frame_rules:
  security:
    pre_rules:
      - no-secrets
```

---

### 2. Add Inline Documentation

```yaml
# ============================================================================
# SHARED RULES
# ============================================================================
# Rules listed here can be shared across MULTIPLE consumers:
#   - Multiple frames (security, architecture, etc.)
#   - External services (validation service, API gateway)
#   - LLM context (for AI-powered analysis)
#
# If a rule is NOT in this list, it can only be used in ONE place.
#
# Purpose:
#   - Declares which rules are shareable/reusable
#   - Prevents accidental duplication
#   - Makes dependencies explicit
#
# Example:
#   - no-secrets: Shared across security + architecture frames + LLM
#   - azure-swa: Project-specific, used only in architecture frame (not here)
# ============================================================================
shared_rules:
  - no-secrets
  - file-size-limit
```

---

### 3. Improve Validation Errors

**Current (Unhelpful):**
```
ERROR: Invalid configuration
```

**Proposed (Actionable):**
```
ERROR: Rule 'azure-swa-deployment' is used in 2 places but not marked as shared.

Consumers using this rule:
  - security.pre_rules (frame)
  - architecture.pre_rules (frame)

Solution:
  Add 'azure-swa-deployment' to the 'shared_rules' section:

  shared_rules:
    - azure-swa-deployment
```

---

### 4. Add CLI Validation Command

```bash
warden rules validate --check-shareability

# Output:
✅ Rule 'no-secrets' is shared and used by 3 consumers (security, architecture, llm_context)
⚠️  Rule 'azure-swa' is marked as shared but only used in 1 place (unnecessary)
❌ Rule 'file-check' is used by 2 consumers but NOT marked as shared
   Add to shared_rules section to fix
```

---

## 💥 Breaking Changes

### What Changes

| Item | Before | After | Impact |
|------|--------|-------|--------|
| **YAML Key** | `global_rules` | `shared_rules` | BREAKING |
| **Python Model** | `global_rules: List[str]` | `shared_rules: List[str]` | BREAKING |
| **JSON Key** | `globalRules` | `sharedRules` | BREAKING |
| **Documentation** | "Global rules run everywhere" | "Shared rules can be used by multiple consumers" | Non-breaking |

---

### Files Affected

```
src/warden/rules/domain/models.py
  - ProjectRuleConfig.global_rules → shared_rules

src/warden/rules/infrastructure/yaml_loader.py
  - Load global_rules → shared_rules

src/warden/pipeline/domain/models.py
  - PipelineConfig.global_rules → shared_rules

src/warden/pipeline/application/orchestrator.py
  - self.rule_validator = CustomRuleValidator(self.config.shared_rules)

.warden/rules.yaml (all projects)
  - global_rules: → shared_rules:

docs/USER_GUIDE_PRE_POST_RULES.md
  - Update all references

tests/rules/**/*.py
  - Update test fixtures
```

---

## 🔄 Migration Guide

### For Users (Project Owners)

**Step 1: Update YAML Configuration**

```diff
# .warden/rules.yaml

- global_rules:
+ shared_rules:
    - no-secrets
    - file-size-limit
```

**Step 2: No Other Changes Needed**

✅ `frame_rules` section stays the same
✅ Rule definitions stay the same
✅ Behavior is identical

---

### For Developers (Warden Contributors)

**Step 1: Update Python Models**

```diff
# src/warden/rules/domain/models.py

@dataclass
class ProjectRuleConfig:
-   global_rules: List[str] = field(default_factory=list)
+   shared_rules: List[str] = field(default_factory=list)
```

**Step 2: Update YAML Loader**

```diff
# src/warden/rules/infrastructure/yaml_loader.py

-   global_rules_ids = data.get("global_rules", [])
+   shared_rules_ids = data.get("shared_rules", [])
```

**Step 3: Update JSON Serialization**

```diff
# src/warden/rules/domain/models.py

def to_json(self) -> dict:
    return {
-       "globalRules": self.global_rules,
+       "sharedRules": self.shared_rules,
    }
```

---

## 📅 Implementation Plan

### Phase 1: Code Changes (Week 1)

**Priority 1: Core Models**
- [ ] Update `ProjectRuleConfig.global_rules` → `shared_rules`
- [ ] Update `PipelineConfig.global_rules` → `shared_rules`
- [ ] Update JSON serialization (camelCase: `sharedRules`)

**Priority 2: Infrastructure**
- [ ] Update `RulesYAMLLoader` to read `shared_rules`
- [ ] Update orchestrator initialization
- [ ] Add deprecation warning for `global_rules`

**Priority 3: Validation**
- [ ] Add shareability validation logic
- [ ] Improve error messages
- [ ] Add CLI validation command (`--check-shareability`)

---

### Phase 2: Documentation (Week 1)

**Update Docs:**
- [ ] `USER_GUIDE_PRE_POST_RULES.md` → Replace all `global_rules` references
- [ ] `.warden/rules.example.yaml` → Use `shared_rules`
- [ ] `README.md` → Update examples

**Add New Docs:**
- [ ] Migration guide for users
- [ ] Inline YAML comments explaining shareability
- [ ] Document usage with frames, services, and LLM context

---

### Phase 3: Testing (Week 1)

**Update Tests:**
- [ ] Fix all test fixtures (`global_rules` → `shared_rules`)
- [ ] Add tests for shareability validation
- [ ] Add tests for deprecation warnings
- [ ] Test usage across frames, services, LLM context

**Integration Tests:**
- [ ] Test old config (with deprecation warning)
- [ ] Test new config (no warnings)
- [ ] Test migration scenarios

---

### Phase 4: Deprecation (Optional, if needed)

**If backward compatibility is required:**

```python
# Support both keys temporarily
shared_rules_ids = data.get("shared_rules") or data.get("global_rules", [])

if "global_rules" in data:
    logger.warning(
        "DEPRECATED: 'global_rules' is deprecated, use 'shared_rules' instead. "
        "Support for 'global_rules' will be removed in v2.0.0"
    )
```

**Timeline:**
- v1.0.0 (MVP): Add deprecation warning
- v1.5.0: Remove support for `global_rules`

---

## 🔒 Backward Compatibility Strategy

### Option A: Hard Break (Recommended for Pre-MVP)

**Approach:** No backward compatibility

**Pros:**
- ✅ Clean break before public release
- ✅ No technical debt
- ✅ Simpler codebase

**Cons:**
- ❌ Internal users must update immediately

**Recommendation:** **Use this** (we're pre-MVP, no external users)

---

### Option B: Deprecation Period (If needed)

**Approach:** Support both keys temporarily

**Implementation:**
```python
# Accept both keys
shared_rules = config.get("shared_rules") or config.get("global_rules", [])

# Warn if using old key
if "global_rules" in config:
    warnings.warn(
        "DeprecationWarning: 'global_rules' is deprecated. "
        "Use 'shared_rules' instead. "
        "Support will be removed in v2.0.0",
        DeprecationWarning
    )
```

**Timeline:**
- v1.0.0: Support both, warn on `global_rules`
- v1.5.0: Remove `global_rules` support

**Recommendation:** Only if we have external beta testers

---

## ⏱️ Timeline

### Pre-MVP (Recommended)

**Week 1:**
- Monday: Code changes (models, loaders, serialization)
- Tuesday: Documentation updates
- Wednesday: Test updates
- Thursday: Integration testing
- Friday: Code review + merge

**Week 2:**
- Monday: Update all internal projects (.warden/rules.yaml)
- Tuesday: Final validation
- Wednesday: **SHIP MVP**

---

### Post-MVP (If we miss the window)

**Version 1.0.0 (MVP Release):**
- Ship with `global_rules` (current naming)
- Add TODO comment about future rename

**Version 1.1.0 (3 months later):**
- Add `shared_rules` support
- Add deprecation warning for `global_rules`
- Update documentation

**Version 2.0.0 (6 months later):**
- Remove `global_rules` support (breaking change)
- Final migration

---

## 🎯 Recommendation

**DO THIS NOW (Pre-MVP):**

1. ✅ **Hard break rename** → No backward compatibility needed
2. ✅ **Update all code** → One clean change
3. ✅ **Update all docs** → Prevent future confusion
4. ✅ **Ship MVP with correct naming** → Right from the start

**Why?**
- No external users yet → Safe to break
- Sets correct expectations → First impression matters
- Prevents technical debt → No legacy support needed
- Better developer experience → Clear, semantic naming

---

## 📞 Questions & Feedback

**Maintainer:** Warden Team
**Contact:** [GitHub Issues](https://github.com/yourorg/warden-core/issues)
**Discussion:** [RFC: Rename global_rules to shared_rules](https://github.com/yourorg/warden-core/discussions/XXX)

---

## 📝 Appendix: Alternative Names Considered

| Name | Pros | Cons | Score |
|------|------|------|-------|
| `shared_rules` | ✅ Short<br>✅ Generic (frames, services, LLM)<br>✅ Common term<br>✅ Industry standard | None significant | ⭐⭐⭐⭐⭐ |
| `reusable_rules` | ✅ Clear purpose<br>✅ Semantic accuracy | ❌ Frame-focused, less generic | ⭐⭐⭐⭐ |
| `common_rules` | ✅ Short | ❌ Vague meaning | ⭐⭐⭐ |
| `library_rules` | ✅ Good metaphor | ❌ Slightly metaphorical | ⭐⭐⭐⭐ |
| `multi_use_rules` | ✅ Very explicit | ❌ Too verbose | ⭐⭐⭐ |

**Decision:** `shared_rules`

**Rationale:**
- Most generic: Works for frames, services, LLM context, external tools
- Industry standard: "Shared library", "shared resource" are familiar concepts
- Short and clear: Same length as `global_rules`, easy to type
- Accurately describes behavior: Rules that are shared across multiple consumers

---

**Document Version:** 1.0
**Last Updated:** 2025-12-23
**Status:** Awaiting approval
**Next Steps:** Team review → Approve → Implement → Ship MVP
