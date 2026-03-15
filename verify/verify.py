#!/usr/bin/env python3
"""Warden Scan Verification Suite.

Runs corpus files through each pipeline phase and validates results
against expected.yaml.

Default mode includes mock LLM pipeline test (no real API calls).
Use --no-llm to skip LLM integration test for faster CI runs.

Usage:
    python verify/verify.py                    # full suite (deterministic + mock LLM)
    python verify/verify.py --no-llm           # deterministic only (fast, CI default)
    python verify/verify.py --phase classify   # classification only
    python verify/verify.py --phase taint      # taint analysis only
    python verify/verify.py --frame security   # security frame only
    python verify/verify.py --phase pipeline_llm  # mock LLM pipeline only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
VERIFY_DIR = Path(__file__).resolve().parent
CORPUS_DIR = VERIFY_DIR / "corpus"
EXPECTED_FILE = VERIFY_DIR / "expected.yaml"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    phase: str
    file: str
    check: str
    passed: bool
    detail: str = ""


@dataclass
class SuiteResult:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def add(self, phase: str, file: str, check: str, passed: bool, detail: str = "") -> None:
        self.results.append(CheckResult(phase, file, check, passed, detail))


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def _load_corpus() -> dict[str, tuple[str, str]]:
    """Return {filename: (content, language)}."""
    files: dict[str, tuple[str, str]] = {}
    for p in sorted(CORPUS_DIR.iterdir()):
        if p.suffix in (".py", ".js"):
            lang = "python" if p.suffix == ".py" else "javascript"
            files[p.name] = (p.read_text(), lang)
    return files


def _load_expected() -> dict[str, Any]:
    return yaml.safe_load(EXPECTED_FILE.read_text())


def run_classify(corpus: dict, expected: dict, suite: SuiteResult) -> None:
    """Test heuristic classification for each corpus file."""
    from warden.classification.application.heuristic_classifier import HeuristicClassifier
    from warden.validation.domain.frame import CodeFile

    available_frames = [
        "security", "resilience", "fuzz", "property",
        "antipattern", "architecture", "orphan", "gitchanges", "spec",
    ]

    for fname, (content, lang) in corpus.items():
        exp = expected.get(fname, {}).get("classify", {})
        must_include = exp.get("must_include_frames", [])

        code_file = CodeFile(path=fname, content=content, language=lang)
        result = HeuristicClassifier.classify([code_file], available_frames)

        for frame_id in must_include:
            ok = frame_id in result.frames
            suite.add(
                "classify", fname, f"must_include:{frame_id}",
                ok,
                f"selected={result.frames}" if not ok else "",
            )


async def run_taint(corpus: dict, expected: dict, suite: SuiteResult) -> None:
    """Test taint analysis for each corpus file."""
    from warden.validation.frames.security._internal.taint_analyzer import TaintAnalyzer

    analyzer = TaintAnalyzer()

    for fname, (content, lang) in corpus.items():
        exp = expected.get(fname, {}).get("taint", {})
        min_paths = exp.get("min_paths", 0)
        expected_sinks = set(exp.get("taint_sinks", []))

        paths = analyzer.analyze(content, lang)

        # Check minimum path count
        ok = len(paths) >= min_paths
        suite.add(
            "taint", fname, f"min_paths>={min_paths}",
            ok,
            f"got {len(paths)} paths" if not ok else f"{len(paths)} paths",
        )

        # Check expected sink types
        if expected_sinks:
            found_sinks = {p.sink.sink_type for p in paths if hasattr(p.sink, "sink_type")}
            for sink_type in expected_sinks:
                ok = sink_type in found_sinks
                suite.add(
                    "taint", fname, f"sink:{sink_type}",
                    ok,
                    f"found_sinks={found_sinks}" if not ok else "",
                )


async def run_security_frame(corpus: dict, expected: dict, suite: SuiteResult) -> None:
    """Test SecurityFrame deterministic checks for each corpus file."""
    from warden.validation.domain.frame import CodeFile
    from warden.validation.frames.security import SecurityFrame

    frame = SecurityFrame()

    for fname, (content, lang) in corpus.items():
        exp = expected.get(fname, {}).get("security_frame", {})
        min_findings = exp.get("min_findings", 0)
        max_findings = exp.get("max_findings", None)
        contains = exp.get("contains", [])

        code_file = CodeFile(path=fname, content=content, language=lang)

        try:
            result = await frame.execute_async(code_file)
        except Exception as e:
            suite.add("security_frame", fname, "execute", False, f"ERROR: {e}")
            continue

        findings = result.findings if result else []
        count = len(findings)

        # Min findings check
        ok = count >= min_findings
        suite.add(
            "security_frame", fname, f"min_findings>={min_findings}",
            ok,
            f"got {count}" if not ok else f"{count} findings",
        )

        # Max findings check (false positive test)
        if max_findings is not None:
            ok = count <= max_findings
            suite.add(
                "security_frame", fname, f"max_findings<={max_findings}",
                ok,
                f"got {count} (expected max {max_findings})" if not ok else "",
            )

        # Contains check
        if contains and count > 0:
            all_text = " ".join(
                (getattr(f, "message", "") or "") + " " + (getattr(f, "id", "") or "")
                for f in findings
            ).lower()
            matched_any = any(kw.lower() in all_text for kw in contains)
            suite.add(
                "security_frame", fname, f"contains_any:{contains}",
                matched_any,
                f"findings_text='{all_text[:200]}'" if not matched_any else "",
            )


async def run_pipeline_with_llm(corpus: dict, expected: dict, suite: SuiteResult) -> None:
    """Test full pipeline with mock LLM — validates LLM-dependent phases work end-to-end.

    Phases tested:
    - Classification (heuristic + LLM fallback)
    - Validation (SecurityFrame with LLM batch verification)
    - Verification (FP filtering)
    All with a mock LLM that returns valid JSON responses.
    """
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock

    from warden.pipeline import PipelineConfig
    from warden.pipeline.application.orchestrator.orchestrator import PhaseOrchestrator
    from warden.pipeline.domain.enums import AnalysisLevel, PipelineStatus
    from warden.validation.domain.frame import CodeFile
    from warden.validation.frames import SecurityFrame

    # Mock LLM that returns plausible JSON for any prompt
    mock_llm = AsyncMock()
    mock_llm.complete_async = AsyncMock(return_value=MagicMock(
        content='{"score": 6.5, "confidence": 0.8, "summary": "Mock analysis", "issues": []}',
        success=True,
    ))
    mock_llm.provider = MagicMock(value="mock")
    mock_llm.config = None
    mock_llm.get_usage = MagicMock(return_value={
        "total_tokens": 100, "prompt_tokens": 50,
        "completion_tokens": 50, "request_count": 1,
    })

    # Pick 2 corpus files: 1 vulnerable (sqli), 1 clean
    test_files = {
        "python_sqli.py": ("python", True),
        "clean_python.py": ("python", False),
    }

    for fname, (lang, is_vulnerable) in test_files.items():
        if fname not in corpus:
            continue

        content, _ = corpus[fname]
        code_file = CodeFile(path=fname, content=content, language=lang)

        config = PipelineConfig(
            analysis_level=AnalysisLevel.STANDARD,
            use_llm=True,
            enable_fortification=False,
            enable_cleaning=False,
            enable_issue_validation=True,
            timeout=60,
        )

        orchestrator = PhaseOrchestrator(
            frames=[SecurityFrame()],
            config=config,
            project_root=Path.cwd(),
            llm_service=mock_llm,
        )

        try:
            result, context = await orchestrator.execute_async(
                [code_file], analysis_level="standard",
            )
        except Exception as e:
            suite.add("pipeline_llm", fname, "execute", False, f"ERROR: {e}")
            continue

        # Check 1: Pipeline completed (didn't crash with mock LLM)
        terminal = {PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.COMPLETED_WITH_FAILURES}
        ok = result.status in terminal
        suite.add("pipeline_llm", fname, "completed", ok, f"status={result.status}")

        # Check 2: Classification ran (selected_frames populated)
        frames = getattr(context, "selected_frames", None)
        ok = frames is not None and len(frames) > 0
        suite.add("pipeline_llm", fname, "classification_ran", ok,
                   f"selected_frames={frames}" if not ok else f"{len(frames)} frames")

        # Check 3: Validation ran (frame_results populated)
        ok = isinstance(context.frame_results, dict) and len(context.frame_results) > 0
        suite.add("pipeline_llm", fname, "validation_ran", ok)

        # Check 4: Vulnerable file should have findings
        if is_vulnerable:
            ok = result.total_findings >= 1
            suite.add("pipeline_llm", fname, "has_findings", ok,
                       f"total_findings={result.total_findings}")

        # Check 5: Mock LLM called for vulnerable files (clean may skip via heuristic)
        if is_vulnerable:
            ok = mock_llm.complete_async.call_count > 0
            suite.add("pipeline_llm", fname, "llm_called", ok,
                       f"call_count={mock_llm.complete_async.call_count}")
        else:
            # Clean files may or may not trigger LLM — just report, don't fail
            suite.add("pipeline_llm", fname, "llm_call_count",
                       True, f"calls={mock_llm.complete_async.call_count} (informational)")

        # Reset mock call count for next file
        mock_llm.complete_async.reset_mock()


async def run_report(corpus: dict, suite: SuiteResult) -> None:
    """Test that SARIF report generation produces valid output."""
    from warden.reports.generator import ReportGenerator

    import json
    import tempfile

    generator = ReportGenerator()

    # Minimal scan_results dict
    scan_results = {
        "pipeline_id": "verify-test",
        "status": 0,
        "total_findings": 1,
        "frame_results": [
            {
                "frame_id": "security",
                "frame_name": "Security Analysis",
                "status": "passed",
                "findings": [
                    {
                        "id": "test-001",
                        "severity": "high",
                        "message": "Test finding",
                        "location": "test.py:1",
                        "detail": "Test detail",
                    }
                ],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        sarif_path = Path(tmp) / "test.sarif"
        try:
            generator.generate_sarif_report(scan_results, sarif_path)
            ok = sarif_path.exists() and sarif_path.stat().st_size > 0
            suite.add("report", "sarif", "file_created", ok)

            if ok:
                data = json.loads(sarif_path.read_text())
                has_version = data.get("version") == "2.1.0"
                has_runs = len(data.get("runs", [])) > 0
                suite.add("report", "sarif", "version=2.1.0", has_version)
                suite.add("report", "sarif", "has_runs", has_runs)
        except Exception as e:
            suite.add("report", "sarif", "generate", False, f"ERROR: {e}")

        json_path = Path(tmp) / "test.json"
        try:
            generator.generate_json_report(scan_results, json_path)
            ok = json_path.exists() and json_path.stat().st_size > 0
            suite.add("report", "json", "file_created", ok)
        except Exception as e:
            suite.add("report", "json", "generate", False, f"ERROR: {e}")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(suite: SuiteResult) -> None:
    current_phase = ""
    for r in suite.results:
        if r.phase != current_phase:
            current_phase = r.phase
            print(f"\n{'=' * 60}")
            print(f"  PHASE: {current_phase.upper()}")
            print(f"{'=' * 60}")

        icon = "\033[32m PASS\033[0m" if r.passed else "\033[31m FAIL\033[0m"
        line = f"  [{icon}] {r.file:<35s} {r.check}"
        if r.detail and not r.passed:
            line += f"\n         {r.detail}"
        print(line)

    print(f"\n{'=' * 60}")
    total = suite.total
    passed = suite.passed
    failed = suite.failed
    color = "\033[32m" if failed == 0 else "\033[31m"
    print(f"  TOTAL: {total}  PASSED: {passed}  FAILED: {color}{failed}\033[0m")
    pct = (passed / total * 100) if total else 0
    print(f"  RECALL: {pct:.0f}%")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(description="Warden Verify Suite")
    parser.add_argument("--phase", choices=["classify", "taint", "security_frame", "report", "pipeline_llm"],
                        help="Run only this phase")
    parser.add_argument("--frame", choices=["security"],
                        help="Run only this frame")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM-dependent checks (default: include mock LLM pipeline test)")
    parser.add_argument("--with-llm", action="store_true",
                        help="(Alias) Explicitly include mock LLM pipeline test")
    args = parser.parse_args()

    corpus = _load_corpus()
    expected = _load_expected()
    suite = SuiteResult()

    target_phase = args.phase
    if args.frame == "security":
        target_phase = "security_frame"

    # Deterministic phases (always run)
    phases: dict[str, Any] = {
        "classify": lambda: run_classify(corpus, expected, suite),
        "taint": lambda: run_taint(corpus, expected, suite),
        "security_frame": lambda: run_security_frame(corpus, expected, suite),
        "report": lambda: run_report(corpus, suite),
    }

    # LLM phase (mock-based, run by default unless --no-llm)
    if not args.no_llm:
        phases["pipeline_llm"] = lambda: run_pipeline_with_llm(corpus, expected, suite)

    start = time.monotonic()

    for name, runner in phases.items():
        if target_phase and name != target_phase:
            continue
        result = runner()
        if asyncio.iscoroutine(result):
            await result

    elapsed = time.monotonic() - start

    print_results(suite)
    print(f"  Duration: {elapsed:.1f}s")

    return 1 if suite.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
