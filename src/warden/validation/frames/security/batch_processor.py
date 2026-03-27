"""
Batch Processor Module

Batch LLM processing for security findings verification.
"""

import asyncio
import json
from typing import Any

from warden.llm.types import LlmRequest
from warden.shared.chunking import ChunkingConfig, ChunkingService

_SECURITY_CHUNK_CONFIG = ChunkingConfig(max_chunk_tokens=600, max_chunks_per_file=3)

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


def _prepare_code_for_batch(code_file: Any) -> str:
    """Return a compact code representation for batch LLM verification.

    For large files, returns only the first chunk's content (which contains
    the most relevant declarations).  For small files, returns the raw content
    capped at 500 chars as before.
    """
    try:
        svc = ChunkingService()
        if svc.should_chunk(code_file, _SECURITY_CHUNK_CONFIG):
            chunks = svc.chunk(code_file, ast_cache=None, config=_SECURITY_CHUNK_CONFIG)
            if chunks:
                header = svc.build_prompt_header(chunks[0])
                return (header + chunks[0].content)[:600]
    except Exception:
        pass
    return (code_file.content or "")[:500]


async def batch_verify_security_findings(
    findings_map: dict[str, list[Any]],
    code_files: list[Any],
    llm_service: Any,
    semantic_context: str = "",
) -> dict[str, list[Any]]:
    """
    Batch LLM verification of security findings.

    Reduces LLM calls from N findings to N/batch_size calls.

    Args:
        findings_map: Dict of file_path -> findings
        code_files: List of code files for context
        llm_service: LLM service for verification
        semantic_context: Optional project-level context for LLM enrichment

    Returns:
        Updated findings_map with LLM-verified findings
    """
    # Split: deterministic findings (taint, pattern) skip LLM verification.
    # Only LLM-sourced or unattributed findings need a second opinion.
    _DETERMINISTIC_SOURCES = {"taint", "pattern", "ast", "deterministic"}
    deterministic_by_path: dict[str, list[Any]] = {path: [] for path in findings_map}
    all_findings_with_context = []
    for file_path, findings in findings_map.items():
        code_file = next((f for f in code_files if f.path == file_path), None)
        for finding in findings:
            ds = getattr(finding, "detection_source", None) or ""
            if ds in _DETERMINISTIC_SOURCES:
                deterministic_by_path[file_path].append(finding)
            else:
                all_findings_with_context.append({"finding": finding, "file_path": file_path, "code_file": code_file})

    if not all_findings_with_context:
        # Merge deterministic back and return
        for path in findings_map:
            findings_map[path] = deterministic_by_path.get(path, [])
        return findings_map

    # Smart Batching (token-aware)
    MAX_SAFE_TOKENS = 6000
    BATCH_SIZE = 10
    batches = _smart_batch_findings(all_findings_with_context, BATCH_SIZE, MAX_SAFE_TOKENS)

    logger.info("security_batch_llm_verification", total_findings=len(all_findings_with_context), batches=len(batches))

    # Process all batches in parallel — each batch is an independent LLM call (closes #304)
    _BATCH_TIMEOUT_S = 320.0  # complete_async(300s) + rate limiter headroom(10s) + buffer

    async def _run_batch(i: int, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            logger.debug("processing_security_batch", index=i + 1, total=len(batches))
            return await asyncio.wait_for(
                _verify_security_batch(batch, code_files, llm_service, semantic_context),
                timeout=_BATCH_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("security_batch_verification_timeout", batch=i)
            return batch  # conservative fallback: keep original items
        except Exception as e:
            logger.error("security_batch_verification_failed", batch=i, error=str(e))
            return batch  # conservative fallback: keep original items

    batch_results = await asyncio.gather(*[_run_batch(i, b) for i, b in enumerate(batches)])

    verified_findings_map: dict[str, list[Any]] = {path: [] for path in findings_map}
    for verified_batch in batch_results:
        for item in verified_batch:
            verified_findings_map[item["file_path"]].append(item["finding"])

    # Merge deterministic findings back (they skipped LLM verification)
    for path, det_findings in deterministic_by_path.items():
        verified_findings_map[path] = det_findings + verified_findings_map.get(path, [])

    return verified_findings_map


def _smart_batch_findings(
    findings_with_context: list[dict[str, Any]], max_batch_size: int, max_tokens: int
) -> list[list[dict[str, Any]]]:
    """Token-aware batching for findings."""
    batches = []
    current_batch = []
    current_tokens = 0

    for item in findings_with_context:
        finding = item["finding"]
        # Estimate tokens: message + code snippet
        estimated_tokens = len(finding.message.split()) * 1.5
        if finding.code:
            estimated_tokens += len(finding.code.split()) * 1.5

        if current_tokens + estimated_tokens > max_tokens or len(current_batch) >= max_batch_size:
            if current_batch:
                batches.append(current_batch)
            current_batch = [item]
            current_tokens = estimated_tokens
        else:
            current_batch.append(item)
            current_tokens += estimated_tokens

    if current_batch:
        batches.append(current_batch)

    return batches


async def _verify_security_batch(
    batch: list[dict[str, Any]],
    code_files: list[Any],
    llm_service: Any,
    semantic_context: str = "",
) -> list[dict[str, Any]]:
    """
    Single LLM call for multiple security findings.

    Args:
        batch: List of {finding, file_path, code_file}
        code_files: All code files for context
        llm_service: LLM service
        semantic_context: Optional project-level context

    Returns:
        List of verified findings with same structure
    """
    # Build batch prompt
    prompt_parts = ["Review these security findings and verify if they are true vulnerabilities:\n\n"]

    # Inject project-level context (compact, max 300 chars)
    if semantic_context:
        prompt_parts.append(f"[PROJECT CONTEXT]:\n{semantic_context[:300]}\n\n")

    for i, item in enumerate(batch):
        finding = item["finding"]
        code_file = item["code_file"]

        prompt_parts.append(f"Finding #{i + 1}:")
        prompt_parts.append(f"File: {item['file_path']}")
        prompt_parts.append(f"Severity: {finding.severity}")
        prompt_parts.append(f"Message: {finding.message}")
        if code_file and finding.line_number:
            # Show ±20 lines around the flagged line so verifier sees full context
            lines = (code_file.content or "").splitlines()
            ln = finding.line_number - 1  # 0-indexed
            start = max(0, ln - 20)
            end = min(len(lines), ln + 21)
            numbered = [f"{start + j + 1}: {lines[start + j]}" for j in range(end - start)]
            prompt_parts.append(f"Code (lines {start + 1}–{end}):\n```\n" + "\n".join(numbered) + "\n```")
        elif finding.code:
            prompt_parts.append(f"Code:\n```\n{finding.code[:200]}\n```")
        if code_file and not finding.line_number:
            # Fallback: first-chunk context for findings without line numbers
            file_context = _prepare_code_for_batch(code_file)
            prompt_parts.append(f"File Context:\n```\n{file_context}\n```")
        prompt_parts.append("\n---\n")

    prompt_parts.append("""
Return JSON array with verification results:
[
  {"finding_id": 1, "is_valid": true/false, "confidence": "high/medium/low", "reason": "..."},
  ...
]
""")

    full_prompt = "\n".join(prompt_parts)

    # Single LLM call
    try:
        request = LlmRequest(
            user_message=full_prompt,
            system_prompt="You are a senior security engineer. Verify if these security findings are true vulnerabilities or false positives.",
            max_tokens=1024,  # 600 caused frequent truncation → malformed JSON → silent fallback
        )
        response = await llm_service.send_with_tools_async(request)

        # Parse LLM response and filter false positives
        # LlmResponse is a Pydantic model — use attribute access, not .get()
        if not response.success:
            logger.warning(
                "security_batch_llm_not_successful", error=response.error_message, fallback="keeping_all_findings"
            )
            return batch

        try:
            content = response.content or ""
            # Extract JSON from markdown fences if LLM wrapped the response
            if "```" in content:
                import re

                match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", content)
                if match:
                    content = match.group(1).strip()

            # Attempt to recover truncated JSON arrays (e.g. "[{...},{..." → "[{...}]")
            content = content.strip()
            if content.startswith("[") and not content.endswith("]"):
                # Find last complete object boundary and close the array
                last_brace = content.rfind("}")
                if last_brace > 0:
                    content = content[: last_brace + 1] + "]"
                    logger.debug("security_llm_json_recovery", action="truncated_array_closed")

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: try shared JSON parser with repair
                try:
                    from warden.shared.utils.json_parser import parse_json_from_llm
                    parsed = parse_json_from_llm(content)
                    logger.debug("security_llm_json_repaired", method="shared_parser")
                except Exception:
                    raise json.JSONDecodeError("All parse attempts failed", content, 0)

            if isinstance(parsed, list):
                # Build set of invalid finding IDs (1-based indexing from prompt)
                invalid_ids = {
                    item.get("finding_id")
                    for item in parsed
                    if isinstance(item, dict) and not item.get("is_valid", True)
                }

                if invalid_ids:
                    # Filter out invalid findings (0-based indexing in batch)
                    verified = [batch[i] for i in range(len(batch)) if (i + 1) not in invalid_ids]
                    logger.info(
                        "security_llm_filtered",
                        total=len(batch),
                        filtered=len(batch) - len(verified),
                        remaining=len(verified),
                    )
                    return verified

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(
                "security_llm_parse_failed", error=str(e), error_type=type(e).__name__, fallback="keeping_all_findings"
            )

        # Fallback: keep all findings if parsing fails or no invalid findings found
        return batch

    except Exception as e:
        logger.error("security_batch_llm_failed", error=str(e))
        return batch  # Fallback: keep all findings
