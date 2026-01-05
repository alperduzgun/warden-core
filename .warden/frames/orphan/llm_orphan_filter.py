"""
LLM-Powered Orphan Code Filter

Intelligent false positive filtering using LLM context awareness.
Works for ANY programming language by leveraging LLM's understanding of code patterns.

Architecture:
    1. AST detector finds potential orphans (fast, language-specific)
    2. LLM filter removes false positives (smart, language-agnostic)
    3. Final report contains only TRUE orphans

Usage:
    ```python
    # Basic usage
    filter = LLMOrphanFilter()
    true_orphans = await filter.filter_findings(
        findings=ast_findings,
        code_file=code_file,
        language="python"
    )

    # With custom config
    config = LlmConfiguration(provider="anthropic", model="claude-3-5-sonnet")
    filter = LLMOrphanFilter(llm_config=config)
    ```

Author: Warden Team
Date: 2025-12-21
"""

import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from warden.llm.factory import create_client
from warden.llm.config import LlmConfiguration
from warden.llm.types import LlmRequest, LlmResponse
from orphan_detector import OrphanFinding
from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FilterDecision:
    """LLM decision for a single finding."""

    finding_id: int
    is_true_orphan: bool
    reasoning: str
    confidence: float = 1.0  # LLM confidence (0-1)


