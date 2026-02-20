"""
Intelligence Saver Service.

Saves project intelligence to disk for CI consumption.
Used during `warden init` and `warden refresh` commands.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from warden.analysis.domain.intelligence import (
    FileException,
    ModuleInfo,
    ProjectIntelligence,
    SecurityPosture,
)

if TYPE_CHECKING:
    from warden.analysis.application.dependency_graph import DependencyGraph
    from warden.analysis.domain.code_graph import CodeGraph, GapReport

logger = structlog.get_logger(__name__)


class IntelligenceSaver:
    """
    Saves project intelligence to the `.warden/intelligence/` directory.

    Creates versioned JSON files that can be loaded by IntelligenceLoader
    in CI environments without LLM dependency.
    """

    INTELLIGENCE_DIR = ".warden/intelligence"
    INTELLIGENCE_FILE = "project.json"

    def __init__(self, project_root: Path):
        """
        Initialize the saver.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = Path(project_root).resolve()
        self.intelligence_dir = self.project_root / self.INTELLIGENCE_DIR
        self.intelligence_path = self.intelligence_dir / self.INTELLIGENCE_FILE

    def ensure_directory(self) -> bool:
        """
        Ensure the intelligence directory exists.

        Returns:
            True if directory exists or was created, False on error.
        """
        try:
            self.intelligence_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error("intelligence_dir_creation_failed", error=str(e))
            return False

    def save(
        self,
        purpose: str,
        architecture: str,
        security_posture: SecurityPosture,
        module_map: dict[str, ModuleInfo],
        file_exceptions: dict[str, FileException] | None = None,
        project_name: str | None = None,
    ) -> bool:
        """
        Save project intelligence to disk.

        Args:
            purpose: Project purpose description.
            architecture: Architecture description.
            security_posture: Security posture classification.
            module_map: Dictionary mapping module names to ModuleInfo.
            file_exceptions: Optional dictionary of file exceptions.
            project_name: Optional project name (defaults to directory name).

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.ensure_directory():
            return False

        try:
            # Build ProjectIntelligence object
            intelligence = ProjectIntelligence(
                schema_version="1.0.0",
                generated_at=datetime.now(timezone.utc).isoformat(),
                generated_by="warden",
                project_name=project_name or self.project_root.name,
                purpose=purpose,
                architecture=architecture,
                security_posture=security_posture,
                modules=module_map,
                exceptions=file_exceptions or {},
                llm_claims_count=len(module_map),
                verified_claims_count=0,  # Will be updated by verification step
            )

            # Serialize and save
            data = intelligence.to_json()
            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                "intelligence_saved",
                path=str(self.intelligence_path),
                modules=len(module_map),
                exceptions=len(file_exceptions or {}),
            )
            return True

        except Exception as e:
            logger.error("intelligence_save_failed", error=str(e))
            return False

    def save_intelligence(self, intelligence: ProjectIntelligence) -> bool:
        """
        Save a complete ProjectIntelligence object to disk.

        Args:
            intelligence: Complete ProjectIntelligence object.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.ensure_directory():
            return False

        try:
            # Update generation timestamp
            intelligence.generated_at = datetime.now(timezone.utc).isoformat()

            data = intelligence.to_json()
            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                "intelligence_saved",
                path=str(self.intelligence_path),
                modules=len(intelligence.modules),
                quality_score=intelligence.quality_score,
            )
            return True

        except Exception as e:
            logger.error("intelligence_save_failed", error=str(e))
            return False

    def update_verification_counts(self, verified_count: int, total_claims: int | None = None) -> bool:
        """
        Update verification counts in existing intelligence file.

        Called after AST verification pass.

        Args:
            verified_count: Number of claims verified by AST.
            total_claims: Optional total claims count (uses existing if None).

        Returns:
            True if updated successfully, False otherwise.
        """
        if not self.intelligence_path.exists():
            logger.warning("intelligence_file_not_found_for_update")
            return False

        try:
            with open(self.intelligence_path, encoding="utf-8") as f:
                data = json.load(f)

            data["verifiedClaimsCount"] = verified_count
            if total_claims is not None:
                data["llmClaimsCount"] = total_claims

            # Update timestamp
            data["generatedAt"] = datetime.now(timezone.utc).isoformat()

            content = json.dumps(data, indent=2, ensure_ascii=False)

            with open(self.intelligence_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.debug(
                "verification_counts_updated",
                verified=verified_count,
                total=total_claims or data.get("llmClaimsCount", 0),
            )
            return True

        except Exception as e:
            logger.error("verification_update_failed", error=str(e))
            return False

    def exists(self) -> bool:
        """Check if intelligence file exists."""
        return self.intelligence_path.exists()

    def get_last_modified(self) -> datetime | None:
        """
        Get last modification time of intelligence file.

        Returns:
            datetime of last modification, or None if file doesn't exist.
        """
        if not self.intelligence_path.exists():
            return None

        try:
            stat = self.intelligence_path.stat()
            return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except Exception:
            return None

    # --- Atomic write helper (O5 fix: temp -> os.replace) ---

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically: write to temp file then replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".warden_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        except BaseException:
            # Clean up temp file on any error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # --- Graph export methods (Phase 1 + 2) ---

    def save_dependency_graph(self, graph: DependencyGraph) -> bool:
        """
        Save DependencyGraph to .warden/intelligence/dependency_graph.json.

        Includes orphan detection and forward/reverse integrity check.

        Args:
            graph: DependencyGraph instance with populated _forward_graph/_reverse_graph.

        Returns:
            True if saved successfully.
        """
        if not self.ensure_directory():
            return False

        try:
            project_root = graph.project_root

            def _rel(p: Path) -> str:
                try:
                    return str(p.relative_to(project_root))
                except ValueError:
                    return str(p)

            # Serialize forward and reverse graphs
            forward: dict[str, list[str]] = {}
            for src, deps in graph._forward_graph.items():
                forward[_rel(src)] = sorted(_rel(d) for d in deps)

            reverse: dict[str, list[str]] = {}
            for tgt, dependents in graph._reverse_graph.items():
                reverse[_rel(tgt)] = sorted(_rel(d) for d in dependents)

            # Orphan detection: nodes with zero edges in both directions
            all_nodes = set(forward.keys()) | set(reverse.keys())
            for deps in forward.values():
                all_nodes.update(deps)
            for deps in reverse.values():
                all_nodes.update(deps)

            # Only count nodes that have at least one actual edge (non-empty list)
            nodes_with_edges = {k for k, v in forward.items() if v} | {k for k, v in reverse.items() if v}
            orphan_files = sorted(all_nodes - nodes_with_edges)

            # Integrity: every forward target should appear in reverse
            missing_targets = []
            for _src, deps in forward.items():
                for dep in deps:
                    if dep not in reverse:
                        missing_targets.append(dep)

            data = {
                "schema_version": "1.0.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "forward": forward,
                "reverse": reverse,
                "orphan_files": orphan_files,
                "stats": {
                    "total_files": len(all_nodes),
                    "total_edges": sum(len(v) for v in forward.values()),
                    "orphan_count": len(orphan_files),
                },
                "integrity": {
                    "forward_reverse_match": len(missing_targets) == 0,
                    "missing_targets": sorted(set(missing_targets)),
                },
            }

            path = self.intelligence_dir / "dependency_graph.json"
            self._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

            logger.info(
                "dependency_graph_saved",
                path=str(path),
                files=data["stats"]["total_files"],
                edges=data["stats"]["total_edges"],
                orphans=len(orphan_files),
            )
            return True

        except Exception as e:
            logger.error("dependency_graph_save_failed", error=str(e))
            return False

    def save_code_graph(self, code_graph: CodeGraph) -> bool:
        """
        Save CodeGraph to .warden/intelligence/code_graph.json.

        Args:
            code_graph: CodeGraph instance.

        Returns:
            True if saved successfully.
        """
        if not self.ensure_directory():
            return False

        try:
            data = code_graph.to_json()
            data["generated_at"] = datetime.now(timezone.utc).isoformat()

            path = self.intelligence_dir / "code_graph.json"
            self._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

            graph_stats = code_graph.stats()
            logger.info(
                "code_graph_saved",
                path=str(path),
                nodes=graph_stats["total_nodes"],
                edges=graph_stats["total_edges"],
            )
            return True

        except Exception as e:
            logger.error("code_graph_save_failed", error=str(e))
            return False

    def save_gap_report(self, gap_report: GapReport) -> bool:
        """
        Save GapReport to .warden/intelligence/gap_report.json.

        Args:
            gap_report: GapReport instance.

        Returns:
            True if saved successfully.
        """
        if not self.ensure_directory():
            return False

        try:
            data = gap_report.to_json()
            data["generated_at"] = datetime.now(timezone.utc).isoformat()

            path = self.intelligence_dir / "gap_report.json"
            self._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

            logger.info(
                "gap_report_saved",
                path=str(path),
                coverage=gap_report.coverage,
                orphan_files=len(gap_report.orphan_files),
                broken_imports=len(gap_report.broken_imports),
            )
            return True

        except Exception as e:
            logger.error("gap_report_save_failed", error=str(e))
            return False

    def save_chain_validation(self, chain_validation: Any) -> bool:
        """
        Save LSP ChainValidation to .warden/intelligence/chain_validation.json.

        Args:
            chain_validation: ChainValidation instance (from LSP audit).

        Returns:
            True if saved successfully.
        """
        if not self.ensure_directory():
            return False

        try:
            data = chain_validation.to_json() if hasattr(chain_validation, "to_json") else {}
            data["generated_at"] = datetime.now(timezone.utc).isoformat()

            path = self.intelligence_dir / "chain_validation.json"
            self._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))

            logger.info("chain_validation_saved", path=str(path))
            return True

        except Exception as e:
            logger.error("chain_validation_save_failed", error=str(e))
            return False
