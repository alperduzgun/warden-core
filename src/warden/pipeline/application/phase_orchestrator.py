"""
Phase Orchestrator for 6-phase pipeline.

This module provides backward compatibility by importing from the new orchestrator module.
The actual implementation has been refactored into separate modules for better maintainability.
"""

# Import from the new modular structure
from .orchestrator import PhaseOrchestrator

# Export for backward compatibility
__all__ = ["PhaseOrchestrator"]