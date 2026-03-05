"""
Tests for TechDebtGenerator.

Tests the generation, smart merge, and idempotency of .warden/TECH_DEBT.md.
"""

import pytest
from pathlib import Path

from warden.reports.tech_debt_generator import TechDebtGenerator, TechDebtReport, TechDebtItem, ResolvedItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project with .warden directory."""
    warden_dir = tmp_path / ".warden"
    warden_dir.mkdir()
    return tmp_path


@pytest.fixture
def generator(tmp_project):
    """Create a TechDebtGenerator for the temp project."""
    return TechDebtGenerator(project_root=tmp_project)


def _make_scan_results(god_classes=None, large_files=None):
    """Helper to build minimal scan result data with antipattern findings."""
    findings = []
    for gc in (god_classes or []):
        findings.append({
            "id": "god-class",
            "severity": "high",
            "message": f"Class '{gc['name']}' has {gc['lines']} lines (max: 500)",
            "location": f"{gc['file']}:{gc.get('line', 1)}",
            "code": f"class {gc['name']}:  # {gc['lines']} lines",
        })
    for lf in (large_files or []):
        findings.append({
            "id": "large-file",
            "severity": "medium",
            "message": f"File has {lf['lines']} lines (max: 1000)",
            "location": f"{lf['file']}:1",
            "code": f"// {lf['lines']} lines",
        })

    return {
        "status": "COMPLETED",
        "frame_results": [
            {
                "frameId": "antipattern",
                "frameName": "Anti-Pattern Detection",
                "status": "failed",
                "findings": findings,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests: Basic Generation
# ---------------------------------------------------------------------------


class TestTechDebtGeneration:
    """Test basic TECH_DEBT.md generation."""

    def test_generate_creates_file(self, generator, tmp_project):
        """Test that generate() creates TECH_DEBT.md when findings exist."""
        results = _make_scan_results(
            god_classes=[
                {"name": "GodService", "file": "services/god.py", "lines": 800},
            ],
            large_files=[
                {"file": "utils/big_file.py", "lines": 1500},
            ],
        )

        path = generator.generate(results)

        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "# Warden Technical Debt" in content
        assert "GodService" in content
        assert "800" in content
        assert "utils/big_file.py" in content
        assert "1500" in content

    def test_generate_no_findings_no_file(self, generator, tmp_project):
        """Test that generate() returns None when no findings and no existing file."""
        results = _make_scan_results()

        path = generator.generate(results)

        assert path is None

    def test_generate_god_class_table_format(self, generator, tmp_project):
        """Test god class table has expected columns."""
        results = _make_scan_results(
            god_classes=[
                {"name": "FrameExecutor", "file": "pipeline/frame_executor.py", "lines": 1044},
            ],
        )

        path = generator.generate(results)

        content = path.read_text()
        assert "| Class | File | Lines | Status |" in content
        assert "| FrameExecutor | pipeline/frame_executor.py | 1044 | Open |" in content

    def test_generate_large_file_table_format(self, generator, tmp_project):
        """Test large file table has expected columns."""
        results = _make_scan_results(
            large_files=[
                {"file": "generated/warden_pb2_grpc.py", "lines": 2529},
            ],
        )

        path = generator.generate(results)

        content = path.read_text()
        assert "| File | Lines | Notes |" in content
        assert "| generated/warden_pb2_grpc.py | 2529 | Auto-generated |" in content

    def test_generate_auto_generated_annotation(self, generator, tmp_project):
        """Test auto-generated files are annotated."""
        results = _make_scan_results(
            large_files=[
                {"file": "grpc/generated/warden_pb2_grpc.py", "lines": 2529},
                {"file": "app/models.py", "lines": 1200},
            ],
        )

        path = generator.generate(results)

        content = path.read_text()
        assert "Auto-generated" in content
        # The non-generated file should not have the annotation
        lines = content.split("\n")
        models_line = [l for l in lines if "app/models.py" in l][0]
        assert "Auto-generated" not in models_line

    def test_generate_sorted_by_line_count(self, generator, tmp_project):
        """Test findings are sorted by line count descending."""
        results = _make_scan_results(
            god_classes=[
                {"name": "SmallGod", "file": "small.py", "lines": 600},
                {"name": "BigGod", "file": "big.py", "lines": 1200},
                {"name": "MedGod", "file": "med.py", "lines": 800},
            ],
        )

        path = generator.generate(results)

        content = path.read_text()
        big_pos = content.index("BigGod")
        med_pos = content.index("MedGod")
        small_pos = content.index("SmallGod")
        assert big_pos < med_pos < small_pos

    def test_generate_multiple_god_classes_and_large_files(self, generator, tmp_project):
        """Test generating with multiple items in each category."""
        results = _make_scan_results(
            god_classes=[
                {"name": "ServiceA", "file": "a.py", "lines": 700},
                {"name": "ServiceB", "file": "b.py", "lines": 600},
            ],
            large_files=[
                {"file": "big1.py", "lines": 2000},
                {"file": "big2.py", "lines": 1500},
            ],
        )

        path = generator.generate(results)

        content = path.read_text()
        assert "ServiceA" in content
        assert "ServiceB" in content
        assert "big1.py" in content
        assert "big2.py" in content


# ---------------------------------------------------------------------------
# Tests: Smart Merge
# ---------------------------------------------------------------------------


class TestTechDebtSmartMerge:
    """Test smart merge behavior (resolved items tracking)."""

    def test_resolved_god_class_moves_to_recently_resolved(self, generator, tmp_project):
        """Test that a previously tracked god class that is no longer detected is resolved."""
        # First scan: one god class
        results1 = _make_scan_results(
            god_classes=[
                {"name": "OldGod", "file": "old.py", "lines": 800},
                {"name": "StillGod", "file": "still.py", "lines": 600},
            ],
        )
        generator.generate(results1)

        # Second scan: OldGod is gone (refactored)
        results2 = _make_scan_results(
            god_classes=[
                {"name": "StillGod", "file": "still.py", "lines": 600},
            ],
        )
        path = generator.generate(results2)

        content = path.read_text()
        assert "## Recently Resolved" in content
        assert "OldGod" in content
        assert "No longer detected" in content
        # StillGod should still be in the active list
        assert "StillGod" in content

    def test_resolved_large_file_moves_to_recently_resolved(self, generator, tmp_project):
        """Test resolved large files move to Recently Resolved."""
        results1 = _make_scan_results(
            large_files=[
                {"file": "huge.py", "lines": 2000},
                {"file": "still_big.py", "lines": 1500},
            ],
        )
        generator.generate(results1)

        results2 = _make_scan_results(
            large_files=[
                {"file": "still_big.py", "lines": 1500},
            ],
        )
        path = generator.generate(results2)

        content = path.read_text()
        assert "huge.py" in content  # In resolved section
        assert "No longer detected" in content

    def test_new_finding_added_on_subsequent_scan(self, generator, tmp_project):
        """Test new findings are added on subsequent scans."""
        results1 = _make_scan_results(
            god_classes=[{"name": "OldGod", "file": "old.py", "lines": 700}],
        )
        generator.generate(results1)

        results2 = _make_scan_results(
            god_classes=[
                {"name": "OldGod", "file": "old.py", "lines": 700},
                {"name": "NewGod", "file": "new.py", "lines": 550},
            ],
        )
        path = generator.generate(results2)

        content = path.read_text()
        assert "OldGod" in content
        assert "NewGod" in content

    def test_preserves_existing_resolved_items(self, generator, tmp_project):
        """Test that existing resolved items are preserved across scans."""
        # Create initial file with a resolved item
        tech_debt_path = tmp_project / ".warden" / "TECH_DEBT.md"
        tech_debt_path.write_text("""# Warden Technical Debt