class LLMOrphanFilter:
    """
    LLM-powered intelligent orphan code filter.

    Filters false positives from AST-based detection using LLM's deep understanding
    of programming patterns, frameworks, and language idioms.

    Supports:
        - Python (@property, @abstractmethod, ABC, Protocol)
        - JavaScript/TypeScript (decorators, exports, interfaces)
        - Go (interfaces, capital = public)
        - Rust (traits, macros, pub)
        - C# (attributes, interfaces)
        - Java (annotations, interfaces)
        - And any other language LLM understands!
    """

    # Language-specific hints for LLM
    LANGUAGE_HINTS = {
        "python": {
            "decorators": ["@property", "@abstractmethod", "@click.command", "@pytest.fixture"],
            "protocols": ["ABC", "Protocol", "TypedDict"],
            "special_files": ["__init__.py", "__main__.py"],
            "serialization": ["to_json", "from_json", "to_dict", "from_dict"],
        },
        "javascript": {
            "decorators": ["@deprecated", "@override"],
            "exports": ["export", "module.exports"],
            "special_files": ["index.js", "index.ts"],
            "serialization": ["toJSON", "fromJSON", "serialize"],
        },
        "typescript": {
            "decorators": ["@Injectable()", "@Component()", "@Service()"],
            "interfaces": ["interface", "type"],
            "exports": ["export"],
            "serialization": ["toJSON", "fromJSON"],
        },
        "go": {
            "interfaces": ["interface", "type"],
            "exports": ["Capital letter = exported"],
            "build_tags": ["//go:generate", "//go:build"],
            "special": ["init()", "main()"],
        },
        "rust": {
            "traits": ["trait", "impl"],
            "macros": ["#[derive]", "#[cfg]"],
            "visibility": ["pub fn", "pub struct"],
            "serialization": ["Serialize", "Deserialize"],
        },
        "csharp": {
            "attributes": ["[HttpGet]", "[JsonProperty]", "[Serializable]"],
            "interfaces": ["interface", "abstract"],
            "properties": ["{ get; set; }"],
        },
        "java": {
            "annotations": ["@Override", "@Bean", "@Autowired"],
            "interfaces": ["interface", "abstract"],
            "serialization": ["Serializable"],
        },
    }

    def __init__(
        self,
        llm_service: Optional[Any] = None,
        semantic_search_service: Optional[Any] = None,
        batch_size: int = 10,  # Lowered default for safety
        max_retries: int = 2,
    ):
        """
        Initialize LLM orphan filter.

        Args:
            llm_config: LLM configuration (uses default if None)
            llm_service: Pre-configured LLM service (preferred over creating new)
            semantic_search_service: Optional semantic search service
            batch_size: Number of findings to process per LLM call (default: 10)
            max_retries: Max retries on LLM failure (default: 2)
        """
        if llm_service:
            self.llm = llm_service
        else:
            self.llm = create_client(llm_config)
            
        self.semantic_search_service = semantic_search_service
        self.batch_size = batch_size
        self.max_retries = max_retries
        
        # Pattern decision cache: stores LLM decisions by pattern key
        # Key: (orphan_type, reason_pattern) -> Value: (is_true_orphan, reasoning)
        # When LLM decides a pattern is false positive, we cache it to avoid redundant calls
        self._pattern_cache: Dict[str, tuple[bool, str]] = {}
        
        # Persistence
        self._cache_file = Path(".warden/memory/orphan_patterns.json")
        self._load_cache()

        logger.info(
            "llm_orphan_filter_initialized",
            batch_size=batch_size,
            max_retries=max_retries,
            injected_service=llm_service is not None,
            cached_patterns=len(self._pattern_cache)
        )

    def _load_cache(self):
        """Load pattern cache from disk."""
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text())
                self._pattern_cache = data
        except Exception as e:
            logger.warning("failed_to_load_orphan_cache", error=str(e))

    def _save_cache(self):
        """Save pattern cache to disk."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._pattern_cache, indent=2))
        except Exception as e:
            logger.warning("failed_to_save_orphan_cache", error=str(e))

    def _get_pattern_key(self, finding: OrphanFinding, file_path: str) -> str:
        """Generate a cache key for a finding pattern (project-specific)."""
        # Normalize to relative path for portability
        try:
            cwd = Path.cwd()
            if Path(file_path).is_absolute() and str(cwd) in file_path:
                rel_path = str(Path(file_path).relative_to(cwd))
            else:
                rel_path = file_path
        except Exception:
            rel_path = file_path

        # Pattern key includes type, name, and relative file path
        return f"{finding.orphan_type}:{finding.name}:{rel_path}"

    def _check_pattern_cache(self, finding: OrphanFinding, file_path: str) -> Optional[tuple[bool, str]]:
        """Check if we have a cached decision for this finding pattern."""
        key = self._get_pattern_key(finding, file_path)
        if key in self._pattern_cache:
            # Handle list vs tuple (json loads as list)
            val = self._pattern_cache[key]
            return (val[0], val[1])
        return None

    def _cache_pattern_decision(self, finding: OrphanFinding, file_path: str, is_true_orphan: bool, reasoning: str):
        """Cache an LLM decision for a finding pattern."""
        key = self._get_pattern_key(finding, file_path)
        # Only cache false positives (they're the patterns we want to skip)
        if not is_true_orphan:
            self._pattern_cache[key] = (is_true_orphan, reasoning)
            self._save_cache()  # Persist immediately
            logger.debug(
                "pattern_cached",
                key=key,
                is_true_orphan=is_true_orphan,
                cache_size=len(self._pattern_cache)
            )

    async def filter_findings_batch(
        self,
        findings_map: Dict[str, List[OrphanFinding]], # file_path -> findings
        code_files: Dict[str, CodeFile],
        project_context: Optional[Any] = None,
    ) -> Dict[str, List[OrphanFinding]]:
        """
        Filter findings for multiple files in efficient batches.
        
        This method groups findings from all files, batches them by token/count limit,
        processes them via LLM, and redistributes results back to files.
        """
        if not findings_map:
            return {}

        start_time = time.perf_counter()
        
        # 1. Flatten all findings
        all_flattened: List[tuple[str, OrphanFinding]] = [] # (file_path, finding)
        total_findings = 0
        
        for f_path, f_list in findings_map.items():
            for finding in f_list:
                all_flattened.append((f_path, finding))
            total_findings += len(f_list)
            
        logger.info(
            "llm_batch_filter_started", 
            total_files=len(findings_map), 
            total_findings=total_findings
        )
        
        # 2. Check cache & Create batches
        batch_size = self.batch_size
        batches = []
        current_batch = []
        
        # Track pre-decided findings (from cache)
        # f_path -> list of findings that are CONFIRMED true orphans by cache
        cached_results: Dict[str, List[OrphanFinding]] = {path: [] for path in findings_map.keys()}
        
        skipped_count = 0
        cached_count = 0

        for item in all_flattened:
            f_path, finding = item
            
            # Check pattern cache first
            cached_decision = self._check_pattern_cache(finding, f_path)
            if cached_decision:
                cached_count += 1
                is_true_orphan, reasoning = cached_decision
                if is_true_orphan:
                    # It's a true orphan according to cache, keep it
                    # (But usually we only cache false positives to skip them. 
                    # If we cache true orphans too, we add them here.)
                    cached_results[f_path].append(finding)
                else:
                    # It's a false positive (skipped), don't add to results
                    skipped_count += 1
                    logger.debug("skipping_known_false_positive", pattern=self._get_pattern_key(finding, f_path))
                continue

            # Not in cache, needs LLM verification
            current_batch.append(item)
            if len(current_batch) >= batch_size:
                batches.append(current_batch)
                current_batch = []
        
        # Add remaining items
        if current_batch:
            batches.append(current_batch)
            
        logger.info(
            "smart_filter_optimization", 
            total_items=len(all_flattened),
            cached_hits=cached_count,
            skipped_false_positives=skipped_count,
            items_to_process=sum(len(b) for b in batches)
        )
        
        # 3. Process batches
        results_map: Dict[str, List[OrphanFinding]] = cached_results
        
        for i, batch in enumerate(batches):
            logger.info("processing_smart_batch", index=i+1, total=len(batches), items=len(batch))
            
            try:
                # Process via LLM
                batch_results = await self._filter_multi_file_batch(
                    batch, 
                    code_files,
                    project_context
                )
                
                # Redistribute results & update cache
                # Note: filter_multi_file_batch returns only TRUE orphans
                # We need to know which ones were dropped to cache them as false positives.
                
                # Create a set of kept finding IDs (or objects)
                kept_findings = set()
                for f_path, finding in batch_results:
                    results_map[f_path].append(finding)
                    kept_findings.add(id(finding))

                # Identify false positives (items in batch but not in results)
                for f_path, finding in batch:
                    if id(finding) not in kept_findings:
                        # This finding was filtered out -> FALSE POSITIVE
                        # Cache this pattern so we skip it next time
                        self._cache_pattern_decision(
                            finding, 
                            f_path,
                            is_true_orphan=False, 
                            reasoning="Marked as false positive by LLM batch filter"
                        )

            except Exception as e:
                logger.error("smart_batch_failed", batch=i, error=str(e))
                # Fallback: keep all as potential orphans (conservative)
                for f_path, finding in batch:
                    results_map[f_path].append(finding)
                    
        return results_map

    async def _filter_multi_file_batch(
        self,
        batch: List[tuple[str, OrphanFinding]],
        code_files: Dict[str, CodeFile],
        project_context: Optional[Any] = None,
    ) -> List[tuple[str, OrphanFinding]]:
        """
        Process a mixed batch of findings from different files.
        """
        # Retrieve semantic context for all findings in batch
        semantic_context = ""
        if self.semantic_search_service and self.semantic_search_service.is_available():
            try:
                # Query for potential usages of all findings
                query = " ".join([f"usages of {it[1].name}" for it in batch[:5]])
                search_results = await self.semantic_search_service.search(query=query, limit=5)
                if search_results:
                    semantic_context = "\n[Global Semantic Usage Context]\n"
                    for res in search_results:
                        semantic_context += f"- Potential usage in {res.file_path}: {res.content[:150]}...\n"
            except Exception as e:
                logger.warning("batch_semantic_search_failed", error=str(e))

        # Construct prompt
        prompt = self._build_multi_file_prompt(batch, code_files, project_context)
        
        # Send to LLM with semantic context
        response = await self._call_llm(
            code="", # No single code file
            prompt=prompt + (f"\n# SEMANTIC CONTEXT\n{semantic_context}" if semantic_context else ""),
            language="mixed"
        )
        
        # Parse
        decisions = self._parse_llm_response(response.content, len(batch))
        
        # Filter
        true_orphans = []
        for (f_path, finding), decision in zip(batch, decisions):
            if decision.is_true_orphan:
                true_orphans.append((f_path, finding))
                
        return true_orphans

    def _build_multi_file_prompt(
        self,
        batch: List[tuple[str, OrphanFinding]],
        code_files: Dict[str, CodeFile],
        project_context: Optional[Any] = None,
    ) -> str:
        # Build project context string
        context_str = "Type: Unknown Generic Project"
        project_rules = "- Interface/Abstractions are NOT orphans\n- Framework hooks/decorators are NOT orphans"
        
        if project_context:
            try:
                # Robust extraction from Pydantic model or similar object
                name = getattr(project_context, 'project_name', 'Unknown')
                p_type = getattr(project_context, 'project_type', None)
                framework = getattr(project_context, 'framework', None)
                arch = getattr(project_context, 'architecture', None)
                purpose = getattr(project_context, 'purpose', 'No specific purpose defined')
                
                # Convert Enums to string if needed
                p_type_str = p_type.value if hasattr(p_type, 'value') else str(p_type)
                fw_str = framework.value if hasattr(framework, 'value') else str(framework)
                arch_str = arch.value if hasattr(arch, 'value') else str(arch)
                
                context_str = (
                    f"Project: {name}\n"
                    f"Type: {p_type_str.upper()}\n"
                    f"Framework: {fw_str}\n"
                    f"Architecture: {arch_str}\n"
                    f"Purpose: {purpose}\n"
                )
                
                # Dynamic Rule Generation Phase
                rules = []
                
                # 1. Project Type Rules
                if "library" in p_type_str.lower() or "monorepo" in p_type_str.lower():
                    rules.append("LIBRARY/SDK DETECTED: Assume public classes/functions are EXTERNAL APIs (Not orphans).")
                elif "cli" in p_type_str.lower():
                    rules.append("CLI TOOL STRICT MODE: The ONLY public entry points are functions decorated as commands (e.g. @click.command).")
                    rules.append("ANY other public function that is unused by commands is DEAD CODE (TRUE ORPHAN). Do not assume external usage.")
                elif "microservice" in p_type_str.lower() or "api" in p_type_str.lower():
                    rules.append("WEB SERVICE DETECTED: Controller endpoints / Route handlers are entry points.")
                    rules.append("Service layer methods not called by controllers or other services ARE orphans.")
                else:
                    rules.append("APPLICATION DETECTED: explicit entry points (main) required.")

                # 2. Framework Rules
                if "django" in fw_str.lower() or "flask" in fw_str.lower() or "fastapi" in fw_str.lower():
                    rules.append(f"{fw_str.upper()} DETECTED: Views/Models/Serializers are often implicitly used.")
                
                # 3. Architecture Rules
                if "clean" in arch_str.lower():
                    rules.append("CLEAN ARCHITECTURE: Domain entities and use-cases might be defined but awaiting implementation.")
                    
                project_rules = "\n".join([f"- {r}" for r in rules])
                
            except Exception as e:
                logger.warning("context_extraction_failed", error=str(e))
                context_str = f"Context Error: {str(e)}"

        findings_text = ""
        for idx, (f_path, finding) in enumerate(batch):
            findings_text += (
                f"**Finding {idx}:**\n"
                f"  - File: {f_path}\n"
                f"  - Type: {finding.orphan_type}\n"
                f"  - Name: `{finding.name}`\n"
                f"  - Code:\n```\n{finding.code_snippet}\n```\n"
                f"  - Reason: {finding.reason}\n\n"
            )
            
        prompt = f"""You are an expert code analyzer.
        
        # PROJECT CONTEXT
        {context_str}
        
        # ANALYSIS RULES (Based on Project Type)
        {project_rules}
        
        TIMEFRAME: Analyze these {len(batch)} potential orphan code findings.
        
        # FINDINGS
        {findings_text}
        
        # INSTRUCTIONS
        For each finding, determine if it is a TRUE ORPHAN or FALSE POSITIVE.
        
        Reflexion:
        1. Review the PROJECT CONTEXT and ANALYSIS RULES above.
        2. Check if the finding matches the "False Positive" criteria for this specific project type.
        3. If it violates the strict rules (e.g. unused public function in a CLI), mark as TRUE ORPHAN (is_true_orphan=true).
        
        Return JSON with exactly {len(batch)} decisions decision objects.
        
        ```json
        {{
            "decisions": [ ... ]
        }}
        ```
        """
        return prompt

    async def filter_findings(
        self,
        findings: List[OrphanFinding],
        code_file: CodeFile,
        language: str = "python",
    ) -> List[OrphanFinding]:
        """
        Filter orphan findings using LLM intelligence.

        Args:
            findings: Raw AST findings (may contain false positives)
            code_file: Full code context
            language: Programming language (python, javascript, go, etc.)

        Returns:
            Filtered findings (only TRUE orphans)
        """
        if not findings:
            logger.info("no_findings_to_filter")
            return []

        start_time = time.perf_counter()

        logger.info(
            "llm_filter_started",
            total_findings=len(findings),
            language=language,
            file_path=code_file.path,
        )

        # Batch findings for efficiency
        batches = self._batch_findings(findings)

        true_orphans: List[OrphanFinding] = []
        total_decisions = 0
        false_positives_filtered = 0

        for batch_idx, batch in enumerate(batches):
            logger.debug(
                "processing_batch",
                batch_idx=batch_idx + 1,
                total_batches=len(batches),
                batch_size=len(batch),
            )

            try:
                # Filter batch using LLM
                filtered_batch = await self._filter_batch(
                    batch, code_file, language
                )

                true_orphans.extend(filtered_batch)
                total_decisions += len(batch)
                false_positives_filtered += len(batch) - len(filtered_batch)

            except Exception as e:
                logger.error(
                    "llm_batch_filter_failed",
                    batch_idx=batch_idx,
                    error=str(e),
                    error_type=type(e).__name__,
                    fallback="returning all batch findings (conservative)",
                )
                # Conservative fallback: include all findings from failed batch
                true_orphans.extend(batch)
                total_decisions += len(batch)

        duration = time.perf_counter() - start_time
        false_positive_rate = (false_positives_filtered / total_decisions * 100) if total_decisions > 0 else 0

        logger.info(
            "llm_filter_completed",
            original_findings=len(findings),
            true_orphans=len(true_orphans),
            false_positives_filtered=false_positives_filtered,
            false_positive_rate=f"{false_positive_rate:.1f}%",
            duration=f"{duration:.2f}s",
        )

        return true_orphans

    async def _filter_batch(
        self,
        batch: List[OrphanFinding],
        code_file: CodeFile,
        language: str,
    ) -> List[OrphanFinding]:
        """
        Filter a batch of findings using LLM.

        Args:
            batch: Batch of findings to filter
            code_file: Code file context
            language: Programming language

        Returns:
            Filtered findings (TRUE orphans only)
        """
        # Build prompt
        prompt = self._build_filter_prompt(batch, code_file, language)

        # Call LLM with retry logic
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._call_llm(
                    code=code_file.content,
                    prompt=prompt,
                    language=language,
                )

                # Parse LLM decisions
                decisions = self._parse_llm_response(response.content, len(batch))

                # Filter based on LLM decisions
                true_orphans = [
                    finding
                    for finding, decision in zip(batch, decisions)
                    if decision.is_true_orphan
                ]

                # Log filtering stats
                filtered_count = len(batch) - len(true_orphans)
                logger.debug(
                    "batch_filtered",
                    total=len(batch),
                    true_orphans=len(true_orphans),
                    filtered=filtered_count,
                )

                return true_orphans

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(
                        "llm_call_failed_retrying",
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        error=str(e),
                    )
                    await self._backoff(attempt)
                else:
                    # Max retries exceeded, re-raise
                    raise

        # Should never reach here, but satisfy type checker
        return batch

    async def _call_llm(
        self,
        code: str,
        prompt: str,
        language: str,
    ) -> LlmResponse:
        """
        Call LLM for analysis.

        Args:
            code: Source code
            prompt: Analysis prompt
            language: Programming language

        Returns:
            LLM response
        """
        # Build system prompt for code analysis
        system_prompt = f"""You are an expert {language} code analyzer specializing in orphan code detection.
