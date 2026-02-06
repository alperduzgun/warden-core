# Batch Processing Pattern for Validation Frames

**Author:** Warden Team
**Date:** 2026-02-06
**Status:** Production Ready (OrphanFrame)

---

## 📋 Overview

Batch processing reduces LLM API calls by **80-95%** by processing multiple findings/files in a single request.

**Current Implementation:** OrphanFrame (Reference Implementation)
**Target Frames:** SecurityFrame, ResilienceFrame, PropertyFrame, FuzzFrame

---

## 🏗️ Architecture Pattern

### 1. **Interface Definition**

All frames must implement:
```python
async def execute_batch_async(
    self,
    code_files: List[CodeFile]
) -> List[FrameResult]:
    """Execute frame on multiple files with smart batching."""
    pass
```

### 2. **Execution Flow**

```
┌─────────────────────────────────────────────┐
│ 1. FLATTEN FINDINGS                         │
│    Pattern/AST phase finds candidates       │
│    100 findings from 20 files               │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│ 2. CACHE CHECK (Optional but Recommended)   │
│    Check pattern cache                      │
│    30 findings → CACHE HIT (skip)           │
│    70 findings → Need LLM verification      │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│ 3. SMART BATCHING                           │
│    Token-aware grouping:                    │
│    - MAX_SAFE_TOKENS = 6000                 │
│    - batch_size = 10 (configurable)         │
│    Result: 7 batches                        │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│ 4. LLM PROCESSING (Batched)                 │
│    7 batches × 1 LLM call = 7 requests      │
│    (vs 100 naive sequential requests)       │
│    Reduction: 93% fewer LLM calls!          │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│ 5. CACHE UPDATE                             │
│    Store false positives for future         │
│    Next scan: 95% cache hit rate            │
└─────────────────────────────────────────────┘
```

---

## 📦 OrphanFrame Implementation (Reference)

### File Structure
```
orphan/
├── orphan_frame.py          # Main frame (execute_batch_async)
└── llm_orphan_filter.py     # LLM batch filtering logic
```

### Key Methods

**1. execute_batch_async() - Entry Point**
```python
# orphan_frame.py:106-247
async def execute_batch_async(
    self,
    code_files: List[CodeFile]
) -> List[FrameResult]:
    # Phase 1: AST Analysis (Fast, Parallel)
    findings_map = await self._run_ast_analysis(code_files)

    # Phase 2: LLM Batch Filtering (Smart Batching)
    if self.llm_filter:
        findings_map = await self.llm_filter.filter_findings_batch(
            findings_map,
            code_files
        )

    # Phase 3: Build Results
    return self._build_results(findings_map, code_files)
```

**2. filter_findings_batch() - Batch Logic**
```python
# llm_orphan_filter.py:218-352
async def filter_findings_batch(
    self,
    findings_map: Dict[str, List[Finding]],
    code_files: List[CodeFile]
) -> Dict[str, List[Finding]]:
    # 1. Flatten findings
    all_findings = self._flatten_findings(findings_map)

    # 2. Cache check
    cache_hits, need_llm = self._check_cache(all_findings)

    # 3. Smart batching
    batches = self._batch_findings(need_llm, max_batch_size=10)

    # 4. Process batches
    for batch in batches:
        verified = await self._filter_multi_file_batch(batch, code_files)
        # Store results

    # 5. Update cache
    self._update_cache(verified_findings)

    return filtered_findings_map
```

**3. _batch_findings() - Token-Aware Batching**
```python
def _batch_findings(
    self,
    findings: List[Finding],
    max_batch_size: int = 10
) -> List[List[Finding]]:
    """Group findings into batches by token limit."""
    MAX_SAFE_TOKENS = 6000
    batches = []
    current_batch = []
    current_tokens = 0

    for finding in findings:
        estimated_tokens = len(finding.code_snippet.split()) * 1.5

        if current_tokens + estimated_tokens > MAX_SAFE_TOKENS:
            # Batch full, start new one
            batches.append(current_batch)
            current_batch = [finding]
            current_tokens = estimated_tokens
        else:
            current_batch.append(finding)
            current_tokens += estimated_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
```

**4. _filter_multi_file_batch() - LLM Call**
```python
async def _filter_multi_file_batch(
    self,
    batch: List[Finding],
    code_files: List[CodeFile]
) -> List[Finding]:
    """Single LLM call for multiple findings."""

    # Build prompt with all findings
    prompt = self._build_batch_prompt(batch, code_files)

    # Single LLM call
    response = await self.llm_client.send_async(
        prompt=prompt,
        system="You are a senior code reviewer..."
    )

    # Parse response
    verified = self._parse_batch_response(response, batch)

    return verified
```

---