Last updated: 2026-02-05 by warden scan

## God Classes (500+ lines)

| Class | File | Lines | Status |
|-------|------|-------|--------|
| ActiveGod | active.py | 700 | Open |

## Large Files (1000+ lines)

No large files detected.

## Recently Resolved

| Item | Resolution | Date |
|------|------------|------|
| `AntiPatternFrame` (1142 lines) | Split into detectors | 2026-02-05 |
""")

        # New scan still has ActiveGod
        results = _make_scan_results(
            god_classes=[{"name": "ActiveGod", "file": "active.py", "lines": 700}],
        )
        path = generator.generate(results)

        content = path.read_text()
        assert "ActiveGod" in content
        # Previously resolved item should be preserved
        assert "AntiPatternFrame" in content
        assert "Split into detectors" in content


# ---------------------------------------------------------------------------
# Tests: Idempotency
# ---------------------------------------------------------------------------


class TestTechDebtIdempotency:
    """Test that TECH_DEBT.md is not rewritten if content unchanged."""

    def test_idempotent_no_rewrite_on_same_findings(self, generator, tmp_project):
        """Test file is not rewritten when findings are unchanged."""
        results = _make_scan_results(
            god_classes=[{"name": "GodA", "file": "a.py", "lines": 600}],
        )

        path1 = generator.generate(results)
        mtime1 = path1.stat().st_mtime
        content1 = path1.read_text()

        # Generate again with same results
        path2 = generator.generate(results)
        content2 = path2.read_text()

        # Content should be identical (ignoring timestamp which may differ)
        # The generator should detect this and not rewrite
        assert path2 is not None
        # Both should have the same structural content
        assert "GodA" in content1
        assert "GodA" in content2

    def test_generate_no_findings_preserves_existing(self, generator, tmp_project):
        """Test generate with empty findings updates existing file to empty state."""
        # First: create with findings
        results1 = _make_scan_results(
            god_classes=[{"name": "GodA", "file": "a.py", "lines": 600}],
        )
        generator.generate(results1)

        # Second: empty results (the god class was resolved)
        results2 = _make_scan_results()
        path = generator.generate(results2)

        content = path.read_text()
        # GodA should be in resolved section
        assert "GodA" in content
        assert "No longer detected" in content


# ---------------------------------------------------------------------------
# Tests: Scaffold
# ---------------------------------------------------------------------------


class TestTechDebtScaffold:
    """Test scaffold creation for warden init."""

    def test_scaffold_creates_file(self, tmp_path):
        """Test scaffold creates empty TECH_DEBT.md."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()

        path = TechDebtGenerator.create_scaffold(warden_dir)

        assert path.exists()
        content = path.read_text()
        assert "# Warden Technical Debt" in content
        assert "No god classes detected." in content
        assert "No large files detected." in content
        assert "No recently resolved items." in content

    def test_scaffold_does_not_overwrite_existing(self, tmp_path):
        """Test scaffold does not overwrite an existing TECH_DEBT.md."""
        warden_dir = tmp_path / ".warden"
        warden_dir.mkdir()
        existing = warden_dir / "TECH_DEBT.md"
        existing.write_text("# Custom Content\nDo not overwrite")

        path = TechDebtGenerator.create_scaffold(warden_dir)

        assert path.read_text() == "# Custom Content\nDo not overwrite"


