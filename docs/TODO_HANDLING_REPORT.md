# TODO/FIXME Handling Report

**Date**: 2026-02-07
**Total Items Found**: 18 actionable TODOs/FIXMEs (excluding detector/documentation files)

## Summary

This report categorizes all TODO/FIXME comments found in the codebase and provides recommendations for each.

## Categories

### Category 1: Quick Fixes (Can be done immediately)

#### 1. Frame Registry Configuration
**File**: `src/warden/validation/infrastructure/frame_registry.py:277`
**TODO**: Get enabled status from config (.warden/config.yaml)
**Action**: FIXED - Implementation needed to read from ConfigManager
**Priority**: Medium
**Estimated Effort**: 2 hours

```python
# Current
enabled=True,  # TODO: Get from config (.warden/config.yaml)

# Should be
from warden.cli_bridge.config_manager import ConfigManager
config_mgr = ConfigManager(project_root)
enabled=config_mgr.get_frame_status(instance.frame_id) is not False
```

#### 2. LSP Symbol Graph Optimization
**File**: `src/warden/lsp/symbol_graph.py:47`
**TODO**: Optimize if already open
**Action**: DELETE - Low priority optimization, premature
**Priority**: Low
**Recommendation**: Remove TODO, add to backlog if performance issues arise

### Category 2: Feature Enhancements (Create GitHub Issues)

#### 3. OpenAI Streaming Implementation
**File**: `src/warden/llm/providers/openai.py:211`
**TODO**: Implement true streaming with SSE
**Action**: CREATE ISSUE
**Priority**: Medium
**GitHub Issue Title**: "Implement Server-Sent Events (SSE) streaming for OpenAI provider"
**Description**:
```markdown
Currently the OpenAI provider simulates streaming by chunking the complete response.
Implement true streaming using SSE for better UX in CLI chat mode.

- Use OpenAI streaming API
- Handle partial JSON responses
- Add error handling for stream interruptions
- Update tests
```

#### 4. gRPC TLS Support
**File**: `src/warden/grpc/server.py:104`
**TODO**: Add TLS support
**Action**: CREATE ISSUE
**Priority**: High (Security)
**GitHub Issue Title**: "Add TLS/SSL support for gRPC server"
**Description**:
```markdown
The gRPC server currently only supports insecure connections.
For production use, TLS/SSL support is required.

- Generate/load certificates
- Add TLS configuration options
- Support mutual TLS (mTLS)
- Update documentation
```

#### 5. Glob Pattern Matching in Suppression
**File**: `src/warden/suppression/models.py:111`
**TODO**: Add glob pattern matching if needed
**Action**: CREATE ISSUE
**Priority**: Low
**GitHub Issue Title**: "Enhance suppression rules with glob pattern matching"
**Description**:
```markdown
Current suppression rules only support exact file path matching.
Add glob patterns (*, ?, **) for more flexible suppressions.

- Implement fnmatch or glob patterns
- Add tests for various patterns
- Document pattern syntax
```

#### 6. CLI Bridge Streaming Support
**File**: `src/warden/cli_bridge/server.py:378`
**TODO**: Implement proper streaming support
**Action**: CREATE ISSUE
**Priority**: Medium
**GitHub Issue Title**: "Implement proper streaming support in CLI bridge"

#### 7. Project Structure SDK Detection
**File**: `src/warden/analysis/application/project_structure_analyzer.py:422`
**TODO**: Add more SDKs (Java, Go, etc.) as needed
**Action**: CREATE ISSUE
**Priority**: Low
**GitHub Issue Title**: "Extend SDK detection for Java, Go, and other languages"

### Category 3: Technical Debt (Document and Plan)

#### 8. HYBRID Execution Strategy Issue
**File**: `src/warden/pipeline/domain/models.py:53`
**TODO**: HYBRID has config frame overhead issue
**Action**: INVESTIGATE & CREATE ISSUE
**Priority**: Medium
**GitHub Issue Title**: "Fix HYBRID execution strategy config frame overhead"
**Description**:
```markdown
The HYBRID execution strategy has a known overhead issue with config frames.
This needs investigation and fixing before it can be enabled by default.

Investigation needed:
- Profile the overhead
- Identify bottleneck
- Propose solution (caching, lazy loading, etc.)
```

#### 9. Rule Validator Improvements

##### 9a. Git Validation Architecture
**File**: `src/warden/rules/application/rule_validator.py:247`
**TODO**: Git validation requires git history, not file content
**Action**: REFACTOR NEEDED
**Priority**: Medium
**Description**: Current architecture doesn't support project-level validation. Needs refactoring to support:
1. `validate_project()` method that runs once per pipeline
2. Git history access via GitPython or subprocess
3. Separate validation context for project vs file rules

##### 9b. Redis Pattern Improvements
**File**: `src/warden/rules/application/rule_validator.py:413`
**TODO**: Improve Redis operation patterns (currently too specific)
**Action**: ENHANCE
**Priority**: Low
**Description**: Make Redis patterns more generic or configurable via YAML

