"""
Partial Results Writer -- incremental scan persistence (#101).

Writes findings to ``.warden/cache/partial_results.jsonl`` after each
file's frame execution completes so that progress survives crashes.

Lifecycle:
    1. ``append(file_path, frame_id, findings)`` -- called after each
       file finishes; appends one JSON line to the JSONL file.
    2. ``commit()`` -- called on clean completion; deletes the partial
       results file.
    3. On ``SIGINT`` / ``SIGTERM`` the current buffer is flushed
       automatically (signal handler installed at construction time).

Resume support:
    ``load_completed_keys()`` returns a ``set[str]`` of
    ``(frame_id, file_path)`` tuples that have already been scanned.
    The scan loop can skip those entries when ``--resume`` is active.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Default location relative to project root
_DEFAULT_PARTIAL_DIR = ".warden/cache"
_DEFAULT_PARTIAL_FILENAME = "partial_results.jsonl"


class PartialResultsWriter:
    """Append-only JSONL writer for incremental scan persistence.

    Thread-safe: the ``append`` method acquires a lock before writing.
    """

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        install_signal_handlers: bool = True,
    ) -> None:
        root = project_root or Path.cwd()
        self._dir = root / _DEFAULT_PARTIAL_DIR
        self._path = self._dir / _DEFAULT_PARTIAL_FILENAME
        self._lock = threading.Lock()
        self._fd: Any = None
        self._entry_count = 0

        # Ensure the directory exists (idempotent).
        self._dir.mkdir(parents=True, exist_ok=True)

        if install_signal_handlers:
            self._install_signal_handlers()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Return the path to the partial results JSONL file."""
        return self._path

    def append(
        self,
        file_path: str,
        frame_id: str,
        findings: list[dict[str, Any]],
    ) -> None:
        """Append a single scan result line (one file x one frame).

        Args:
            file_path: The source file that was scanned.
            frame_id: The validation frame that produced the findings.
            findings: A list of finding dicts (may be empty for clean files).
        """
        record = {
            "file": file_path,
            "frame_id": frame_id,
            "findings": findings,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._ensure_open()
            line = json.dumps(record, default=str) + "\n"
            self._fd.write(line)
            self._fd.flush()
            os.fsync(self._fd.fileno())
            self._entry_count += 1

    def flush(self) -> None:
        """Force-flush the underlying file descriptor."""
        with self._lock:
            if self._fd is not None and not self._fd.closed:
                self._fd.flush()
                os.fsync(self._fd.fileno())

    def commit(self) -> None:
        """Mark the scan as complete by removing partial results.

        Call this on clean scan completion.
        """
        with self._lock:
            self._close()
            if self._path.exists():
                self._path.unlink()
                logger.debug(
                    "partial_results_committed",
                    path=str(self._path),
                    entries=self._entry_count,
                )
            self._entry_count = 0

    def close(self) -> None:
        """Close the file handle without deleting the file."""
        with self._lock:
            self._close()

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    @classmethod
    def has_partial_results(cls, project_root: Path | None = None) -> bool:
        """Check whether a partial results file exists."""
        root = project_root or Path.cwd()
        path = root / _DEFAULT_PARTIAL_DIR / _DEFAULT_PARTIAL_FILENAME
        return path.exists() and path.stat().st_size > 0

    @classmethod
    def load_completed_keys(cls, project_root: Path | None = None) -> set[tuple[str, str]]:
        """Load ``{(frame_id, file_path), ...}`` from existing partial results.

        Returns an empty set when no partial results exist or on parse
        errors.
        """
        root = project_root or Path.cwd()
        path = root / _DEFAULT_PARTIAL_DIR / _DEFAULT_PARTIAL_FILENAME
        keys: set[tuple[str, str]] = set()

        if not path.exists():
            return keys

        try:
            with open(path, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        frame_id = record.get("frame_id", "")
                        file_path = record.get("file", "")
                        if frame_id and file_path:
                            keys.add((frame_id, file_path))
                    except json.JSONDecodeError:
                        logger.debug(
                            "partial_results_bad_line",
                            line_num=line_num,
                            path=str(path),
                        )
        except OSError as e:
            logger.warning(
                "partial_results_load_failed",
                path=str(path),
                error=str(e),
            )

        if keys:
            logger.info(
                "partial_results_loaded",
                entries=len(keys),
                path=str(path),
            )

        return keys

    @classmethod
    def load_findings(cls, project_root: Path | None = None) -> list[dict[str, Any]]:
        """Load all findings from partial results for report merging.

        Returns a flat list of finding dicts collected from every line
        in the JSONL file.
        """
        root = project_root or Path.cwd()
        path = root / _DEFAULT_PARTIAL_DIR / _DEFAULT_PARTIAL_FILENAME
        all_findings: list[dict[str, Any]] = []

        if not path.exists():
            return all_findings

        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        findings = record.get("findings", [])
                        if findings:
                            all_findings.extend(findings)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        return all_findings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        """Open the JSONL file in append mode if not already open."""
        if self._fd is None or self._fd.closed:
            self._fd = open(self._path, "a", encoding="utf-8")

    def _close(self) -> None:
        """Close the file descriptor if open."""
        if self._fd is not None and not self._fd.closed:
            try:
                self._fd.flush()
                os.fsync(self._fd.fileno())
            except OSError:
                pass
            self._fd.close()
            self._fd = None

    def _install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers to flush on crash.

        Only installs from the main thread (signal module requirement).
        Preserves any previously registered handler by chaining.
        """
        if threading.current_thread() is not threading.main_thread():
            return

        for sig in (signal.SIGINT, signal.SIGTERM):
            prev_handler = signal.getsignal(sig)

            def _handler(signum: int, frame: Any, _prev=prev_handler) -> None:
                self.flush()
                self.close()
                # Re-raise via the previous handler
                if callable(_prev):
                    _prev(signum, frame)
                elif _prev == signal.SIG_DFL:
                    signal.signal(signum, signal.SIG_DFL)
                    os.kill(os.getpid(), signum)

            try:
                signal.signal(sig, _handler)
            except (OSError, ValueError):
                # Cannot set signal handler (e.g. not main thread despite
                # the check above, or platform limitation).
                pass
