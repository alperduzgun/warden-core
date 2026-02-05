"""
Project Statistics Collection Module.

Collects statistical information about the project during PRE-ANALYSIS phase.
"""

from pathlib import Path
from typing import Dict, List, Optional
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
        self._injected_files: Optional[List[Path]] = None

    def _categorize_file(self, file_path: Path, stats: ProjectStatistics):
        """
        Categorize a single file and update statistics.
        Uses central LanguageRegistry.
        """
        from warden.shared.languages.registry import LanguageRegistry
        from warden.ast.domain.enums import CodeLanguage
        
        lang_enum = LanguageRegistry.get_language_from_path(file_path)

        if lang_enum != CodeLanguage.UNKNOWN:
            try:
                size = file_path.stat().st_size
            except (FileNotFoundError, PermissionError, OSError):
                size = 0
            
            stats.language_distribution[lang_enum] = stats.language_distribution.get(lang_enum, 0) + 1
            stats.language_bytes[lang_enum] = stats.language_bytes.get(lang_enum, 0) + size
            
            # Test file heuristics
            if any(x in file_path.name.lower() for x in ["test", "spec"]):
                stats.test_files += 1
            else:
                stats.code_files += 1
        
        # Config & Docs
        ext = file_path.suffix.lower()
        if ext in ['.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.xml', '.lock']:
            stats.config_files += 1
        elif ext in ['.md', '.rst', '.txt', '.doc', '.docx']:
            stats.documentation_files += 1

    async def collect_async(self, all_files: Optional[List[Path]] = None) -> ProjectStatistics:
        """
        Collect statistical information about the project.
        """
        self._injected_files = all_files
        logger.debug("statistics_collection_started")

        stats = ProjectStatistics()

        # Files must be pre-filtered by caller (Respects .gitignore)
        all_files_to_scan = all_files if all_files is not None else list(self.project_root.rglob("*"))
        
        # Filter for files only
        valid_files = [f for f in all_files_to_scan if f.is_file()]

        # Try Rust-based metadata extraction (FAST)
        try:
            from warden import warden_core_rust
            paths = [str(f) for f in valid_files]
            rust_stats = warden_core_rust.get_file_stats(paths)
            
            for s in rust_stats:
                file_path = Path(s.path)
                stats.total_files += 1
                self._categorize_file(file_path, stats)
                stats.total_lines += s.line_count
                
            logger.debug("rust_stats_collection_completed", count=len(rust_stats))
            return stats # Success early return

        except (ImportError, Exception) as e:
            if not isinstance(e, ImportError):
                logger.warning("rust_stats_failed", error=str(e))
            
            # Fallback (Existing Python Logic)
            for file_path in valid_files:
                stats.total_files += 1
                self._categorize_file(file_path, stats)

                # Count lines (for small files only)
                try:
                    file_size = file_path.stat().st_size
                    if file_size < 200000:  # < 200KB
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            stats.total_lines += sum(1 for _ in f)
                except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
                    pass  # Skip unreadable files

        # Calculate directory depth
        stats.max_depth = self._calculate_max_depth()

        # Calculate average file complexity/size proxy
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
        all_files = self._injected_files or []
                
        for path in all_files:
            try:
                # relative_to can fail if path is outside root (unlikely here)
                depth = len(path.parent.relative_to(self.project_root).parts)
                max_depth = max(max_depth, depth)
            except ValueError:
                # Path not relative to project root - skip
                continue

        return max_depth