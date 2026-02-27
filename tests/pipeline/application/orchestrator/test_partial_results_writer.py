"""Tests for PartialResultsWriter -- incremental scan persistence (#101)."""

import json
import os
from pathlib import Path

import pytest

from warden.pipeline.application.orchestrator.partial_results_writer import (
    PartialResultsWriter,
    _DEFAULT_PARTIAL_DIR,
    _DEFAULT_PARTIAL_FILENAME,
)


@pytest.fixture
def project_root(tmp_path):
    """Create a temporary project root directory."""
    return tmp_path


@pytest.fixture
def writer(project_root):
    """Create a PartialResultsWriter for testing.

    Signal handlers are disabled to avoid interfering with pytest's
    own signal handling.
    """
    w = PartialResultsWriter(
        project_root=project_root,
        install_signal_handlers=False,
    )
    yield w
    w.close()


class TestPartialResultsAppend:
    """Tests for the append method."""

    def test_append_creates_jsonl_file(self, writer, project_root):
        """First append creates the JSONL file."""
        writer.append("src/app.py", "security_frame", [])
        assert writer.path.exists()

    def test_append_writes_valid_json_lines(self, writer):
        """Each append produces a valid JSON line."""
        writer.append("a.py", "frame_1", [{"id": "F-001", "severity": "high"}])
        writer.append("b.py", "frame_1", [])

        with open(writer.path) as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 2

        record_1 = json.loads(lines[0])
        assert record_1["file"] == "a.py"
        assert record_1["frame_id"] == "frame_1"
        assert len(record_1["findings"]) == 1
        assert record_1["findings"][0]["id"] == "F-001"
        assert "ts" in record_1

        record_2 = json.loads(lines[1])
        assert record_2["file"] == "b.py"
        assert record_2["findings"] == []

    def test_append_with_empty_findings(self, writer):
        """Clean files produce a line with empty findings list."""
        writer.append("clean.py", "test_frame", [])

        with open(writer.path) as f:
            record = json.loads(f.readline())

        assert record["findings"] == []

    def test_append_increments_entry_count(self, writer):
        """Internal entry counter tracks appends."""
        writer.append("a.py", "f1", [])
        writer.append("b.py", "f1", [])
        writer.append("c.py", "f2", [])
        assert writer._entry_count == 3


class TestPartialResultsCommit:
    """Tests for the commit method (clean completion)."""

    def test_commit_deletes_partial_file(self, writer):
        """Clean completion removes the partial results file."""
        writer.append("a.py", "frame_1", [])
        assert writer.path.exists()

        writer.commit()
        assert not writer.path.exists()

    def test_commit_resets_entry_count(self, writer):
        """Entry count is zeroed after commit."""
        writer.append("a.py", "f1", [])
        writer.commit()
        assert writer._entry_count == 0

    def test_commit_without_appends_is_safe(self, writer):
        """Committing without any appends is a no-op."""
        writer.commit()  # Should not raise


class TestPartialResultsResume:
    """Tests for resume support: load_completed_keys."""

    def test_load_completed_keys_returns_set_of_tuples(self, writer, project_root):
        """Completed keys are (frame_id, file_path) tuples."""
        writer.append("src/a.py", "security_frame", [])
        writer.append("src/b.py", "quality_frame", [{"id": "Q-1"}])
        writer.close()

        keys = PartialResultsWriter.load_completed_keys(project_root)
        assert ("security_frame", "src/a.py") in keys
        assert ("quality_frame", "src/b.py") in keys
        assert len(keys) == 2

    def test_load_completed_keys_empty_when_no_file(self, project_root):
        """No partial results file returns empty set."""
        keys = PartialResultsWriter.load_completed_keys(project_root)
        assert keys == set()

    def test_load_completed_keys_skips_bad_lines(self, writer, project_root):
        """Malformed JSON lines are skipped gracefully."""
        writer.append("good.py", "f1", [])
        writer.close()

        # Inject a bad line
        with open(writer.path, "a") as f:
            f.write("NOT VALID JSON\n")

        writer2 = PartialResultsWriter(
            project_root=project_root, install_signal_handlers=False,
        )
        writer2.append("also_good.py", "f2", [])
        writer2.close()

        keys = PartialResultsWriter.load_completed_keys(project_root)
        assert ("f1", "good.py") in keys
        assert ("f2", "also_good.py") in keys

    def test_has_partial_results_true_when_file_exists(self, writer, project_root):
        """has_partial_results returns True when file exists with content."""
        writer.append("a.py", "f1", [])
        writer.close()

        assert PartialResultsWriter.has_partial_results(project_root) is True

    def test_has_partial_results_false_when_missing(self, project_root):
        """has_partial_results returns False when no file exists."""
        assert PartialResultsWriter.has_partial_results(project_root) is False


class TestPartialResultsLoadFindings:
    """Tests for loading findings from partial results."""

    def test_load_findings_returns_flat_list(self, writer, project_root):
        """Findings from all lines are merged into a flat list."""
        writer.append("a.py", "f1", [
            {"id": "F-001", "severity": "high", "message": "Issue 1"},
        ])
        writer.append("b.py", "f1", [
            {"id": "F-002", "severity": "medium", "message": "Issue 2"},
            {"id": "F-003", "severity": "low", "message": "Issue 3"},
        ])
        writer.append("c.py", "f2", [])  # clean file
        writer.close()

        findings = PartialResultsWriter.load_findings(project_root)
        assert len(findings) == 3
        ids = {f["id"] for f in findings}
        assert ids == {"F-001", "F-002", "F-003"}

    def test_load_findings_empty_when_no_file(self, project_root):
        """Returns empty list when no partial results exist."""
        findings = PartialResultsWriter.load_findings(project_root)
        assert findings == []


class TestPartialResultsFlush:
    """Tests for flush and close behaviour."""

    def test_flush_is_safe_before_any_append(self, writer):
        """Flush before any writes does not raise."""
        writer.flush()

    def test_close_is_idempotent(self, writer):
        """Closing twice does not raise."""
        writer.append("a.py", "f1", [])
        writer.close()
        writer.close()  # Should not raise

    def test_path_property(self, writer, project_root):
        """Path property returns the expected JSONL path."""
        expected = project_root / _DEFAULT_PARTIAL_DIR / _DEFAULT_PARTIAL_FILENAME
        assert writer.path == expected


class TestPartialResultsDirectoryCreation:
    """Tests for directory creation behaviour."""

    def test_creates_cache_directory(self, tmp_path):
        """Writer creates .warden/cache/ directory if missing."""
        root = tmp_path / "fresh_project"
        root.mkdir()

        w = PartialResultsWriter(
            project_root=root, install_signal_handlers=False,
        )
        assert (root / _DEFAULT_PARTIAL_DIR).is_dir()
        w.close()