## 🎯 Applying Pattern to SecurityFrame

### Current State (SecurityFrame)
```python
# security_frame.py:Line 470
async def execute_async(self, code_file: CodeFile) -> FrameResult:
    # Pattern checks (regex)
    candidates = self._run_pattern_checks(code_file)

    # LLM verification (1 call per file!)
    for candidate in candidates:
        verified = await self.llm_verify(candidate)  # ❌ Sequential!

    return FrameResult(...)
```

**Problem:** 100 files × 3 findings/file = 300 LLM calls!

### Proposed State (Batch Processing)
```python
# security_frame.py (NEW)
async def execute_batch_async(
    self,
    code_files: List[CodeFile]
) -> List[FrameResult]:
    # Phase 1: Pattern checks (Fast, all files)
    findings_map = {}
    for code_file in code_files:
        findings_map[code_file.path] = self._run_pattern_checks(code_file)

    # Phase 2: Batch LLM verification
    findings_map = await self._batch_verify_findings(findings_map, code_files)

    # Phase 3: Build results
    return self._build_results(findings_map, code_files)

async def _batch_verify_findings(
    self,
    findings_map: Dict[str, List[Finding]],
    code_files: List[CodeFile]
) -> Dict[str, List[Finding]]:
    # Same pattern as OrphanFrame
    all_findings = self._flatten(findings_map)
    batches = self._smart_batch(all_findings, max_size=10)

    for batch in batches:
        verified = await self._verify_batch(batch)  # ✅ Single LLM call!

    return filtered_findings_map
```

**Result:** 300 LLM calls → ~30 LLM calls (**90% reduction!**)

---

## 📊 Performance Impact

| Frame | Current (100 files) | With Batching | Reduction |
|-------|---------------------|---------------|-----------|
| **OrphanFrame** | ✅ 7 calls | ✅ 7 calls | Baseline |
| **SecurityFrame** | 100 calls | ~15 calls | **85%** |
| **ResilienceFrame** | 100 calls | ~20 calls | **80%** |
| **PropertyFrame** | 100 calls | ~10 calls | **90%** |
| **FuzzFrame** | 100 calls | ~10 calls | **90%** |

**Estimated Total Speedup:** 3-5x for large projects (100+ files)

---

## 🔧 Implementation Checklist

For each frame that needs batch processing:

- [ ] **1. Add execute_batch_async() method**
  - Override default implementation
  - Handle multi-file input

- [ ] **2. Separate pattern/AST phase from LLM phase**
  - Pattern checks: Fast, deterministic
  - LLM verification: Slow, needs batching

- [ ] **3. Implement smart batching**
  - Token-aware grouping
  - MAX_SAFE_TOKENS = 6000
  - Configurable batch_size

- [ ] **4. Build batch prompt**
  - Include multiple findings in one prompt
  - Clear delimiters
  - Structured output format

- [ ] **5. Parse batch response**
  - Extract per-finding results
  - Handle partial failures
  - Maintain finding metadata

- [ ] **6. (Optional) Add caching**
  - Pattern-based cache key
  - Serialize/deserialize cache
  - Invalidation strategy

---

## 🎓 Best Practices

### 1. **Token Management**
```python
MAX_SAFE_TOKENS = 6000  # Leave room for response
# Estimate: ~1.5 tokens per word
estimated_tokens = len(text.split()) * 1.5
```

### 2. **Batch Size**
```python
# Too small: More LLM calls, less savings
# Too large: Token limit exceeded, parsing errors
RECOMMENDED_BATCH_SIZE = 10  # Sweet spot
```

### 3. **Error Handling**
```python
try:
    verified = await self._verify_batch(batch)
except TokenLimitError:
    # Fall back to smaller batches
    for finding in batch:
        verified = await self._verify_single(finding)
```

### 4. **Progress Reporting**
```python
for i, batch in enumerate(batches):
    logger.info(f"Processing batch {i+1}/{len(batches)}")
    # User sees progress even with batching
```

### 5. **Caching Strategy**
```python
# Cache key: finding pattern + code context hash
cache_key = f"{finding.type}:{hashlib.md5(finding.code_snippet.encode()).hexdigest()}"
```

---

## 📚 References

- **OrphanFrame Implementation:** `src/warden/validation/frames/orphan/`
- **Benchmark Results:** `benchmarks/COMPARISON_REPORT.md`
- **Performance Analysis:** Shows 95% cache hit rate, 93% LLM call reduction

---

**Next Steps:**
1. Apply pattern to SecurityFrame (highest priority)
2. Benchmark and validate
3. Extend to ResilienceFrame, PropertyFrame, FuzzFrame
4. Document results and update README

---

**Status:** ✅ Pattern Documented, Ready for Implementation
