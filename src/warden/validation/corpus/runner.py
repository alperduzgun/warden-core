"""
Corpus-based F1/FP/TP scorer for security checks.

Scans a labeled corpus directory and computes per-check precision, recall,
and F1 score. Used by ``warden scan --eval-corpus`` and the autoimprove loop.

Corpus file naming convention:
  *_tp.py / *_tp.js   — True Positive files: scanner MUST produce findings
  *_fp.py / *_fp.js   — False Positive files: scanner MUST NOT flag
  clean_*.py           — True Negative: same as _fp (0 findings expected)
  (no suffix)          — Uses corpus_labels: metadata header only

Expected per-file finding counts are embedded in a ``corpus_labels:`` YAML
block inside the file's docstring:

    corpus_labels:
      sql-injection: 2
      xss: 0
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

_LABEL_RE = re.compile(
    r"corpus_labels\s*:\s*\n((?:\s+[\w-]+\s*:\s*\d+\n?)+)",
    re.MULTILINE,
)
_ENTRY_RE = re.compile(r"^\s+([\w-]+)\s*:\s*(\d+)\s*$", re.MULTILINE)


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class CheckMetrics:
    check_id: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def fp_rate(self) -> float:
        denom = self.fp + self.tn
        return self.fp / denom if denom else 0.0

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "fp_rate": round(self.fp_rate, 4),
        }


@dataclass
class CorpusResult:
    metrics: dict[str, CheckMetrics] = field(default_factory=dict)
    files_scanned: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def overall_f1(self) -> float:
        if not self.metrics:
            return 0.0
        return sum(m.f1 for m in self.metrics.values()) / len(self.metrics)

    def to_dict(self) -> dict:
        return {
            "overall_f1": round(self.overall_f1, 4),
            "files_scanned": self.files_scanned,
            "checks": {cid: m.to_dict() for cid, m in self.metrics.items()},
            "errors": self.errors,
        }


# ─── Label Parsing ────────────────────────────────────────────────────────────


def parse_corpus_labels(content: str) -> dict[str, int]:
    """
    Extract ``corpus_labels:`` block from file docstring.

    Returns dict mapping check_id → expected finding count.
    Returns empty dict if no label block found (file will be skipped).
    """
    match = _LABEL_RE.search(content)
    if not match:
        return {}
    block = match.group(1)
    return {m.group(1): int(m.group(2)) for m in _ENTRY_RE.finditer(block)}


def _infer_labels_from_filename(path: Path, check_ids: list[str]) -> dict[str, int] | None:
    """
    Infer expected findings from filename suffix when no corpus_labels block.

    *_tp.*  → all check_ids: 1 (at least one finding expected)
    *_fp.*  → all check_ids: 0
    clean_* → all check_ids: 0
    other   → None (skip file)
    """
    stem = path.stem.lower()
    if stem.endswith("_tp"):
        return {cid: 1 for cid in check_ids}
    if stem.endswith("_fp") or stem.startswith("clean_"):
        return {cid: 0 for cid in check_ids}
    return None


# ─── Runner ───────────────────────────────────────────────────────────────────


class CorpusRunner:
    """
    Run any Warden validation frame over a labeled corpus directory and compute metrics.

    Works with SecurityFrame, OrphanFrame, AntiPatternFrame, or any custom frame.
    The ``corpus_labels:`` block maps check/pattern IDs to expected finding counts.
    Findings are matched by checking whether the label key appears as a substring of
    ``Finding.id`` — e.g. ``"sql-injection"`` matches ``"security-sql-injection-0"``;
    ``"bare-except"`` matches ``"bare-except-0"``.

    Usage::

        from warden.validation.corpus.runner import CorpusRunner
        from warden.validation.frames.security.security_frame import SecurityFrame

        runner = CorpusRunner(Path("verify/corpus"), SecurityFrame())
        result = await runner.evaluate(check_id="sql-injection")
        print(result.metrics["sql-injection"].f1)

        # Any other frame works the same way:
        from warden.validation.frames.antipattern.antipattern_frame import AntiPatternFrame
        runner = CorpusRunner(Path("verify/corpus/antipattern"), AntiPatternFrame())
        result = await runner.evaluate(check_id="bare-except")
    """

    _SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java"}
    _LANGUAGE_MAP = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript", ".go": "go", ".java": "java",
    }

    def __init__(self, corpus_dir: Path, frame: object) -> None:
        self._corpus_dir = corpus_dir
        self._frame = frame

    # Findings with pattern_confidence below this are LLM-routed and not counted
    # as FPs — they would be dropped by the LLM in a full scan.
    CONFIDENCE_THRESHOLD: float = 0.75

    async def evaluate(
        self,
        check_id: str | None = None,
    ) -> CorpusResult:
        """
        Scan all corpus files and compute per-check metrics.

        Args:
            check_id: If set, only compute metrics for this check.
                      If None, compute metrics for all checks found in labels.
        """
        result = CorpusResult()
        corpus_files = [
            p for p in sorted(self._corpus_dir.iterdir())
            if p.suffix in self._SUPPORTED_EXTENSIONS and not p.name.startswith("__")
        ]

        all_check_ids: list[str] = [check_id] if check_id else []

        # First pass: collect all check_ids from labels
        if not check_id:
            for path in corpus_files:
                content = path.read_text(encoding="utf-8", errors="replace")
                labels = parse_corpus_labels(content)
                for cid in labels:
                    if cid not in all_check_ids:
                        all_check_ids.append(cid)

        if not all_check_ids:
            all_check_ids = [
                "sql-injection", "xss", "hardcoded-password",
                "weak-crypto", "command-injection",
            ]

        # Initialize metrics
        metrics: dict[str, CheckMetrics] = {
            cid: CheckMetrics(check_id=cid) for cid in all_check_ids
        }

        # Second pass: scan each file
        for path in corpus_files:
            content = path.read_text(encoding="utf-8", errors="replace")
            labels = parse_corpus_labels(content)

            if not labels:
                labels = _infer_labels_from_filename(path, all_check_ids) or {}

            if not labels:
                logger.debug("corpus_file_skipped_no_labels", file=path.name)
                continue

            if check_id and check_id not in labels:
                continue

            language = self._LANGUAGE_MAP.get(path.suffix, "python")
            code_file = CodeFile(
                path=str(path),
                content=content,
                language=language,
            )

            try:
                frame_result = await self._frame.execute_async(code_file)
            except Exception as exc:
                msg = f"{path.name}: {exc}"
                result.errors.append(msg)
                logger.warning("corpus_scan_error", file=path.name, error=str(exc))
                continue

            result.files_scanned += 1

            # Score each check_id against its label
            for cid, expected in labels.items():
                if cid not in metrics:
                    continue

                # Only count high-confidence findings — low-confidence ones
                # are LLM-routed and would be dropped in a full (non-fast) scan.
                actual = sum(
                    1 for f in frame_result.findings
                    if cid in (f.id or "")
                    and (
                        getattr(f, "pattern_confidence", None) is None
                        or getattr(f, "pattern_confidence") >= self.CONFIDENCE_THRESHOLD
                    )
                )

                m = metrics[cid]
                if expected > 0:
                    # TP file: scanner should flag
                    caught = min(actual, expected)
                    missed = expected - caught
                    spurious = max(0, actual - expected)
                    m.tp += caught
                    m.fn += missed
                    m.fp += spurious
                else:
                    # FP/TN file: scanner should be silent
                    if actual == 0:
                        m.tn += 1
                    else:
                        m.fp += actual

                logger.debug(
                    "corpus_file_scored",
                    file=path.name,
                    check=cid,
                    expected=expected,
                    actual=actual,
                )

        result.metrics = metrics
        return result


# ─── Table Formatter ──────────────────────────────────────────────────────────


def format_metrics_table(result: CorpusResult) -> str:
    """Render metrics as a human-readable table."""
    if not result.metrics:
        return "No metrics computed."

    col_w = [22, 5, 5, 5, 5, 10, 8, 8]
    header = (
        f"{'Check':<{col_w[0]}} {'TP':>{col_w[1]}} {'FP':>{col_w[2]}} "
        f"{'FN':>{col_w[3]}} {'TN':>{col_w[4]}} "
        f"{'Precision':>{col_w[5]}} {'Recall':>{col_w[6]}} {'F1':>{col_w[7]}}"
    )
    sep = "─" * len(header)
    rows = [sep, header, sep]

    for cid, m in sorted(result.metrics.items()):
        rows.append(
            f"{cid:<{col_w[0]}} {m.tp:>{col_w[1]}} {m.fp:>{col_w[2]}} "
            f"{m.fn:>{col_w[3]}} {m.tn:>{col_w[4]}} "
            f"{m.precision:>{col_w[5]}.2%} {m.recall:>{col_w[6]}.2%} "
            f"{m.f1:>{col_w[7]}.2f}"
        )

    rows.append(sep)
    rows.append(
        f"{'OVERALL':<{col_w[0]}} "
        + " " * (col_w[1] + col_w[2] + col_w[3] + col_w[4] + 3)
        + f" {'':>{col_w[5]}} {'':>{col_w[6]}} "
        f"{result.overall_f1:>{col_w[7]}.2f}"
    )
    rows.append(sep)

    if result.errors:
        rows.append(f"\n⚠ Errors ({len(result.errors)}):")
        for e in result.errors:
            rows.append(f"  {e}")

    return "\n".join(rows)
