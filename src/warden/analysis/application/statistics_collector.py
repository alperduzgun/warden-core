"""
Project Statistics Collection Module.

Collects statistical information about the project during PRE-ANALYSIS phase.
"""

from pathlib import Path
from typing import Dict, List, Set
import structlog

from warden.analysis.domain.project_context import ProjectStatistics

logger = structlog.get_logger()


class StatisticsCollector:
    """
    Collects statistical information about the project.

    Part of the PRE-ANALYSIS phase for context detection.
    """

    def __init__(
        self,
        project_root: Path,
        special_dirs: Dict[str, List[str]],
    ):
        """
        Initialize statistics collector.

        Args:
            project_root: Root directory of the project
            special_dirs: Special directories found
        """
        self.project_root = project_root
        self.special_dirs = special_dirs

    async def collect_async(self) -> ProjectStatistics:
        """
        Collect statistical information about the project.

        Returns:
            ProjectStatistics with collected metrics
        """
        logger.debug("statistics_collection_started")

        stats = ProjectStatistics()

        # Count files by type
        for file_path in self.project_root.rglob("*"):
            if file_path.is_file():
                # Skip hidden and special directories
                if any(part.startswith('.') for part in file_path.parts[:-1]):
                    continue
                if any(vendor in str(file_path) for vendor in self.special_dirs.get("vendor", [])):
                    continue

                stats.total_files += 1

                # Categorize by extension
                ext = file_path.suffix.lower()
                if ext in ['.py', '.pyw']:
                    stats.language_distribution["Python"] = stats.language_distribution.get("Python", 0) + 1
                    if "test" in file_path.name.lower() or "test" in str(file_path.parent).lower():
                        stats.test_files += 1
                    else:
                        stats.code_files += 1
                elif ext in ['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs']:
                    stats.language_distribution["JavaScript/TypeScript"] = \
                        stats.language_distribution.get("JavaScript/TypeScript", 0) + 1
                    if "test" in file_path.name.lower() or "spec" in file_path.name.lower():
                        stats.test_files += 1
                    else:
                        stats.code_files += 1
                elif ext in ['.json', '.yaml', '.yml', '.toml', '.ini', '.cfg']:
                    stats.config_files += 1
                elif ext in ['.md', '.rst', '.txt', '.doc', '.docx']:
                    stats.documentation_files += 1

                # Count lines (for small files only to avoid performance issues)
                if file_path.stat().st_size < 100000:  # < 100KB
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = len(f.readlines())
                            stats.total_lines += lines
                    except Exception:
                        pass

        # Calculate directory depth
        stats.max_depth = self._calculate_max_depth()

        # Calculate average file size
        if stats.code_files > 0:
            stats.average_file_size = stats.total_lines / stats.code_files

        logger.debug(
            "statistics_collection_completed",
            total_files=stats.total_files,
            code_files=stats.code_files,
            test_files=stats.test_files,
        )

        return stats

    def _calculate_max_depth(self) -> int:
        """Calculate maximum directory depth."""
        max_depth = 0

        try:
            for dirpath, _, _ in self.project_root.walk():
                depth = len(Path(dirpath).relative_to(self.project_root).parts)
                max_depth = max(max_depth, depth)
        except Exception as e:
            logger.debug("max_depth_calculation_error", error=str(e))
            # Fallback to simple calculation
            for path in self.project_root.rglob("*"):
                if path.is_dir():
                    try:
                        depth = len(path.relative_to(self.project_root).parts)
                        max_depth = max(max_depth, depth)
                    except Exception:
                        continue

        return max_depth