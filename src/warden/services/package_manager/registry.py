import json
from typing import List, Dict, Any, Optional
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

class RegistryClient:
    """
    Client for interacting with the Warden Hub/Registry.
    Simulates fetching metadata from a remote marketplace.
    """

    def __init__(self, registry_url: Optional[str] = None):
        self.registry_url = registry_url or "https://hub.warden.dev/v1"
        # Simulated data based on warden-panel marketplace mocks
        self._mock_data = [
            {
                "id": "architectural",
                "name": "Architectural Consistency",
                "version": "1.0.0",
                "author": "warden-team",
                "description": "Validates project structure, naming conventions, and SOLID principles.",
                "category": "Architecture",
                "stars": 245,
                "downloads": 12500
            },
            {
                "id": "security",
                "name": "Security Hardening",
                "version": "1.2.0",
                "author": "security-experts",
                "description": "Scans for secret leaks, insecure patterns, and OWASP violations.",
                "category": "Security",
                "stars": 512,
                "downloads": 8900
            },
            {
                "id": "performance",
                "name": "Performance Auditor",
                "version": "0.9.5",
                "author": "perf-io",
                "description": "Detects N+1 queries, heavy loops, and memory leak patterns.",
                "category": "Performance",
                "stars": 128,
                "downloads": 3200
            }
        ]

    def search(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for frames matching the query."""
        if not query:
            return self._mock_data
            
        q = query.lower()
        results = []
        for frame in self._mock_data:
            if q in frame["name"].lower() or q in frame["description"].lower() or q in frame["category"].lower():
                results.append(frame)
        return results

    def get_details(self, frame_id: str) -> Optional[Dict[str, Any]]:
        """Get full details for a specific frame."""
        for frame in self._mock_data:
            if frame["id"] == frame_id:
                return frame
        return None
