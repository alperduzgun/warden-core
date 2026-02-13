#!/usr/bin/env python3
"""
Demo script to showcase the centralized async error handler.

Shows before/after comparison and real-world usage examples.
"""

import asyncio
import structlog
from warden.shared.infrastructure.error_handler import (
    async_error_handler,
    ProviderUnavailableError,
    OperationTimeoutError,
)

logger = structlog.get_logger(__name__)


# === BEFORE: Repetitive try/except ===

async def fetch_data_before(source: str):
    """Old style - repetitive error handling."""
    try:
        if source == "broken":
            raise ConnectionError("Source unavailable")
        return {"data": f"from {source}"}
    except Exception as e:
        logger.error("fetch_failed", source=source, error=str(e))
        return {"data": "fallback"}


async def process_file_before(filepath: str):
    """Old style - repetitive error handling."""
    try:
        if filepath == "invalid":
            raise ValueError("Invalid file")
        return {"status": "processed", "file": filepath}
    except Exception as e:
        logger.error("process_failed", file=filepath, error=str(e))
        return None


# === AFTER: Using decorator ===

@async_error_handler(
    fallback_value={"data": "fallback"},
    log_level="error",
    context_keys=["source"],
    reraise=False
)
async def fetch_data_after(source: str):
    """New style - decorator handles errors."""
    if source == "broken":
        raise ConnectionError("Source unavailable")
    return {"data": f"from {source}"}


@async_error_handler(
    fallback_value=None,
    log_level="error",
    context_keys=["filepath"],
    reraise=False
)
async def process_file_after(filepath: str):
    """New style - decorator handles errors."""
    if filepath == "invalid":
        raise ValueError("Invalid file")
    return {"status": "processed", "file": filepath}


# === Real-world examples ===

@async_error_handler(
    fallback_value=lambda: {"provider": "offline", "status": "fallback"},
    log_level="warning",
    error_map={ConnectionError: ProviderUnavailableError},
    context_keys=["provider"],
    reraise=False
)
async def create_llm_client(provider: str):
    """Simulates LLM client creation with fallback."""
    if provider == "unreachable":
        raise ConnectionError("Cannot reach provider")
    return {"provider": provider, "status": "connected"}


@async_error_handler(
    fallback_value=None,
    log_level="error",
    error_map={asyncio.TimeoutError: OperationTimeoutError},
    context_keys=["frame_id", "file"],
    reraise=False
)
async def execute_validation_frame(frame_id: str, file: str):
    """Simulates frame execution with timeout handling."""
    if frame_id == "slow":
        await asyncio.sleep(5)  # Simulate slow operation
        raise asyncio.TimeoutError("Operation timed out")
    return {"frame_id": frame_id, "file": file, "status": "passed"}


async def main():
    """Run demos."""
    print("=" * 60)
    print("Centralized Async Error Handler Demo")
    print("=" * 60)

    # Demo 1: Before/After comparison
    print("\n1. Before/After Comparison")
    print("-" * 60)

    print("\nBEFORE (repetitive try/except):")
    result = await fetch_data_before("broken")
    print(f"  Result: {result}")

    print("\nAFTER (using decorator):")
    result = await fetch_data_after("broken")
    print(f"  Result: {result}")

    # Demo 2: Success path unchanged
    print("\n2. Success Path Unchanged")
    print("-" * 60)

    print("\nSuccess case:")
    result = await fetch_data_after("api")
    print(f"  Result: {result}")

    # Demo 3: LLM client creation
    print("\n3. LLM Client Creation with Fallback")
    print("-" * 60)

    print("\nCreating OpenAI client (success):")
    result = await create_llm_client("openai")
    print(f"  Result: {result}")

    print("\nCreating unreachable provider (fallback):")
    result = await create_llm_client("unreachable")
    print(f"  Result: {result}")

    # Demo 4: Frame execution
    print("\n4. Frame Execution with Error Handling")
    print("-" * 60)

    print("\nExecuting security frame (success):")
    result = await execute_validation_frame("security", "test.py")
    print(f"  Result: {result}")

    print("\nExecuting slow frame (timeout):")
    result = await execute_validation_frame("slow", "test.py")
    print(f"  Result: {result}")

    # Demo 5: Multiple errors
    print("\n5. Batch Operations with Mixed Results")
    print("-" * 60)

    sources = ["api1", "broken", "api2", "broken"]
    print(f"\nFetching from sources: {sources}")

    tasks = [fetch_data_after(s) for s in sources]
    results = await asyncio.gather(*tasks)

    for source, result in zip(sources, results):
        status = "✓" if result["data"] != "fallback" else "✗"
        print(f"  {status} {source}: {result}")

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nKey Benefits:")
    print("  ✓ DRY: No repetitive try/except")
    print("  ✓ Consistent: Same logging pattern everywhere")
    print("  ✓ Flexible: Configurable per use-case")
    print("  ✓ Safe: Maintains existing behavior")
    print("  ✓ Testable: Decorator tested once, works everywhere")


if __name__ == "__main__":
    asyncio.run(main())
