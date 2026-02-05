"""
Anti-Pattern Detectors

Modular detector classes for different anti-pattern categories.
"""

from warden.validation.frames.antipattern.detectors.base import BaseDetector
from warden.validation.frames.antipattern.detectors.exception_detector import ExceptionDetector
from warden.validation.frames.antipattern.detectors.class_size_detector import ClassSizeDetector
from warden.validation.frames.antipattern.detectors.debug_detector import DebugDetector
from warden.validation.frames.antipattern.detectors.todo_detector import TodoDetector

__all__ = [
    "BaseDetector",
    "ExceptionDetector",
    "ClassSizeDetector",
    "DebugDetector",
    "TodoDetector",
]