Your task is to analyze code files and identify true orphan code (unused/unreferenced code) while filtering out false positives.

You have deep understanding of:
- Programming language patterns and idioms
- Framework conventions and lifecycle methods
- Serialization patterns
- Public API exports and re-exports
- Abstract classes, interfaces, and protocols"""

        # Build user message with code context and analysis request
        user_message = f"""# CODE TO ANALYZE

```{language}
{code}
```

{prompt}"""

        request = LlmRequest(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=3000,
            temperature=0.0,  # Deterministic for consistency
        )

        response = await self.llm.send_async(request)

        return response

    def _build_filter_prompt(
        self,
        findings: List[OrphanFinding],
        code_file: CodeFile,
        language: str,
    ) -> str:
        """
        Build intelligent prompt for LLM filtering.

        Args:
            findings: Findings to analyze
            code_file: Code file context
            language: Programming language

        Returns:
            Formatted prompt
        """
        # Get language-specific hints
        hints = self.LANGUAGE_HINTS.get(language.lower(), {})

        # Format findings for LLM
        findings_text = self._format_findings_for_llm(findings)

        # Build comprehensive prompt
        prompt = f"""You are an expert code analyzer. Analyze this {language} code for orphan code detection.

# CODE FILE: {code_file.path}

The code has already been scanned by an AST-based analyzer. Below are POTENTIAL orphan code findings.
Your job is to determine which are TRUE ORPHANS vs. FALSE POSITIVES.

