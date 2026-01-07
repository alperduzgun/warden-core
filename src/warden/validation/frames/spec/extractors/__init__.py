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
from warden.validation.frames.spec.extractors.aspnetcore_extractor import AspNetCoreExtractor
from warden.validation.frames.spec.extractors.fastapi_extractor import FastAPIExtractor
from warden.validation.frames.spec.extractors.springboot_extractor import SpringBootExtractor
from warden.validation.frames.spec.extractors.angular_extractor import AngularExtractor
from warden.validation.frames.spec.extractors.vue_extractor import VueExtractor
from warden.validation.frames.spec.extractors.nestjs_extractor import NestJSExtractor

__all__ = [
    "BaseContractExtractor",
    "ExtractorRegistry",
    "get_extractor",
    "FlutterExtractor",
    "AspNetCoreExtractor",
    "FastAPIExtractor",
    "SpringBootExtractor",
    "AngularExtractor",
    "VueExtractor",
    "NestJSExtractor",
]
