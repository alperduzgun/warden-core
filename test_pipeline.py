#!/usr/bin/env python
"""Test script to check pipeline execution."""

import asyncio
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_pipeline():
    """Test pipeline execution with all phases enabled."""

    from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
    from warden.pipeline.domain.models import PipelineConfig
    from warden.validation.domain.frame import CodeFile
    from warden.validation.frames import SecurityFrame, OrphanFrame

    # Create sample code file
    code_file = CodeFile(
        path="/tmp/test.py",
        content="""
import os

DATABASE_PASSWORD = "admin123"

def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return query
""",
        language="python"
    )

    # Create config with all phases enabled
    config = PipelineConfig(
        enable_pre_analysis=True,
        enable_analysis=True,
        enable_classification=True,
        enable_validation=True,
        enable_fortification=True,
        enable_cleaning=True,
        fail_fast=False,
        timeout=300,
        frame_timeout=120,
    )

    # Define progress callback
    def progress_callback(event: str, data: dict):
        print(f"[PROGRESS] {event}: {data}")

    # Create orchestrator with frames
    orchestrator = PhaseOrchestrator(
        frames=[SecurityFrame(), OrphanFrame()],
        config=config,
        progress_callback=progress_callback,
        project_root=Path.cwd()
    )

    print("Starting pipeline execution with all phases enabled...")
    print(f"Config: {config.__dict__}")

    try:
        # Execute pipeline
        result, context = await orchestrator.execute([code_file])

        print("\n=== Pipeline Execution Complete ===")
        print(f"Pipeline ID: {context.pipeline_id}")
        print(f"Summary: {context.get_summary()}")

        # Check which phases ran
        if hasattr(context, 'phase_results'):
            print("\n=== Phases Executed ===")
            for phase, result in context.phase_results.items():
                print(f"{phase}: {result}")

        if hasattr(context, 'errors') and context.errors:
            print("\n=== Errors ===")
            for error in context.errors:
                print(f"ERROR: {error}")

        return True

    except Exception as e:
        print(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_pipeline())
    if success:
        print("\n✅ Pipeline test completed successfully")
    else:
        print("\n❌ Pipeline test failed")