# POTENTIAL ORPHAN CODE FINDINGS

{findings_text}

# YOUR TASK

For EACH finding above, determine if it's a **TRUE ORPHAN** or **FALSE POSITIVE**.

## Common FALSE POSITIVES (DO NOT report these as orphans):

### Universal Patterns (All Languages)
1. **Property/Getter methods** - Accessed as attributes, not called as functions
2. **Abstract/Interface methods** - Contract definitions, implemented by subclasses
3. **Public API exports** - Re-exported in index/init files for external use
4. **Serialization methods** - Used by frameworks (to_json, from_json, toJSON, etc.)
5. **Framework lifecycle methods** - Called by frameworks via reflection/decorators
6. **Test fixtures** - Used by test frameworks
7. **Enum helper methods** - Utility methods on enum types

### {language.upper()}-Specific Patterns
"""

        # Add language-specific hints
        if "decorators" in hints:
            prompt += f"\n**Decorators:** {', '.join(hints['decorators'])}"
            prompt += "\n  → Methods with these decorators are often framework-managed"

        if "protocols" in hints or "interfaces" in hints:
            protocols = hints.get("protocols") or hints.get("interfaces")
            prompt += f"\n**Protocols/Interfaces:** {', '.join(protocols)}"
            prompt += "\n  → Abstract contracts, not meant to be called directly"

        if "special_files" in hints:
            prompt += f"\n**Special Files:** {', '.join(hints['special_files'])}"
            prompt += "\n  → Imports in these files are often re-exports (public API)"

        if "serialization" in hints:
            prompt += f"\n**Serialization Methods:** {', '.join(hints['serialization'])}"
            prompt += "\n  → Called by serialization frameworks, not directly in code"

        # Continue prompt
        prompt += """

