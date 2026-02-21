"""
Batch Processor Module

Batch LLM processing for security findings verification.
"""

import json
from typing import Any

from warden.llm.types import LlmRequest

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


async def batch_verify_security_findings(
    findings_map: dict[str, list[Any]], code_files: list[Any], llm_service: Any
) -> dict[str, list[Any]]:
    """
    Batch LLM verification of security findings.

    Reduces LLM calls from N findings to N/batch_size calls.

    Args:
        findings_map: Dict of file_path -> findings
        code_files: List of code files for context
        llm_service: LLM service for verification

    Returns:
        Updated findings_map with LLM-verified findings
    """
    # Flatten findings
    all_findings_with_context = []
    for file_path, findings in findings_map.items():
        code_file = next((f for f in code_files if f.path == file_path), None)
        for finding in findings:
            all_findings_with_context.append({"finding": finding, "file_path": file_path, "code_file": code_file})

    if not all_findings_with_context:
        return findings_map

    # Smart Batching (token-aware)
    MAX_SAFE_TOKENS = 6000
    BATCH_SIZE = 10
    batches = _smart_batch_findings(all_findings_with_context, BATCH_SIZE, MAX_SAFE_TOKENS)

    logger.info("security_batch_llm_verification", total_findings=len(all_findings_with_context), batches=len(batches))

    # Process each batch
    verified_findings_map: dict[str, list[Any]] = {path: [] for path in findings_map}

    for i, batch in enumerate(batches):
        try:
            logger.debug(f"Processing security batch {i + 1}/{len(batches)}")
            verified_batch = await _verify_security_batch(batch, code_files, llm_service)

            # Map back to files
            for item in verified_batch:
                file_path = item["file_path"]
                verified_findings_map[file_path].append(item["finding"])

        except Exception as e:
            logger.error("security_batch_verification_failed", batch=i, error=str(e))
            # Fallback: keep original findings
            for item in batch:
                file_path = item["file_path"]
                verified_findings_map[file_path].append(item["finding"])

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
    batch: list[dict[str, Any]], code_files: list[Any], llm_service: Any
) -> list[dict[str, Any]]:
    """
    Single LLM call for multiple security findings.

    Args:
        batch: List of {finding, file_path, code_file}
        code_files: All code files for context
        llm_service: LLM service

    Returns:
        List of verified findings with same structure
    """
    # Build batch prompt
    prompt_parts = ["Review these security findings and verify if they are true vulnerabilities:\n\n"]

    for i, item in enumerate(batch):
        finding = item["finding"]
        code_file = item["code_file"]

        prompt_parts.append(f"Finding #{i + 1}:")
        prompt_parts.append(f"File: {item['file_path']}")
        prompt_parts.append(f"Severity: {finding.severity}")
        prompt_parts.append(f"Message: {finding.message}")
        if finding.code:
            prompt_parts.append(f"Code:\n```\n{finding.code[:200]}\n```")
        if code_file:
            # Add limited context
            prompt_parts.append(f"File Context (first 500 chars):\n```\n{code_file.content[:500]}\n```")
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
            system_prompt="You are a senior security engineer. Verify if these security findings are true vulnerabilities or false positives."
        )
        response = await llm_service.send_async(request)

        # Parse LLM response and filter false positives
        # LlmResponse is a Pydantic model — use attribute access, not .get()
        if not response.success:
            logger.warning(
                "security_batch_llm_not_successful",
                error=response.error_message,
                fallback="keeping_all_findings"
            )
            return batch

        try:
            content = response.content or ""
            parsed = json.loads(content)

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
