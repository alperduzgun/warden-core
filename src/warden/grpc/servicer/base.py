"""
Warden Servicer Base

Base class with shared state and initialization.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

from warden.cli_bridge.bridge import WardenBridge

# Optional: structured logging
try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class WardenServicerBase:
    """
    Base class for WardenServicer with shared state.

    Provides initialization and common utilities used by all mixins.
    """

    def __init__(
        self,
        bridge: Optional[WardenBridge] = None,
        project_root: Optional[Path] = None
    ):
        """
        Initialize servicer.

        Args:
            bridge: Existing WardenBridge instance (creates new if None)
            project_root: Project root path for bridge initialization
        """
        self.bridge = bridge or WardenBridge(project_root=project_root or Path.cwd())
        self.start_time = datetime.now()
        self.total_scans = 0
        self.total_findings = 0

        # Issue storage (in-memory for now)
        self._issues: Dict[str, dict] = {}
        self._issue_history: List[dict] = []

        # Suppression storage
        self._suppressions: Dict[str, dict] = {}

        # Report status tracking
        self._report_status: Dict[str, dict] = {}

        logger.info("grpc_servicer_initialized", endpoints=51)

    def track_issue(self, finding: Dict[str, Any]) -> None:
        """Track a finding as an issue."""
        hash_content = (
            f"{finding.get('title', '')}"
            f"{finding.get('file_path', '')}"
            f"{finding.get('line_number', 0)}"
        )
        content_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:16]

        issue_id = finding.get("id", str(uuid.uuid4()))

        if content_hash not in [i.get("hash") for i in self._issues.values()]:
            self._issues[issue_id] = {
                "id": issue_id,
                "hash": content_hash,
                "title": finding.get("title", ""),
                "description": finding.get("description", ""),
                "severity": finding.get("severity", "medium"),
                "state": "open",
                "file_path": finding.get("file_path", ""),
                "line_number": finding.get("line_number", 0),
                "code_snippet": finding.get("code_snippet", ""),
                "frame_id": finding.get("frame_id", ""),
                "first_detected": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "occurrence_count": 1
            }
        else:
            for issue in self._issues.values():
                if issue.get("hash") == content_hash:
                    issue["last_seen"] = datetime.now().isoformat()
                    issue["occurrence_count"] = issue.get("occurrence_count", 0) + 1
                    break

    def hash_finding(self, finding: Any) -> str:
        """Create hash for a proto finding."""
        hash_content = f"{finding.title}{finding.file_path}{finding.line_number}"
        return hashlib.sha256(hash_content.encode()).hexdigest()[:16]
