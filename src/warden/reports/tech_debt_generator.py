"""
Technical Debt Report Generator

Generates and updates .warden/TECH_DEBT.md from AntiPatternFrame findings.
Supports smart merge: new items are added, resolved items are moved to
"Recently Resolved", and auto-generated files are annotated.

Usage (called from scan post-processing):
    from warden.reports.tech_debt_generator import TechDebtGenerator

    generator = TechDebtGenerator(project_root=Path.cwd())
    generator.generate(final_result_data)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Patterns that indicate auto-generated files
AUTO_GENERATED_PATTERNS = [
    r"_pb2\.py$",
    r"_pb2_grpc\.py$",
    r"\.generated\.",
    r"\.g\.dart$",
    r"\.freezed\.dart$",
    r"__generated__",
]


@dataclass
class TechDebtItem:
    """A single technical debt entry (god class or large file)."""

    category: str  # "god_class" or "large_file"
    class_name: str | None  # Only for god classes
    file_path: str
    line_count: int
    status: str = "Open"
    notes: str = ""


@dataclass
class ResolvedItem:
    """An item that was previously tracked but is no longer detected."""

    description: str
    resolution: str
    date: str


@dataclass
class TechDebtReport:
    """Full tech debt report state."""

    god_classes: list[TechDebtItem] = field(default_factory=list)
    large_files: list[TechDebtItem] = field(default_factory=list)
    recently_resolved: list[ResolvedItem] = field(default_factory=list)
    last_updated: str = ""


class TechDebtGenerator:
    """Generates and updates .warden/TECH_DEBT.md from scan findings."""

    TECH_DEBT_PATH = ".warden/TECH_DEBT.md"

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.tech_debt_file = self.project_root / self.TECH_DEBT_PATH

    def generate(self, scan_results: dict[str, Any]) -> Path | None:
        """
        Generate or update TECH_DEBT.md from scan results.

        Args:
            scan_results: The final_result_data dict from scan pipeline.

        Returns:
            Path to the generated file, or None if no changes needed.
        """
        # 1. Extract antipattern findings from scan results
        current_items = self._extract_findings(scan_results)

        if not current_items.god_classes and not current_items.large_files:
            logger.debug("tech_debt_no_findings", msg="No god class or large file findings")
            # If there are no findings and no existing file, skip generation
            if not self.tech_debt_file.exists():
                return None

        # 2. Parse existing TECH_DEBT.md if it exists
        previous = self._parse_existing()

        # 3. Smart merge: detect resolved items
        merged = self._smart_merge(previous, current_items)

        # 4. Check idempotency: skip write if content unchanged
        new_content = self._render(merged)
        if self.tech_debt_file.exists():
            existing_content = self.tech_debt_file.read_text(encoding="utf-8")
            # Compare ignoring the "Last updated" line (timestamp changes)
            if self._content_equal_ignoring_timestamp(existing_content, new_content):
                logger.debug("tech_debt_unchanged", msg="TECH_DEBT.md is already up to date")
                return self.tech_debt_file

        # 5. Write updated file
        self.tech_debt_file.parent.mkdir(parents=True, exist_ok=True)
        self.tech_debt_file.write_text(new_content, encoding="utf-8")
        logger.info("tech_debt_updated", path=str(self.tech_debt_file))
        return self.tech_debt_file

    # =========================================================================
    # EXTRACTION
    # =========================================================================

    def _extract_findings(self, scan_results: dict[str, Any]) -> TechDebtReport:
        """Extract god-class and large-file findings from scan results."""
        report = TechDebtReport()
        report.last_updated = datetime.now().strftime("%Y-%m-%d")

        # Gather all findings from frame_results/frameResults
        all_findings: list[dict[str, Any]] = []
        for key in ("frame_results", "frameResults"):
            for frame in scan_results.get(key, []):
                frame_id = frame.get("frameId", frame.get("frame_id", ""))
                if frame_id == "antipattern":
                    findings = frame.get("findings", [])
                    all_findings.extend(findings if isinstance(findings, list) else [])

        # Also check top-level findings (some pipelines flatten them)
        for key in ("validated_issues", "findings", "true_positives"):
            top_level = scan_results.get(key, [])
            if isinstance(top_level, list):
                for f in top_level:
                    fid = f.get("id", "")
                    if fid in ("god-class", "large-file"):
                        all_findings.append(f)

        # Deduplicate by (id, location)
        seen: set[tuple[str, str]] = set()
        for finding in all_findings:
            finding_id = finding.get("id", "")
            location = finding.get("location", "")
            dedup_key = (finding_id, location)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            if finding_id == "god-class":
                item = self._finding_to_god_class(finding)
                if item:
                    report.god_classes.append(item)
            elif finding_id == "large-file":
                item = self._finding_to_large_file(finding)
                if item:
                    report.large_files.append(item)

        # Sort by line count descending
        report.god_classes.sort(key=lambda x: x.line_count, reverse=True)
        report.large_files.sort(key=lambda x: x.line_count, reverse=True)

        return report

    def _finding_to_god_class(self, finding: dict[str, Any]) -> TechDebtItem | None:
        """Convert a god-class finding dict to a TechDebtItem."""
        message = finding.get("message", "")
        location = finding.get("location", "")

        # Extract class name from message: "Class 'ClassName' has N lines (max: 500)"
        class_match = re.search(r"Class\s+'([^']+)'", message)
        class_name = class_match.group(1) if class_match else "Unknown"

        # Extract line count from message
        lines_match = re.search(r"has\s+(\d+)\s+lines", message)
        line_count = int(lines_match.group(1)) if lines_match else 0

        # Get file path from location ("filename.py:line")
        file_path = location.rsplit(":", 1)[0] if ":" in location else location

        # Annotate auto-generated files
        notes = self._get_auto_generated_note(file_path)

        return TechDebtItem(
            category="god_class",
            class_name=class_name,
            file_path=file_path,
            line_count=line_count,
            notes=notes,
        )

    def _finding_to_large_file(self, finding: dict[str, Any]) -> TechDebtItem | None:
        """Convert a large-file finding dict to a TechDebtItem."""
        message = finding.get("message", "")
        location = finding.get("location", "")

        # Extract line count from message: "File has N lines (max: 1000)"
        lines_match = re.search(r"has\s+(\d+)\s+lines", message)
        line_count = int(lines_match.group(1)) if lines_match else 0

        # Get file path
        file_path = location.rsplit(":", 1)[0] if ":" in location else location

        # Annotate auto-generated files
        notes = self._get_auto_generated_note(file_path)

        return TechDebtItem(
            category="large_file",
            class_name=None,
            file_path=file_path,
            line_count=line_count,
            notes=notes,
        )

    def _get_auto_generated_note(self, file_path: str) -> str:
        """Return annotation note if the file appears auto-generated."""
        for pattern in AUTO_GENERATED_PATTERNS:
            if re.search(pattern, file_path):
                return "Auto-generated"
        return ""

    # =========================================================================
    # PARSING EXISTING
    # =========================================================================

    def _parse_existing(self) -> TechDebtReport:
        """Parse existing TECH_DEBT.md to preserve resolved items."""
        report = TechDebtReport()

        if not self.tech_debt_file.exists():
            return report

        try:
            content = self.tech_debt_file.read_text(encoding="utf-8")
        except Exception:
            return report

        # Parse "Recently Resolved" section
        resolved_section = re.search(
            r"## Recently Resolved\s*\n(.*?)(?=\n## |\n---|\Z)",
            content,
            re.DOTALL,
        )
        if resolved_section:
            # Parse table rows: | Item | Resolution | Date |
            rows = re.findall(
                r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|",
                resolved_section.group(1),
            )
            for row in rows:
                desc, resolution, date = row
                # Skip header row and separator row
                if desc.strip().startswith("Item") or desc.strip().startswith("-"):
                    continue
                report.recently_resolved.append(
                    ResolvedItem(
                        description=desc.strip(),
                        resolution=resolution.strip(),
                        date=date.strip(),
                    )
                )

        # Parse god classes for tracking purposes
        god_section = re.search(
            r"## God Classes.*?\n(.*?)(?=\n## |\n---|\Z)",
            content,
            re.DOTALL,
        )
        if god_section:
            rows = re.findall(
                r"\|\s*`?([^|`]+)`?\s*\|\s*([^|]+)\s*\|\s*(\d+)\s*\|\s*([^|]+)\s*\|",
                god_section.group(1),
            )
            for row in rows:
                name, fpath, lines, status = row
                name = name.strip()
                if name in ("Class", "---", ""):
                    continue
                report.god_classes.append(
                    TechDebtItem(
                        category="god_class",
                        class_name=name,
                        file_path=fpath.strip(),
                        line_count=int(lines),
                        status=status.strip(),
                    )
                )

        # Parse large files
        large_section = re.search(
            r"## Large Files.*?\n(.*?)(?=\n## |\n---|\Z)",
            content,
            re.DOTALL,
        )
        if large_section:
            rows = re.findall(
                r"\|\s*([^|]+)\s*\|\s*(\d+)\s*\|\s*([^|]*)\s*\|",
                large_section.group(1),
            )
            for row in rows:
                fpath, lines, notes = row
                fpath = fpath.strip()
                if fpath in ("File", "---", ""):
                    continue
                report.large_files.append(
                    TechDebtItem(
                        category="large_file",
                        class_name=None,
                        file_path=fpath,
                        line_count=int(lines),
                        notes=notes.strip(),
                    )
                )

        return report

    # =========================================================================
    # SMART MERGE
    # =========================================================================

    def _smart_merge(self, previous: TechDebtReport, current: TechDebtReport) -> TechDebtReport:
        """
        Merge previous and current findings.

        - Items in current but not in previous: new items (added)
        - Items in previous but not in current: resolved (moved to Recently Resolved)
        - Items in both: updated with current line counts
        """
        merged = TechDebtReport()
        merged.last_updated = current.last_updated or datetime.now().strftime("%Y-%m-%d")
        today = merged.last_updated

        # Carry over existing resolved items (keep recent ones, up to 20)
        merged.recently_resolved = list(previous.recently_resolved)

        # --- God classes ---
        prev_god_keys = {(item.class_name, self._normalize_path(item.file_path)) for item in previous.god_classes}
        curr_god_keys = {(item.class_name, self._normalize_path(item.file_path)) for item in current.god_classes}

        # Resolved god classes
        for item in previous.god_classes:
            key = (item.class_name, self._normalize_path(item.file_path))
            if key not in curr_god_keys:
                merged.recently_resolved.append(
                    ResolvedItem(
                        description=f"`{item.class_name}` ({item.line_count} lines)",
                        resolution="No longer detected",
                        date=today,
                    )
                )

        # Current god classes (use current data)
        merged.god_classes = list(current.god_classes)

        # --- Large files ---
        prev_large_keys = {self._normalize_path(item.file_path) for item in previous.large_files}
        curr_large_keys = {self._normalize_path(item.file_path) for item in current.large_files}

        # Resolved large files
        for item in previous.large_files:
            key = self._normalize_path(item.file_path)
            if key not in curr_large_keys:
                merged.recently_resolved.append(
                    ResolvedItem(
                        description=f"{item.file_path} ({item.line_count} lines)",
                        resolution="No longer detected",
                        date=today,
                    )
                )

        # Current large files (use current data)
        merged.large_files = list(current.large_files)

        # Trim resolved items to most recent 20
        merged.recently_resolved = merged.recently_resolved[:20]

        return merged

    def _normalize_path(self, path: str) -> str:
        """Normalize file path for comparison."""
        return path.strip().replace("\\", "/")

    # =========================================================================
    # RENDERING
    # =========================================================================

    def _render(self, report: TechDebtReport) -> str:
        """Render TechDebtReport to markdown string."""
        lines: list[str] = []
        lines.append("# Warden Technical Debt")
        lines.append("")
        lines.append(f"Last updated: {report.last_updated} by warden scan")
        lines.append("")

        # God Classes section
        lines.append("## God Classes (500+ lines)")
        lines.append("")
        if report.god_classes:
            lines.append("| Class | File | Lines | Status |")
            lines.append("|-------|------|-------|--------|")
            for item in report.god_classes:
                status = item.notes if item.notes else item.status
                lines.append(f"| {item.class_name} | {item.file_path} | {item.line_count} | {status} |")
        else:
            lines.append("No god classes detected.")
        lines.append("")

        # Large Files section
        lines.append("## Large Files (1000+ lines)")
        lines.append("")
        if report.large_files:
            lines.append("| File | Lines | Notes |")
            lines.append("|------|-------|-------|")
            for item in report.large_files:
                lines.append(f"| {item.file_path} | {item.line_count} | {item.notes} |")
        else:
            lines.append("No large files detected.")
        lines.append("")

        # Recently Resolved section
        lines.append("## Recently Resolved")
        lines.append("")
        if report.recently_resolved:
            lines.append("| Item | Resolution | Date |")
            lines.append("|------|------------|------|")
            for item in report.recently_resolved:
                lines.append(f"| {item.description} | {item.resolution} | {item.date} |")
        else:
            lines.append("No recently resolved items.")
        lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # IDEMPOTENCY
    # =========================================================================

    def _content_equal_ignoring_timestamp(self, old: str, new: str) -> bool:
        """Compare two TECH_DEBT.md contents ignoring the timestamp line."""
        ts_pattern = re.compile(r"^Last updated:.*$", re.MULTILINE)
        old_clean = ts_pattern.sub("", old).strip()
        new_clean = ts_pattern.sub("", new).strip()
        return old_clean == new_clean

    # =========================================================================
    # SCAFFOLD (for warden init)
    # =========================================================================

    @staticmethod
    def create_scaffold(warden_dir: Path) -> Path:
        """Create an empty TECH_DEBT.md scaffold during warden init."""
        tech_debt_path = warden_dir / "TECH_DEBT.md"
        if tech_debt_path.exists():
            return tech_debt_path

        content = """# Warden Technical Debt

Last updated: (not yet scanned)

## God Classes (500+ lines)

No god classes detected.

## Large Files (1000+ lines)

No large files detected.

## Recently Resolved

No recently resolved items.
"""
        tech_debt_path.write_text(content, encoding="utf-8")
        return tech_debt_path
