#!/usr/bin/env python3
"""Warden Scan Verification Suite.

Runs corpus files through each pipeline phase and validates results
against expected.yaml. No LLM required for deterministic checks.

Usage:
    python verify/verify.py                    # full suite
    python verify/verify.py --phase classify   # classification only
    python verify/verify.py --phase taint      # taint analysis only
    python verify/verify.py --frame security   # security frame only
    python verify/verify.py --no-llm           # skip LLM-dependent checks
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
    parser.add_argument("--phase", choices=["classify", "taint", "security_frame", "report"],
                        help="Run only this phase")
    parser.add_argument("--frame", choices=["security"],
                        help="Run only this frame")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM-dependent checks")
    args = parser.parse_args()

    corpus = _load_corpus()
    expected = _load_expected()
    suite = SuiteResult()

    target_phase = args.phase
    if args.frame == "security":
        target_phase = "security_frame"

    phases = {
        "classify": lambda: run_classify(corpus, expected, suite),
        "taint": lambda: run_taint(corpus, expected, suite),
        "security_frame": lambda: run_security_frame(corpus, expected, suite),
        "report": lambda: run_report(corpus, suite),
    }

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
