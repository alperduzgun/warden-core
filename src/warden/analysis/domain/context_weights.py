"""
Context-Based Weight Configurations for Quality Metrics.

Provides weight configurations for different file contexts to enable
context-aware quality scoring.
"""

from typing import Dict, Any
from warden.analysis.domain.file_context import FileContext


# Default weight configurations for each context
CONTEXT_WEIGHTS: Dict[FileContext, Dict[str, float]] = {
    FileContext.PRODUCTION: {
        "complexity": 0.25,
        "duplication": 0.20,
        "maintainability": 0.20,
        "naming": 0.15,
        "documentation": 0.15,
        "testability": 0.05,
    },
    FileContext.TEST: {
        "complexity": 0.10,  # Tests can be complex for thoroughness
        "duplication": 0.05,  # Test patterns often repeat (setup/teardown)
        "maintainability": 0.15,
        "naming": 0.10,
        "documentation": 0.05,  # Tests should be self-documenting
        "testability": 0.55,  # Test quality and coverage is critical!
    },
    FileContext.EXAMPLE: {
        "complexity": 0.05,  # Examples must be simple to understand
        "duplication": 0.10,
        "maintainability": 0.10,
        "naming": 0.25,  # Clear naming is critical for education
        "documentation": 0.40,  # Educational documentation is key
        "testability": 0.10,
    },
    FileContext.FRAMEWORK: {
        "complexity": 0.20,
        "duplication": 0.15,
        "maintainability": 0.25,  # Framework code needs long-term maintenance
        "naming": 0.20,
        "documentation": 0.15,
        "testability": 0.05,
    },
    FileContext.CONFIGURATION: {
        "complexity": 0.05,  # Config should be simple
        "duplication": 0.30,  # DRY principle is important in configs
        "maintainability": 0.30,
        "naming": 0.20,
        "documentation": 0.10,
        "testability": 0.05,
    },
    FileContext.MIGRATION: {
        "complexity": 0.10,
        "duplication": 0.10,
        "maintainability": 0.20,
        "naming": 0.10,
        "documentation": 0.20,  # Migration documentation is important
        "testability": 0.30,  # Rollback testing is critical
    },
    FileContext.FIXTURE: {
        "complexity": 0.05,  # Fixtures should be simple
        "duplication": 0.05,  # Some duplication is OK in fixtures
        "maintainability": 0.15,
        "naming": 0.25,  # Clear naming for test data
        "documentation": 0.10,
        "testability": 0.40,  # Fixture quality affects tests
    },
    FileContext.SCRIPT: {
        "complexity": 0.15,
        "duplication": 0.15,
        "maintainability": 0.20,
        "naming": 0.15,
        "documentation": 0.25,  # Script usage documentation
        "testability": 0.10,
    },
    FileContext.GENERATED: {
        "complexity": 0.10,  # Generated code complexity is less important
        "duplication": 0.10,  # Generated code may have duplication
        "maintainability": 0.10,  # Don't manually maintain generated code
        "naming": 0.10,
        "documentation": 0.10,
        "testability": 0.50,  # Generated code should still work correctly
    },
    FileContext.VENDOR: {
        # Vendor code typically shouldn't be analyzed, but if it is:
        "complexity": 0.05,
        "duplication": 0.05,
        "maintainability": 0.05,
        "naming": 0.05,
        "documentation": 0.05,
        "testability": 0.75,  # Main concern is that it works
    },
    FileContext.DOCUMENTATION: {
        # Documentation files have minimal code
        "complexity": 0.05,
        "duplication": 0.05,
        "maintainability": 0.10,
        "naming": 0.10,
        "documentation": 0.60,  # Documentation quality is key
        "testability": 0.10,
    },
    FileContext.UNKNOWN: {
        # Default balanced weights for unknown context
        "complexity": 0.20,
        "duplication": 0.20,
        "maintainability": 0.20,
        "naming": 0.15,
        "documentation": 0.15,
        "testability": 0.10,
    },
}


def get_context_weights(context: FileContext) -> Dict[str, float]:
    """
    Get weight configuration for a specific context.

    Args:
        context: File context enum value

    Returns:
        Dictionary of metric weights
    """
    return CONTEXT_WEIGHTS.get(
        context,
        CONTEXT_WEIGHTS[FileContext.UNKNOWN]
    )