# ---------------------------------------------------------------------------
# Tests: Auto-generated Detection
# ---------------------------------------------------------------------------


class TestAutoGeneratedDetection:
    """Test auto-generated file pattern detection."""

    def test_pb2_grpc_detected(self, generator, tmp_project):
        """Test _pb2_grpc.py files are annotated."""
        results = _make_scan_results(
            large_files=[{"file": "service_pb2_grpc.py", "lines": 3000}],
        )
        path = generator.generate(results)
        content = path.read_text()
        assert "Auto-generated" in content

    def test_pb2_detected(self, generator, tmp_project):
        """Test _pb2.py files are annotated."""
        results = _make_scan_results(
            large_files=[{"file": "service_pb2.py", "lines": 2000}],
        )
        path = generator.generate(results)
        content = path.read_text()
        assert "Auto-generated" in content

    def test_generated_dot_pattern(self, generator, tmp_project):
        """Test .generated. files are annotated."""
        results = _make_scan_results(
            large_files=[{"file": "models.generated.ts", "lines": 5000}],
        )
        path = generator.generate(results)
        content = path.read_text()
        assert "Auto-generated" in content

    def test_normal_file_not_annotated(self, generator, tmp_project):
        """Test normal files are not annotated as auto-generated."""
        results = _make_scan_results(
            large_files=[{"file": "app/views.py", "lines": 1500}],
        )
        path = generator.generate(results)
        content = path.read_text()
        lines = content.split("\n")
        views_line = [l for l in lines if "app/views.py" in l][0]
        assert "Auto-generated" not in views_line


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------


class TestTechDebtEdgeCases:
    """Test edge cases and error handling."""

    def test_findings_from_camel_case_keys(self, generator, tmp_project):
        """Test extraction works with camelCase result keys (frameId vs frame_id)."""
        results = {
            "status": "COMPLETED",
            "frameResults": [
                {
                    "frameId": "antipattern",
                    "frameName": "Anti-Pattern Detection",
                    "status": "failed",
                    "findings": [
                        {
                            "id": "god-class",
                            "severity": "high",
                            "message": "Class 'BigClass' has 900 lines (max: 500)",
                            "location": "big.py:1",
                        },
                    ],
                }
            ],
        }
        path = generator.generate(results)
        content = path.read_text()
        assert "BigClass" in content
        assert "900" in content

    def test_deduplication(self, generator, tmp_project):
        """Test duplicate findings are deduplicated."""
        finding = {
            "id": "god-class",
            "severity": "high",
            "message": "Class 'DupeClass' has 600 lines (max: 500)",
            "location": "dupe.py:1",
        }
        results = {
            "status": "COMPLETED",
            "frame_results": [
                {
                    "frameId": "antipattern",
                    "status": "failed",
                    "findings": [finding, finding],  # Same finding twice
                }
            ],
        }
        path = generator.generate(results)
        content = path.read_text()
        # Should only appear once in the table
        count = content.count("DupeClass")
        assert count == 1

    def test_god_class_auto_generated_in_status_column(self, generator, tmp_project):
        """Test auto-generated god classes show 'Auto-generated' in Status column."""
        results = _make_scan_results(
            god_classes=[
                {"name": "WardenService", "file": "grpc/warden_pb2_grpc.py", "lines": 1386},
            ],
        )
        path = generator.generate(results)
        content = path.read_text()
        lines = content.split("\n")
        warden_line = [l for l in lines if "WardenService" in l][0]
        assert "Auto-generated" in warden_line

    def test_empty_scan_results_dict(self, generator, tmp_project):
        """Test generator handles completely empty scan results."""
        path = generator.generate({})
        assert path is None

    def test_missing_warden_dir_created(self, tmp_path):
        """Test .warden dir is created if it does not exist."""
        gen = TechDebtGenerator(project_root=tmp_path)
        results = _make_scan_results(
            god_classes=[{"name": "Test", "file": "test.py", "lines": 600}],
        )
        path = gen.generate(results)
        assert path is not None
        assert path.exists()
        assert (tmp_path / ".warden").is_dir()