## TRUE ORPHANS (DO report these):
1. **Truly unused imports** - Imported but never referenced anywhere
2. **Unreferenced functions** - Defined but never called (and not in exceptions above)
3. **Unreferenced classes** - Defined but never instantiated (and not in exceptions above)
4. **Dead code** - Unreachable after return/raise/break statements

## ANALYSIS GUIDELINES

For each finding:
1. **Check the code context** - Is it part of a framework pattern?
2. **Check decorators/attributes** - Does it have special markers?
3. **Check file type** - Is it in __init__.py or index.js (public API)?
4. **Check naming** - Does the name suggest it's part of a protocol (to_json, serialize, etc.)?
5. **Apply language-specific knowledge** - Use your understanding of {language} idioms

## OUTPUT FORMAT (JSON)

Return a JSON object with your analysis for ALL {len(findings)} findings:

```json
{{
  "decisions": [
    {{
      "finding_id": 0,
      "is_true_orphan": false,
      "reasoning": "@property decorator detected. Properties are accessed as attributes (obj.name), not called as functions. FALSE POSITIVE.",
      "confidence": 0.95
    }},
    {{
      "finding_id": 1,
      "is_true_orphan": true,
      "reasoning": "Function 'calculate_tax' is defined but never called. No decorators, not exported, not abstract. TRUE ORPHAN.",
      "confidence": 0.9
    }},
    ...
  ]
}}
```

