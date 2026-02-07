"""
Spec Decision Cache for Semantic Matching.

Persists LLM matching decisions to disk to avoid redundant API calls
and improve performance on subsequent runs.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SpecDecisionCache:
    """
    Persists semantic match decisions.
    
    Structure:
    {
        "MatchV1:create_invoice:submit_payment": {
            "matched": true,
            "provider_op": "submit_payment",
            "confidence": 0.9,
            "reasoning": "Both create invoice and submit payment imply generic transaction creation context..."
        },
        "MatchV1:delete_user:get_status": {
            "matched": false,
            "reasoning": "Delete and Get are opposite operations."
        }
    }
    """

    def __init__(self, cache_file: Path = Path(".warden/memory/spec_matches.json")):
        self.cache_file = cache_file
        self._cache: Dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        try:
            if self.cache_file.exists():
                text = self.cache_file.read_text(encoding="utf-8")
                self._cache = json.loads(text)
                logger.debug("spec_cache_loaded", entries=len(self._cache))
        except Exception as e:
            logger.warning("spec_cache_load_failed", error=str(e))
            self._cache = {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("spec_cache_save_failed", error=str(e))

    def _get_key(self, consumer_op: str, provider_op: str) -> str:
        """Normalize key for lookup."""
        return f"MatchV1:{consumer_op}:{provider_op}"

    def get_decision(self, consumer_op: str, provider_op: str) -> Optional[Dict[str, Any]]:
        """
        Get cached decision.
        
        Returns:
            Dict with decision data if found, else None.
        """
        key = self._get_key(consumer_op, provider_op)
        return self._cache.get(key)

    def cache_decision(
        self, 
        consumer_op: str, 
        provider_op: str, 
        matched: bool, 
        reasoning: str = "",
        confidence: float = 1.0
    ) -> None:
        """
        Cache a decision.
        """
        key = self._get_key(consumer_op, provider_op)
        entry = {
            "matched": matched,
            "provider_op": provider_op,
            "reasoning": reasoning,
            "confidence": confidence,
            "timestamp": "iso-timestamp-placeholder" # Ideally real timestamp
        }
        self._cache[key] = entry
        self._save_cache()
