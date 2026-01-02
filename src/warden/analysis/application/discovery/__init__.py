"""
Discovery module for Warden.

Provides file discovery, classification, and framework detection capabilities.

Usage:
    >>> from warden.analysis.application.discovery import FileDiscoverer
    >>> discoverer = FileDiscoverer(root_path="/path/to/project")
    >>> result = await discoverer.discover_async()
    >>> print(f"Found {result.stats.total_files} files")
"""

from warden.analysis.application.discovery.models import (
    FileType,
    Framework,
    DiscoveredFile,
    FrameworkDetectionResult,
    DiscoveryStats,
    DiscoveryResult,
)
from warden.analysis.application.discovery.classifier import FileClassifier
from warden.analysis.application.discovery.gitignore_filter import GitignoreFilter, create_gitignore_filter
from warden.analysis.application.discovery.framework_detector import FrameworkDetector, detect_frameworks
from warden.analysis.application.discovery.discoverer import FileDiscoverer, discover_project_files

__all__ = [
    # Models
    "FileType",
    "Framework",
    "DiscoveredFile",
    "FrameworkDetectionResult",
    "DiscoveryStats",
    "DiscoveryResult",
    # Classifier
    "FileClassifier",
    # Gitignore
    "GitignoreFilter",
    "create_gitignore_filter",
    # Framework detection
    "FrameworkDetector",
    "detect_frameworks",
    # Main discoverer
    "FileDiscoverer",
    "discover_project_files",
]
