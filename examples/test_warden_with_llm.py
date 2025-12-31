"""
Test Warden with LLM on vulnerable code (dogfooding).

This script runs the complete 6-phase pipeline with LLM enhancements.
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
from warden.validation.domain.frame import CodeFile
from warden.llm.factory import create_client


async def run_warden_with_llm():
    """Run Warden pipeline with LLM on vulnerable code."""

    print("=" * 80)
    print("WARDEN DOGFOODING TEST - LLM Enhanced Pipeline")
    print("=" * 80)

    # Load the vulnerable code
    vulnerable_file = Path(__file__).parent / "vulnerable_code.py"
    with open(vulnerable_file, "r") as f:
        code_content = f.read()

    # Create CodeFile object
    code_file = CodeFile(
        path=str(vulnerable_file),
        content=code_content,
        language="python",
    )

    # Initialize LLM client (will use environment variables)
    # Note: Make sure AZURE_OPENAI_API_KEY and related env vars are set
    llm_client = None

    # Check if LLM credentials are available
    if os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"):
        try:
            llm_client = create_client()
            print("✅ LLM Client initialized successfully")
        except Exception as e:
            print(f"⚠️ LLM Client initialization failed: {e}")
            print("Falling back to rule-based analysis")
    else:
        print("⚠️ No LLM API keys found in environment")
        print("Set AZURE_OPENAI_API_KEY or OPENAI_API_KEY for LLM features")

    # Configuration for all phases
    config = {
        "enable_pre_analysis": True,
        "enable_analysis": True,
        "enable_classification": True,
        "enable_validation": True,
        "enable_fortification": True,
        "enable_cleaning": True,
        "pre_analysis_config": {
            "use_llm": llm_client is not None,
            "llm_threshold": 0.7,
        },
        "analysis_config": {
            "use_llm": llm_client is not None,
        },
        "classification_config": {
            "use_llm": llm_client is not None,
        },
        "fortification_config": {
            "use_llm": llm_client is not None,
        },
        "cleaning_config": {
            "use_llm": llm_client is not None,
        },
    }

    # Progress callback
    def progress_callback(event: str, data: dict):
        """Print progress updates."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if event == "phase_started":
            print(f"\n[{timestamp}] 🚀 Starting {data.get('phase')}...")
        elif event == "phase_completed":
            print(f"[{timestamp}] ✅ Completed {data.get('phase')}")
        elif event == "frame_started":
            print(f"[{timestamp}]   - Running {data.get('frame_name')}...")
        elif event == "frame_completed":
            status = "✅" if data.get('frame_status') == 'completed' else "❌"
            print(f"[{timestamp}]   {status} {data.get('frame_name')}: {data.get('issues_found', 0)} issues")

    # Initialize orchestrator
    orchestrator = PhaseOrchestrator(
        project_root=Path(__file__).parent,
        config=config,
        progress_callback=progress_callback,
    )

    print(f"\nAnalyzing: {vulnerable_file}")
    print("-" * 80)

    # Execute pipeline
    try:
        context = await orchestrator.execute_pipeline_async([code_file])

        # Print results
        print("\n" + "=" * 80)
        print("PIPELINE RESULTS")
        print("=" * 80)

        # Summary
        print("\n📊 SUMMARY:")
        print(context.get_summary())

        # Security Issues Found
        if context.findings:
            print(f"\n🔍 SECURITY ISSUES FOUND: {len(context.findings)}")
            for i, finding in enumerate(context.findings[:5], 1):
                print(f"  {i}. {finding.get('type', 'Unknown')}: {finding.get('message', 'No message')}")
                print(f"     Severity: {finding.get('severity', 'unknown')}")
                print(f"     Line: {finding.get('line_number', 'unknown')}")

        # Fortifications (Security Fixes)
        if context.fortifications:
            print(f"\n🛡️ SECURITY FIXES SUGGESTED: {len(context.fortifications)}")
            for i, fort in enumerate(context.fortifications[:3], 1):
                print(f"  {i}. {fort.get('title', 'Security Fix')}")
                print(f"     {fort.get('description', 'No description')}")

        # Cleaning Suggestions
        if context.cleaning_suggestions:
            print(f"\n🧹 CODE IMPROVEMENTS SUGGESTED: {len(context.cleaning_suggestions)}")
            for i, clean in enumerate(context.cleaning_suggestions[:3], 1):
                print(f"  {i}. {clean.get('title', 'Improvement')}")
                print(f"     Type: {clean.get('type', 'general')}")
                print(f"     Impact: {clean.get('impact', 'unknown')}")

        # Quality Score
        if context.quality_score_before > 0:
            print(f"\n📈 QUALITY SCORE:")
            print(f"  Before: {context.quality_score_before:.1f}/10")
            print(f"  After (if applied): {context.quality_score_after:.1f}/10")
            print(f"  Improvement: +{context.quality_score_after - context.quality_score_before:.1f}")

        # LLM Usage
        if context.llm_history:
            print(f"\n🤖 LLM INTERACTIONS: {len(context.llm_history)}")
            for phase in ["PRE_ANALYSIS", "ANALYSIS", "CLASSIFICATION", "FORTIFICATION", "CLEANING"]:
                phase_count = sum(1 for h in context.llm_history if h["phase"] == phase)
                if phase_count > 0:
                    print(f"  - {phase}: {phase_count} calls")

        print("\n" + "=" * 80)
        print("✅ DOGFOODING TEST COMPLETED SUCCESSFULLY!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Pipeline execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    # Run the async main function
    exit_code = asyncio.run(run_warden_with_llm())
    sys.exit(exit_code)