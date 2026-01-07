"""
Contract extractors for different platforms.

Each extractor uses tree-sitter to parse source code and extract
API contract information (operations, models, enums).
"""

from warden.validation.frames.spec.extractors.base import (
    BaseContractExtractor,
    ExtractorRegistry,
    get_extractor,
)

# Import extractors to trigger registration
from warden.validation.frames.spec.extractors.flutter_extractor import FlutterExtractor

__all__ = [
    "BaseContractExtractor",
    "ExtractorRegistry",
    "get_extractor",
    "FlutterExtractor",
]
