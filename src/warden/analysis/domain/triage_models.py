"""
Domain models for the Adaptive Hybrid Triage system.
Defines risk scores, lanes, and triage decisions with strict validation.
"""

from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, List

class TriageLane(str, Enum):
    """Routing lanes for analysis depth."""
    FAST = "fast_lane"      # Regex/Rule-based (0 cost, <10ms)
    MIDDLE = "middle_lane"  # Local LLM Deep Scan (0 cost, ~2s)
    DEEP = "deep_lane"      # Cloud API Analysis ($ cost, ~15s)

class RiskScore(BaseModel):
    """Risk assessment for a specific file."""
    score: float = Field(..., ge=0, le=10, description="Risk score from 0 to 10")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the score")
    reasoning: str = Field(..., description="Explanation for the assigned score")
    category: str = Field(..., description="Categorization (e.g., 'auth', 'dto', 'ui')")
    
    @validator('score', pre=True)
    def normalize_score(cls, v):
        """
        Hardens the score against common LLM hallucinations:
        1. 100-scale scores (30 -> 3.0)
        2. Float strings ("8.5" -> 8.5)
        3. Extreme out-of-range values
        """
        try:
            val = float(v)
            # Chaos Rule: If LLM returns 10-100, assume it's a 100-scale score
            if val > 10 and val <= 100:
                val = val / 10.0
            
            # Clamp to [0, 10]
            return max(0.0, min(10.0, val))
        except (ValueError, TypeError):
            return 5.0 # Safe default on catastrophic failure

    @validator('confidence', pre=True)
    def normalize_confidence(cls, v):
        """
        Hardens confidence against 100-scale hallucinations (e.g. 95.0 -> 0.95).
        """
        try:
            val = float(v)
            if val > 1.0 and val <= 100.0:
                val = val / 100.0
            return max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            return 0.5 # Default middle confidence

class TriageDecision(BaseModel):
    """Final routing decision for a file."""
    file_path: str
    lane: TriageLane
    risk_score: RiskScore
    processing_time_ms: float
    is_cached: bool = False
    metadata: Optional[dict] = Field(default_factory=dict)
