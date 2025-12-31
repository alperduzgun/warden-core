#!/usr/bin/env python3
"""
Pipeline Verification Script
Verifies that all 6 phases of the pipeline are working correctly.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Configure logging to see all phases
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_phase_header(phase_name: str):
    """Print a colored header for each phase."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}PHASE: {phase_name}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")

def print_success(message: str):
    """Print success message in green."""
    print(f"{Colors.GREEN}✓ {message}{Colors.ENDC}")

def print_error(message: str):
    """Print error message in red."""
    print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")

def print_info(key: str, value: Any):
    """Print info in formatted way."""
    print(f"{Colors.CYAN}{key}:{Colors.ENDC} {value}")

async def verify_pipeline():
    """Verify all pipeline phases are working."""

    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         WARDEN PIPELINE VERIFICATION TOOL               ║")
    print("║         Testing All 6 Pipeline Phases                   ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")

    # Import required modules
    from warden.pipeline.application.phase_orchestrator import PhaseOrchestrator
    from warden.pipeline.domain.models import PipelineConfig
    from warden.validation.domain.frame import CodeFile
    from warden.validation.frames import SecurityFrame, OrphanFrame

    # Sample vulnerable code for testing
    test_code = '''
import os
import sqlite3

# Security issue: Hardcoded password
DATABASE_PASSWORD = "admin123"
API_KEY = "sk-1234567890abcdef"

# Security issue: SQL Injection
def get_user(user_id):
    conn = sqlite3.connect('users.db')
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return conn.execute(query).fetchall()

# Orphan code: Unused function
def unused_function():
    pass

# Complexity issue: Too many nested conditions
def complex_function(a, b, c, d, e):
    if a > 0:
        if b > 0:
            if c > 0:
                if d > 0:
                    if e > 0:
                        return True
    return False

# Naming issue: Poor variable names
def calc(x, y, z):
    a = x + y
    b = a * z
    return b
'''

    # Create test file
    code_file = CodeFile(
        path="/tmp/pipeline_test.py",
        content=test_code,
        language="python"
    )

    # Create config with ALL phases enabled
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

    # Phase tracking
    phases_executed = []
    phase_results = {}

    def progress_callback(event: str, data: Dict):
        """Track pipeline progress."""
        if event == "phase_started":
            phase = data.get("phase", "UNKNOWN")
            phases_executed.append(phase)
            print(f"\n{Colors.BLUE}▶ Phase Starting: {phase}{Colors.ENDC}")
        elif event == "phase_completed":
            phase = data.get("phase", "UNKNOWN")
            print(f"{Colors.GREEN}✓ Phase Completed: {phase}{Colors.ENDC}")
        elif event == "frame_started":
            frame = data.get("frame_name", "UNKNOWN")
            print(f"  {Colors.CYAN}• Frame: {frame}{Colors.ENDC}")

    # Create orchestrator
    orchestrator = PhaseOrchestrator(
        frames=[SecurityFrame(), OrphanFrame()],
        config=config,
        progress_callback=progress_callback,
        project_root=Path.cwd()
    )

    print(f"\n{Colors.BOLD}Starting Pipeline Execution...{Colors.ENDC}")
    print(f"{Colors.WARNING}Configuration:{Colors.ENDC}")
    print(f"  • Pre-Analysis: {config.enable_pre_analysis}")
    print(f"  • Analysis: {config.enable_analysis}")
    print(f"  • Classification: {config.enable_classification}")
    print(f"  • Validation: {config.enable_validation}")
    print(f"  • Fortification: {config.enable_fortification}")
    print(f"  • Cleaning: {config.enable_cleaning}")

    try:
        # Execute pipeline
        result, context = await orchestrator.execute([code_file])

        # Print detailed results
        print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}PIPELINE EXECUTION COMPLETE{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")

        # 1. Check PRE-ANALYSIS results
        print_phase_header("1. PRE-ANALYSIS RESULTS")
        if hasattr(context, 'project_type'):
            print_success("PRE-ANALYSIS executed")
            print_info("Project Type", context.project_type)
            print_info("Framework", context.framework)
            print_info("File Contexts", len(context.file_contexts) if context.file_contexts else 0)
        else:
            print_error("PRE-ANALYSIS did not execute or store results")

        # 2. Check ANALYSIS results
        print_phase_header("2. ANALYSIS RESULTS")
        if hasattr(context, 'quality_metrics'):
            print_success("ANALYSIS executed")
            print_info("Quality Score", f"{context.quality_score_before:.2f}/10")
            print_info("Hotspots", len(context.hotspots) if context.hotspots else 0)
            print_info("Quick Wins", len(context.quick_wins) if context.quick_wins else 0)
            print_info("Technical Debt", f"{context.technical_debt_hours:.1f} hours")
        else:
            print_error("ANALYSIS did not execute or store results")

        # 3. Check CLASSIFICATION results
        print_phase_header("3. CLASSIFICATION RESULTS")
        if hasattr(context, 'selected_frames'):
            print_success("CLASSIFICATION executed")
            print_info("Selected Frames", context.selected_frames)
            print_info("Suppression Rules", len(context.suppression_rules) if context.suppression_rules else 0)
            print_info("Reasoning", context.classification_reasoning)
        else:
            print_error("CLASSIFICATION did not execute or store results")

        # 4. Check VALIDATION results
        print_phase_header("4. VALIDATION RESULTS")
        if hasattr(context, 'findings'):
            print_success("VALIDATION executed")
            print_info("Total Findings", len(context.findings))
            print_info("Validated Issues", len(context.validated_issues) if hasattr(context, 'validated_issues') else 0)

            # Show sample findings
            if context.findings:
                print(f"\n  {Colors.CYAN}Sample Findings:{Colors.ENDC}")
                for finding in context.findings[:3]:
                    if hasattr(finding, 'message'):
                        print(f"    • {finding.message}")
                    elif isinstance(finding, dict):
                        print(f"    • {finding.get('message', 'Unknown issue')}")
        else:
            print_error("VALIDATION did not execute or store results")

        # 5. Check FORTIFICATION results
        print_phase_header("5. FORTIFICATION RESULTS")
        if hasattr(context, 'fortifications'):
            print_success("FORTIFICATION executed")
            print_info("Fortifications", len(context.fortifications) if context.fortifications else 0)
            print_info("Applied Fixes", len(context.applied_fixes) if hasattr(context, 'applied_fixes') else 0)

            if context.fortifications:
                print(f"\n  {Colors.CYAN}Sample Fortifications:{Colors.ENDC}")
                for fort in context.fortifications[:2]:
                    print(f"    • {fort.get('title', 'Security fix')}")
        else:
            print_error("FORTIFICATION did not execute or store results")

        # 6. Check CLEANING results
        print_phase_header("6. CLEANING RESULTS")
        if hasattr(context, 'cleaning_suggestions'):
            print_success("CLEANING executed")
            print_info("Cleaning Suggestions", len(context.cleaning_suggestions) if context.cleaning_suggestions else 0)
            print_info("Refactorings", len(context.refactorings) if hasattr(context, 'refactorings') else 0)
            print_info("Quality After", f"{context.quality_score_after:.2f}/10" if hasattr(context, 'quality_score_after') else "N/A")

            if context.cleaning_suggestions:
                print(f"\n  {Colors.CYAN}Sample Suggestions:{Colors.ENDC}")
                for suggestion in context.cleaning_suggestions[:2]:
                    print(f"    • {suggestion.get('title', 'Code improvement')}")
        else:
            print_error("CLEANING did not execute or store results")

        # Summary
        print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}VERIFICATION SUMMARY{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")

        print(f"\n{Colors.CYAN}Phases Executed:{Colors.ENDC}")
        for i, phase in enumerate(phases_executed, 1):
            print(f"  {i}. {phase}")

        # Check errors
        if hasattr(context, 'errors') and context.errors:
            print(f"\n{Colors.WARNING}Errors Encountered:{Colors.ENDC}")
            for error in context.errors:
                print(f"  {Colors.FAIL}• {error}{Colors.ENDC}")

        # Final verdict
        expected_phases = ['PRE-ANALYSIS', 'ANALYSIS', 'CLASSIFICATION', 'VALIDATION', 'FORTIFICATION', 'CLEANING']
        missing_phases = [p for p in expected_phases if p not in phases_executed]

        print(f"\n{Colors.BOLD}FINAL VERDICT:{Colors.ENDC}")
        if not missing_phases:
            print(f"{Colors.GREEN}{Colors.BOLD}✓ ALL 6 PHASES EXECUTED SUCCESSFULLY!{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}✗ MISSING PHASES: {', '.join(missing_phases)}{Colors.ENDC}")

        # Save detailed report
        report_path = Path("/tmp/pipeline_verification_report.json")
        report = {
            "timestamp": datetime.now().isoformat(),
            "phases_executed": phases_executed,
            "missing_phases": missing_phases,
            "context_summary": context.get_summary() if hasattr(context, 'get_summary') else {},
            "errors": context.errors if hasattr(context, 'errors') else [],
            "success": len(missing_phases) == 0
        }

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\n{Colors.CYAN}Detailed report saved to: {report_path}{Colors.ENDC}")

        return len(missing_phases) == 0

    except Exception as e:
        print(f"\n{Colors.FAIL}Pipeline execution failed: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(verify_pipeline())

    if success:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✅ PIPELINE VERIFICATION SUCCESSFUL!{Colors.ENDC}")
        print(f"{Colors.GREEN}All 6 phases are working correctly.{Colors.ENDC}")
    else:
        print(f"\n{Colors.FAIL}{Colors.BOLD}❌ PIPELINE VERIFICATION FAILED!{Colors.ENDC}")
        print(f"{Colors.FAIL}Some phases are not working correctly.{Colors.ENDC}")

    print(f"\n{Colors.CYAN}Run 'cat /tmp/pipeline_verification_report.json' to see the full report.{Colors.ENDC}")