def calculate_weighted_score(
    scores: Dict[str, float],
    context: FileContext
) -> float:
    """
    Calculate weighted overall score based on context.

    Args:
        scores: Individual metric scores (0-10 scale)
        context: File context for weight selection

    Returns:
        Weighted overall score (0-10 scale)
    """
    weights = get_context_weights(context)

    # Calculate weighted sum
    weighted_sum = 0.0
    total_weight = 0.0

    for metric, score in scores.items():
        if metric in weights:
            weight = weights[metric]
            weighted_sum += score * weight
            total_weight += weight

    # Avoid division by zero
    if total_weight == 0:
        return 5.0  # Default middle score

    # Calculate weighted average
    overall_score = weighted_sum / total_weight

    # Ensure score is within bounds
    return max(0.0, min(10.0, overall_score))


def get_weight_explanation(context: FileContext) -> Dict[str, str]:
    """
    Get human-readable explanations for weight choices.

    Args:
        context: File context enum value

    Returns:
        Dictionary of metric -> explanation
    """
    explanations = {
        FileContext.PRODUCTION: {
            "complexity": "Production code should be maintainable and understandable",
            "duplication": "DRY principle is important for production maintainability",
            "maintainability": "Long-term maintenance is critical for production",
            "naming": "Clear naming prevents production bugs",
            "documentation": "Documentation helps onboarding and maintenance",
            "testability": "Production code must be testable",
        },
        FileContext.TEST: {
            "complexity": "Test complexity is acceptable for thorough testing",
            "duplication": "Test patterns (setup/teardown) naturally repeat",
            "maintainability": "Tests need some maintenance but less critical",
            "naming": "Test names should describe what they test",
            "documentation": "Tests should be self-documenting through names",
            "testability": "Test quality and coverage is the primary concern",
        },
        FileContext.EXAMPLE: {
            "complexity": "Examples must be simple for learning",
            "duplication": "Some duplication OK if it aids understanding",
            "maintainability": "Examples are often one-time code",
            "naming": "Clear naming is critical for education",
            "documentation": "Educational comments are essential",
            "testability": "Examples focus on demonstrating concepts",
        },
        FileContext.FRAMEWORK: {
            "complexity": "Framework code needs to handle many cases",
            "duplication": "Frameworks should provide reusable components",
            "maintainability": "Frameworks need long-term maintenance",
            "naming": "Clear APIs are critical for frameworks",
            "documentation": "Framework documentation enables adoption",
            "testability": "Frameworks are typically well-tested elsewhere",
        },
    }

    return explanations.get(context, {})


def suggest_weight_adjustments(
    project_type: str,
    framework: str
) -> Dict[FileContext, Dict[str, float]]:
    """
    Suggest weight adjustments based on project characteristics.

    Args:
        project_type: Type of project (library, application, etc.)
        framework: Detected framework

    Returns:
        Suggested weight adjustments per context
    """
    adjustments: Dict[FileContext, Dict[str, float]] = {}

    # Library projects need more documentation
    if project_type == "library":
        adjustments[FileContext.PRODUCTION] = {
            "documentation": 0.25,  # Increase from 0.15
            "testability": 0.10,  # Increase from 0.05
            "naming": 0.20,  # Increase from 0.15
            "complexity": 0.20,  # Decrease from 0.25
            "duplication": 0.15,  # Decrease from 0.20
            "maintainability": 0.10,  # Decrease from 0.20
        }

    # API projects need clear interfaces
    elif project_type == "api":
        adjustments[FileContext.PRODUCTION] = {
            "naming": 0.25,  # Increase for clear endpoints
            "documentation": 0.20,  # API documentation critical
            "testability": 0.15,  # API testing important
            "complexity": 0.15,  # Decrease
            "duplication": 0.15,  # Decrease
            "maintainability": 0.10,  # Decrease
        }

    # FastAPI projects have built-in validation
    if framework == "fastapi":
        adjustments[FileContext.PRODUCTION] = adjustments.get(FileContext.PRODUCTION, {})
        adjustments[FileContext.PRODUCTION]["testability"] = 0.20  # FastAPI encourages testing

    # Django projects have specific patterns
    elif framework == "django":
        adjustments[FileContext.MIGRATION] = {
            "testability": 0.40,  # Django migration testing is critical
            "documentation": 0.30,  # Migration docs very important
            "complexity": 0.05,
            "duplication": 0.05,
            "maintainability": 0.15,
            "naming": 0.05,
        }

    return adjustments