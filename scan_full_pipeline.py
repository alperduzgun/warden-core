#!/usr/bin/env python3
"""
Warden Full Pipeline Scanner
============================

Demonstrates complete pipeline execution with all phases:
1. PRE_ANALYSIS - Initial code quality assessment
2. ANALYSIS - Deep code analysis with LLM
3. CLASSIFICATION - AI-powered frame selection
4. VALIDATION - Frame-based validation
5. FORTIFICATION - Security hardening suggestions
6. CLEANING - Code cleanup recommendations

Usage:
    python scan_full_pipeline.py examples/
    python scan_full_pipeline.py examples/vulnerable_code.py
    python scan_full_pipeline.py examples/ --frames security chaos
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from warden.cli_bridge.bridge import WardenBridge


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_header(text: str):
    """Print styled header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text.center(80)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.END}\n")


def print_section(text: str):
    """Print styled section"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}▶ {text}{Colors.END}")
    print(f"{Colors.BLUE}{'-'*80}{Colors.END}")


def print_phase(phase: str, status: str = "started"):
    """Print phase information"""
    emoji = "⚙️" if status == "started" else "✅"
    color = Colors.YELLOW if status == "started" else Colors.GREEN
    print(f"{emoji} {color}{phase}{Colors.END}")


def print_frame(name: str, status: str, duration: float, issues: int):
    """Print frame execution result"""
    status_emoji = {
        "passed": "✅",
        "failed": "❌",
        "skipped": "⏭️"
    }.get(status.lower(), "❓")

    status_color = {
        "passed": Colors.GREEN,
        "failed": Colors.RED,
        "skipped": Colors.YELLOW
    }.get(status.lower(), Colors.END)

    print(f"  {status_emoji} {Colors.BOLD}{name}{Colors.END} "
          f"({status_color}{status}{Colors.END}) - "
          f"{duration:.2f}s - {issues} issues")


def print_issue(issue: dict, index: int):
    """Print issue details"""
    severity_config = {
        'critical': ('🔴', Colors.RED),
        'high': ('🟠', Colors.YELLOW),
        'medium': ('🟡', Colors.CYAN),
        'low': ('🟢', Colors.GREEN)
    }

    emoji, color = severity_config.get(issue['severity'], ('⚪', Colors.END))

    print(f"\n{color}{Colors.BOLD}Issue #{index + 1} - {issue['severity'].upper()}{Colors.END}")
    print(f"  {emoji} {issue['message']}")
    print(f"  📁 File: {issue['filePath']}:{issue['line']}")
    print(f"  🏷️  Frame: {issue['frame']} | Rule: {issue['rule']}")


async def scan_with_full_pipeline(
    path: str,
    frames: Optional[List[str]] = None,
    verbose: bool = True
):
    """
    Execute full Warden pipeline with real-time progress tracking.

    Args:
        path: Path to scan (file or directory)
        frames: Optional list of specific frames to run
        verbose: Enable verbose output
    """
    print_header("🛡️  WARDEN FULL PIPELINE SCANNER")

    print(f"{Colors.BOLD}Configuration:{Colors.END}")
    print(f"  📂 Scan Path: {path}")
    print(f"  🎯 Frames: {', '.join(frames) if frames else 'All (AI-selected)'}")
    print(f"  🕐 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Initialize bridge
    print(f"\n{Colors.YELLOW}🔧 Initializing Warden Bridge...{Colors.END}")
    bridge = WardenBridge(project_root=Path.cwd())

    # Get configuration
    config = await bridge.get_config()
    print(f"{Colors.GREEN}✅ Bridge initialized{Colors.END}")
    print(f"  🤖 LLM Provider: {config['default_provider']}")
    print(f"  📋 Available Frames: {config['total_frames']}")
    print(f"  ⚙️  Config: {config['config_name']}")

    # Track pipeline phases
    phases_seen = set()
    frames_executed = []
    start_time = datetime.now()

    print_section("🚀 EXECUTING PIPELINE")

    try:
        # Execute pipeline with streaming
        async for event in bridge.execute_pipeline_stream(
            file_path=path,
            frames=frames,
            verbose=verbose
        ):
            event_type = event.get("type")

            if event_type == "progress":
                event_name = event['event']
                data = event.get('data', {})

                # Phase events
                if event_name == "phase_started":
                    phase = data.get('phase', 'UNKNOWN')
                    phases_seen.add(phase)
                    print_phase(f"Phase: {phase}", "started")

                elif event_name == "phase_completed":
                    phase = data.get('phase', 'UNKNOWN')
                    duration = data.get('duration', 0)
                    print_phase(f"Phase: {phase} completed in {duration:.2f}s", "completed")

                # Frame events
                elif event_name == "frame_started":
                    frame_name = data.get('frame_name', 'Unknown')
                    print(f"  🔸 Starting: {Colors.BOLD}{frame_name}{Colors.END}")

                elif event_name == "frame_completed":
                    frame_name = data.get('frame_name', 'Unknown')
                    status = data.get('status', 'unknown')
                    duration = data.get('duration', 0)
                    issues = data.get('issues_found', 0)

                    frames_executed.append({
                        'name': frame_name,
                        'status': status,
                        'duration': duration,
                        'issues': issues
                    })

                    print_frame(frame_name, status, duration, issues)

                # Pipeline events
                elif event_name == "pipeline_started":
                    print(f"{Colors.GREEN}▶️  Pipeline execution started{Colors.END}")

                elif event_name == "pipeline_completed":
                    print(f"{Colors.GREEN}✅ Pipeline execution completed{Colors.END}")

                # Classification events (AI frame selection)
                elif event_name == "classification_completed":
                    selected_frames = data.get('selected_frames', [])
                    confidence = data.get('confidence', 0)
                    print(f"\n  🤖 AI Classification Complete:")
                    print(f"     Selected Frames: {', '.join(selected_frames)}")
                    print(f"     Confidence: {confidence:.2%}")

                # Verbose events
                elif verbose and event_name in ["validation_started", "fortification_started", "cleaning_started"]:
                    print(f"  ℹ️  {event_name.replace('_', ' ').title()}")

            elif event_type == "result":
                # Final results
                result = event['data']

                print_section("📊 PIPELINE RESULTS")

                # Overall status
                status = result.get('status', 'unknown')
                # Convert to string if it's not already
                status_str = str(status) if not isinstance(status, str) else status
                status_emoji = "✅" if status_str == "success" else "❌"
                status_color = Colors.GREEN if status_str == "success" else Colors.RED

                print(f"\n{status_emoji} {Colors.BOLD}Overall Status: {status_color}{status_str.upper()}{Colors.END}")

                # Timing
                duration = result['duration']
                end_time = datetime.now()
                print(f"\n⏱️  {Colors.BOLD}Timing:{Colors.END}")
                print(f"  Total Duration: {duration:.2f}s")
                print(f"  Started: {start_time.strftime('%H:%M:%S')}")
                print(f"  Ended: {end_time.strftime('%H:%M:%S')}")

                # Phases executed
                print(f"\n🔄 {Colors.BOLD}Phases Executed:{Colors.END}")
                phase_names = {
                    'PRE_ANALYSIS': '📋 Pre-Analysis (Quality Assessment)',
                    'ANALYSIS': '🔍 Analysis (Deep Code Analysis)',
                    'CLASSIFICATION': '🤖 Classification (AI Frame Selection)',
                    'VALIDATION': '✅ Validation (Frame Execution)',
                    'FORTIFICATION': '🛡️  Fortification (Security Hardening)',
                    'CLEANING': '🧹 Cleaning (Code Cleanup)'
                }
                for phase in ['PRE_ANALYSIS', 'ANALYSIS', 'CLASSIFICATION', 'VALIDATION', 'FORTIFICATION', 'CLEANING']:
                    status = "✅" if phase in phases_seen else "⏭️"
                    phase_desc = phase_names.get(phase, phase)
                    print(f"  {status} {phase_desc}")

                # Frame results
                print(f"\n🎯 {Colors.BOLD}Frame Results:{Colors.END}")
                print(f"  Total Frames: {result['total_frames']}")
                print(f"  {Colors.GREEN}Passed: {result['frames_passed']}{Colors.END}")
                print(f"  {Colors.RED}Failed: {result['frames_failed']}{Colors.END}")
                print(f"  {Colors.YELLOW}Skipped: {result['frames_skipped']}{Colors.END}")

                # Findings summary
                print(f"\n🔍 {Colors.BOLD}Findings Summary:{Colors.END}")
                print(f"  Total Findings: {result['total_findings']}")
                print(f"  {Colors.RED}🔴 Critical: {result['critical_findings']}{Colors.END}")
                print(f"  {Colors.YELLOW}🟠 High: {result['high_findings']}{Colors.END}")
                print(f"  {Colors.CYAN}🟡 Medium: {result['medium_findings']}{Colors.END}")
                print(f"  {Colors.GREEN}🟢 Low: {result['low_findings']}{Colors.END}")

                # LLM Analysis info
                if 'llm_analysis' in result:
                    llm_info = result['llm_analysis']
                    print(f"\n🤖 {Colors.BOLD}LLM Analysis:{Colors.END}")
                    print(f"  Enabled: {'✅ Yes' if llm_info.get('llm_enabled') else '❌ No'}")
                    if llm_info.get('llm_enabled'):
                        print(f"  Provider: {llm_info.get('llm_provider', 'unknown')}")
                        print(f"  Phases with LLM: {', '.join(llm_info.get('phases_with_llm', []))}")

                # Context summary
                if 'context_summary' in result:
                    context = result['context_summary']
                    print(f"\n📝 {Colors.BOLD}Context Summary:{Colors.END}")
                    if 'quality_metrics' in context:
                        metrics = context['quality_metrics']
                        print(f"  Quality Score: {metrics.get('overall_score', 'N/A')}")
                    if 'file_classification' in context:
                        classification = context['file_classification']
                        print(f"  File Type: {classification.get('file_type', 'unknown')}")
                        print(f"  Complexity: {classification.get('complexity', 'unknown')}")

                # Frame execution details
                if frames_executed:
                    print_section("🔍 FRAME EXECUTION DETAILS")
                    for frame in frames_executed:
                        print_frame(
                            frame['name'],
                            frame['status'],
                            frame['duration'],
                            frame['issues']
                        )

                # Detailed findings
                if result.get('frame_results'):
                    print_section("📋 DETAILED FINDINGS")

                    issue_count = 0
                    for frame_result in result['frame_results']:
                        if frame_result.get('findings'):
                            print(f"\n{Colors.BOLD}Frame: {frame_result['frame_name']}{Colors.END}")

                            for finding in frame_result['findings']:
                                issue = {
                                    'severity': finding.get('severity', 'unknown'),
                                    'message': finding.get('message', 'No message'),
                                    'filePath': finding.get('file', 'unknown'),
                                    'line': finding.get('line', 0),
                                    'frame': frame_result['frame_id'],
                                    'rule': finding.get('code', 'unknown')
                                }
                                print_issue(issue, issue_count)
                                issue_count += 1

                # Final summary
                print_header("✨ SCAN COMPLETE")

                success_rate = (result['frames_passed'] / result['total_frames'] * 100) if result['total_frames'] > 0 else 0
                print(f"  Success Rate: {success_rate:.1f}%")
                print(f"  Total Issues: {result['total_findings']}")
                print(f"  Execution Time: {duration:.2f}s")

                if result['total_findings'] == 0:
                    print(f"\n  {Colors.GREEN}{Colors.BOLD}🎉 No issues found! Code looks great!{Colors.END}")
                elif result['critical_findings'] > 0:
                    print(f"\n  {Colors.RED}{Colors.BOLD}⚠️  Critical issues found! Please review immediately.{Colors.END}")
                else:
                    print(f"\n  {Colors.YELLOW}{Colors.BOLD}⚡ Some issues found. Review recommended.{Colors.END}")

    except Exception as e:
        print(f"\n{Colors.RED}{Colors.BOLD}❌ Error during pipeline execution:{Colors.END}")
        print(f"{Colors.RED}{str(e)}{Colors.END}")
        import traceback
        if verbose:
            traceback.print_exc()
        return 1

    return 0


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Warden Full Pipeline Scanner - Complete validation with all phases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan entire examples directory with all phases
  python scan_full_pipeline.py examples/

  # Scan single file
  python scan_full_pipeline.py examples/vulnerable_code.py

  # Scan with specific frames only
  python scan_full_pipeline.py examples/ --frames security chaos

  # Quiet mode (less verbose)
  python scan_full_pipeline.py examples/ --quiet
        """
    )

    parser.add_argument(
        "path",
        help="Path to scan (file or directory)"
    )

    parser.add_argument(
        "--frames",
        nargs="+",
        help="Specific frames to execute (default: AI-selected)"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity"
    )

    args = parser.parse_args()

    # Execute scan
    exit_code = await scan_with_full_pipeline(
        path=args.path,
        frames=args.frames,
        verbose=not args.quiet
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
