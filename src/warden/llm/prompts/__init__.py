"""
LLM Prompts for Code Analysis and Classification
"""

from .analysis import ANALYSIS_SYSTEM_PROMPT, generate_analysis_request
from .classification import CLASSIFICATION_SYSTEM_PROMPT, generate_classification_request

__all__ = [
    "ANALYSIS_SYSTEM_PROMPT",
    "generate_analysis_request",
    "CLASSIFICATION_SYSTEM_PROMPT",
    "generate_classification_request",
]
