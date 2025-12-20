"""
Discovery module for Warden.

Provides file discovery, classification, and framework detection capabilities.

Usage:
    >>> from warden.analyzers.discovery import FileDiscoverer
    >>> discoverer = FileDiscoverer(root_path="/path/to/project")
    >>> result = await discoverer.discover_async()
    >>> print(f"Found {result.stats.total_files} files")
"""

from warden.analyzers.discovery.models import (
    FileType,
    Framework,
    DiscoveredFile,
    FrameworkDetectionResult,
    DiscoveryStats,
    DiscoveryResult,
)
from warden.analyzers.discovery.classifier import FileClassifier
from warden.analyzers.discovery.gitignore_filter import GitignoreFilter, create_gitignore_filter
from warden.analyzers.discovery.framework_detector import FrameworkDetector, detect_frameworks
from warden.analyzers.discovery.discoverer import FileDiscoverer, discover_project_files

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