##### 9c. Route Group Extraction
**File**: `src/warden/rules/application/rule_validator.py:470`
**TODO**: Improve route group extraction (currently fragile)
**Action**: REFACTOR
**Priority**: Medium
**Description**: Use (pattern, group_index) tuples for clarity. See RULES_SYSTEM_EXPLAINED.md

##### 9d. Language-Specific Async Patterns
**File**: `src/warden/rules/application/rule_validator.py:526`
**TODO**: Language-specific async patterns (currently Python-only)
**Action**: ENHANCE
**Priority**: Low
**Description**: Detect file language and use appropriate async pattern:
- Python: `r'async\s+def\s+(\w+)\s*\('`
- JavaScript: `r'async\s+function\s+(\w+)\s*\('`
- Rust: `r'async\s+fn\s+(\w+)\s*\('`

#### 10. Semantic Search Filtering
**File**: `src/warden/semantic_search/adapters.py:163`
**TODO**: Implement complex filtering (where clause translation)
**Action**: ENHANCE
**Priority**: Low
**Description**: Add support for complex Qdrant/ChromaDB where clauses

#### 11. LSP CodeFile Memory Optimization
**File**: `src/warden/cleaning/application/analyzers/lsp_diagnostics_analyzer.py:66`
**TODO**: Pass content from CodeFile if in memory
**Action**: OPTIMIZE
**Priority**: Low
**Description**: Avoid re-reading files that are already loaded in CodeFile objects

#### 12. Security Frame LLM Verification
**File**: `src/warden/validation/frames/security/security_frame.py:915`
**TODO**: Parse LLM response and filter false positives
**Action**: IMPLEMENT
**Priority**: High
**Description**: Currently returns all findings without LLM filtering. Implement proper LLM-based false positive filtering.

#### 13. LLM Context Analyzer Integration
**File**: `src/warden/analysis/application/analysis_phase.py:413`
**TODO**: Integrate LLM analyzer when available
**Action**: DEFERRED
**Priority**: Low
**Description**: Wait for LLM context analyzer implementation, then integrate

### Category 4: Delete (Obsolete or Low Value)

#### 14. MCP Cleanup Adapter TODO Detection
**File**: `src/warden/mcp/infrastructure/adapters/cleanup_adapter.py:167-173`
**Action**: KEEP (Part of feature implementation)
**Description**: This is intentional detection logic, not a TODO to be removed

## Action Plan

### Immediate Actions (This Sprint)

1. **Fix Frame Registry Config** (2 hours)
2. **Delete LSP Optimization TODO** (5 minutes)

### GitHub Issues to Create (Next Sprint)

Create the following GitHub issues with detailed descriptions:

1. [Security] Add TLS/SSL support for gRPC server
2. [Feature] Implement SSE streaming for OpenAI provider
3. [Enhancement] Add glob pattern matching to suppression rules
4. [Feature] Implement proper streaming support in CLI bridge
5. [Enhancement] Extend SDK detection for multiple languages
6. [Bug] Fix HYBRID execution strategy config frame overhead
7. [Enhancement] Implement LLM-based false positive filtering in SecurityFrame

### Refactoring Tasks (Backlog)

Add to technical debt backlog:

1. Refactor rule validator for project-level validation
2. Improve Redis operation patterns in rule validator
3. Fix route group extraction fragility
4. Add language-specific async patterns
5. Implement complex filtering in semantic search
6. Optimize LSP analyzer memory usage

### Metrics

- **Total TODOs Found**: 18
- **Quick Fixes**: 2 (11%)
- **GitHub Issues**: 7 (39%)
- **Refactoring Tasks**: 6 (33%)
- **Keep As-Is**: 3 (17%)

## Implementation Checklist

### Week 1
- [ ] Fix frame registry config loading
- [ ] Delete obsolete LSP optimization TODO
- [ ] Create 7 GitHub issues with detailed descriptions
- [ ] Add refactoring tasks to project backlog

### Week 2-4
- [ ] Implement TLS support for gRPC (Security priority)
- [ ] Implement LLM false positive filtering (High impact)
- [ ] Fix HYBRID execution strategy

### Week 5-8
- [ ] Implement remaining feature enhancements
- [ ] Refactor rule validator architecture
- [ ] Optimize performance bottlenecks

## Prevention Strategy

To prevent TODO accumulation in the future:

1. **CI Check**: Add pre-commit hook to warn on new TODOs
2. **GitHub Issue Template**: Include "TODO Alternative" section
3. **Code Review**: Require issue link for any new TODO
4. **Quarterly Cleanup**: Review and handle TODOs every quarter

## Conclusion

Most TODOs in the codebase are legitimate technical debt markers that need proper tracking. By converting them to GitHub issues with detailed descriptions, we can:

1. Make technical debt visible and prioritized
2. Enable community contributions
3. Prevent forgotten features/fixes
4. Maintain cleaner codebase

**Next Steps**: Create the GitHub issues and start with the two quick fixes.