**IMPORTANT:**
- Analyze ALL {len(findings)} findings
- Return EXACTLY {len(findings)} decisions
- Use valid JSON format
- Be conservative: if unsure, mark as false (is_true_orphan: false)
- Provide clear reasoning for each decision

Now analyze the findings and return the JSON.
"""

        return prompt

    def _format_findings_for_llm(
        self,
        findings: List[OrphanFinding],
    ) -> str:
        """
        Format findings for LLM prompt.

        Args:
            findings: Findings to format

        Returns:
            Formatted findings text
        """
        formatted_lines = []

        for idx, finding in enumerate(findings):
            formatted_lines.append(
                f"**Finding {idx}:**\n"
                f"  - Type: {finding.orphan_type}\n"
                f"  - Name: `{finding.name}`\n"
                f"  - Line: {finding.line_number}\n"
                f"  - Code: `{finding.code_snippet}`\n"
                f"  - Reason: {finding.reason}\n"
            )

        return "\n".join(formatted_lines)

    def _parse_llm_response(
        self,
        llm_response: str,
        expected_count: int,
    ) -> List[FilterDecision]:
        """
        Parse LLM JSON response into FilterDecision objects.

        Args:
            llm_response: Raw LLM response
            expected_count: Expected number of decisions

        Returns:
            List of FilterDecision objects

        Raises:
            ValueError: If parsing fails or count mismatch
        """
        try:
            if not llm_response or not llm_response.strip():
                raise ValueError("Empty response from LLM")

            # Extract JSON from response (LLM may wrap in markdown code blocks)
            json_str = self._extract_json(llm_response)
            if not json_str:
                raise ValueError("No JSON found in response")

            # Parse JSON
            data = json.loads(json_str)

            # Extract decisions
            decisions_data = data.get("decisions", [])

            # Validate count
            if len(decisions_data) != expected_count:
                raise ValueError(
                    f"Expected {expected_count} decisions, got {len(decisions_data)}"
                )

            # Convert to FilterDecision objects
            decisions = []
            for d in decisions_data:
                decision = FilterDecision(
                    finding_id=d.get("finding_id", 0),
                    is_true_orphan=d.get("is_true_orphan", False),
                    reasoning=d.get("reasoning", "No reasoning provided"),
                    confidence=d.get("confidence", 1.0),
                )
                decisions.append(decision)

            return decisions

        except Exception as e:
            logger.warning(
                "llm_response_parse_failed_using_fallback",
                error=str(e),
                error_type=type(e).__name__,
                response_preview=llm_response[:200] if llm_response else "empty",
            )

            # Conservative fallback: mark all as false (not orphans)
            # This prevents false positives in case of parse error
            return [
                FilterDecision(
                    finding_id=i,
                    is_true_orphan=False,  # Conservative: assume false positive
                    reasoning=f"LLM parse error: {str(e)}. Conservative fallback.",
                    confidence=0.0,
                )
                for i in range(expected_count)
            ]

    def _extract_json(self, text: str) -> str:
        """
        Extract JSON from LLM response.

        LLM may wrap JSON in markdown code blocks:
        ```json
        { ... }
        ```

        Args:
            text: Raw LLM response

        Returns:
            Extracted JSON string
        """
        # Remove markdown code blocks
        text = text.strip()

        # Check for markdown wrapper
        if text.startswith("```"):
            # Find first { and last }
            json_start = text.find("{")
            json_end = text.rfind("}") + 1

            if json_start != -1 and json_end > json_start:
                return text[json_start:json_end]

        # Try to find JSON object directly
        json_start = text.find("{")
        json_end = text.rfind("}") + 1

        if json_start != -1 and json_end > json_start:
            return text[json_start:json_end]

        # Return empty string if no JSON found
        return ""

    def _batch_findings(
        self,
        findings: List[OrphanFinding],
    ) -> List[List[OrphanFinding]]:
        """
        Split findings into batches for efficient processing.

        Args:
            findings: All findings

        Returns:
            List of batches
        """
        batches = []
        for i in range(0, len(findings), self.batch_size):
            batches.append(findings[i:i + self.batch_size])

        logger.debug(
            "findings_batched",
            total_findings=len(findings),
            batch_size=self.batch_size,
            total_batches=len(batches),
        )

        return batches

    async def _backoff(self, attempt: int) -> None:
        """
        Exponential backoff for retries.

        Args:
            attempt: Current attempt number (0-indexed)
        """
        import asyncio

        # Exponential backoff: 1s, 2s, 4s, ...
        delay = 2 ** attempt

        logger.debug(
            "retry_backoff",
            attempt=attempt + 1,
            delay=f"{delay}s",
        )

        await asyncio.sleep(delay)
