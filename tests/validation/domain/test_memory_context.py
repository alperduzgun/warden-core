"""
Tests for ValidationMemoryContext model.

Tests memory context creation, project context, and memory entries.
"""

import pytest
from datetime import datetime

from warden.validation.domain.memory_context import (
    ValidationMemoryContext,
    MemoryEntry,
    ProjectContext,
)


class TestMemoryEntry:
    """Test MemoryEntry model."""

    def test_memory_entry_creation(self):
        """Test creating a memory entry."""
        entry = MemoryEntry(
            content="SQL injection found in payment module",
            timestamp="2024-12-24T10:00:00Z",
            relevance_score=0.95,
            metadata={"severity": "critical", "frame": "security"},
        )

        assert entry.content == "SQL injection found in payment module"
        assert entry.timestamp == "2024-12-24T10:00:00Z"
        assert entry.relevance_score == 0.95
        assert entry.metadata["severity"] == "critical"

    def test_memory_entry_defaults(self):
        """Test memory entry with defaults."""
        entry = MemoryEntry(
            content="Test memory", timestamp="2024-12-24T10:00:00Z"
        )

        assert entry.content == "Test memory"
        assert entry.relevance_score == 0.0
        assert entry.metadata == {}


class TestProjectContext:
    """Test ProjectContext model."""

    def test_project_context_creation(self):
        """Test creating project context."""
        context = ProjectContext(
            name="PaymentAPI",
            description="Payment processing service",
            primary_language="python",
            frameworks=["fastapi", "sqlalchemy"],
            libraries=["pydantic", "alembic"],
            is_web_application=False,
            is_api_service=True,
            domain="fintech",
            compliance_requirements=["PCI-DSS", "SOC2"],
        )

        assert context.name == "PaymentAPI"
        assert context.description == "Payment processing service"
        assert context.primary_language == "python"
        assert "fastapi" in context.frameworks
        assert "sqlalchemy" in context.frameworks
        assert context.is_api_service is True
        assert context.domain == "fintech"
        assert "PCI-DSS" in context.compliance_requirements

    def test_project_context_defaults(self):
        """Test project context with defaults."""
        context = ProjectContext()

        assert context.name == ""
        assert context.description == ""
        assert context.frameworks == []
        assert context.is_web_application is False
        assert context.compliance_requirements == []

    def test_project_context_to_dict(self):
        """Test project context serialization."""
        context = ProjectContext(
            name="TestApp",
            primary_language="python",
            frameworks=["django"],
            domain="healthcare",
        )

        data = context.to_dict()

        assert data["name"] == "TestApp"
        assert data["primary_language"] == "python"
        assert data["frameworks"] == ["django"]
        assert data["domain"] == "healthcare"


class TestValidationMemoryContextCreation:
    """Test ValidationMemoryContext creation."""

    def test_empty_context(self):
        """Test empty() factory method."""
        context = ValidationMemoryContext.empty()

        assert context.project_context is None
        assert context.relevant_memories == []
        assert context.similar_validations == []
        assert context.learned_patterns == []
        assert context.is_available is False

    def test_from_project_context(self):
        """Test from_project() factory method."""
        project = ProjectContext(name="TestApp", domain="ecommerce")
        context = ValidationMemoryContext.from_project(project)

        assert context.project_context is not None
        assert context.project_context.name == "TestApp"
        assert context.is_available is True

    def test_custom_context(self):
        """Test creating custom context."""
        project = ProjectContext(name="API", domain="fintech")
        memories = [
            MemoryEntry("Previous issue 1", "2024-01-01T00:00:00Z", 0.8),
            MemoryEntry("Previous issue 2", "2024-01-02T00:00:00Z", 0.7),
        ]
        patterns = ["SQL injection common in payment code"]

        context = ValidationMemoryContext(
            project_context=project,
            relevant_memories=memories,
            learned_patterns=patterns,
        )

        assert context.project_context.name == "API"
        assert len(context.relevant_memories) == 2
        assert len(context.learned_patterns) == 1
        assert context.is_available is True


class TestIsAvailableProperty:
    """Test is_available property logic."""

    def test_is_available_with_project_context(self):
        """Test is_available is True with project context."""
        project = ProjectContext(name="Test")
        context = ValidationMemoryContext(project_context=project)

        assert context.is_available is True

    def test_is_available_with_memories(self):
        """Test is_available is True with memories."""
        memory = MemoryEntry("Test", "2024-01-01T00:00:00Z")
        context = ValidationMemoryContext(relevant_memories=[memory])

        assert context.is_available is True

    def test_is_available_with_validations(self):
        """Test is_available is True with similar validations."""
        validation = MemoryEntry("Validation", "2024-01-01T00:00:00Z")
        context = ValidationMemoryContext(similar_validations=[validation])

        assert context.is_available is True

    def test_is_available_with_patterns(self):
        """Test is_available is True with learned patterns."""
        context = ValidationMemoryContext(learned_patterns=["Pattern 1"])

        assert context.is_available is True

    def test_is_not_available_when_empty(self):
        """Test is_available is False when completely empty."""
        context = ValidationMemoryContext()

        assert context.is_available is False


class TestSerialization:
    """Test serialization."""

    def test_to_dict_with_full_context(self):
        """Test to_dict() with full context."""
        project = ProjectContext(
            name="TestApp", primary_language="python", domain="fintech"
        )
        memory = MemoryEntry(
            content="Previous issue",
            timestamp="2024-01-01T00:00:00Z",
            relevance_score=0.9,
            metadata={"type": "security"},
        )

        context = ValidationMemoryContext(
            project_context=project,
            relevant_memories=[memory],
            learned_patterns=["Pattern 1", "Pattern 2"],
        )

        data = context.to_dict()

        assert data["project_context"]["name"] == "TestApp"
        assert len(data["relevant_memories"]) == 1
        assert data["relevant_memories"][0]["content"] == "Previous issue"
        assert data["relevant_memories"][0]["relevance_score"] == 0.9
        assert len(data["learned_patterns"]) == 2
        assert data["is_available"] is True

    def test_to_dict_with_empty_context(self):
        """Test to_dict() with empty context."""
        context = ValidationMemoryContext.empty()
        data = context.to_dict()

        assert data["project_context"] is None
        assert data["relevant_memories"] == []
        assert data["similar_validations"] == []
        assert data["learned_patterns"] == []
        assert data["is_available"] is False


class TestComplexScenarios:
    """Test complex memory context scenarios."""

    def test_fintech_project_with_history(self):
        """Test fintech project with historical context."""
        project = ProjectContext(
            name="PaymentGateway",
            description="Payment processing API",
            primary_language="python",
            frameworks=["fastapi", "sqlalchemy"],
            is_api_service=True,
            domain="fintech",
            compliance_requirements=["PCI-DSS", "GDPR"],
        )

        memories = [
            MemoryEntry(
                "SQL injection in payment endpoint",
                "2024-11-01T00:00:00Z",
                0.95,
                {"severity": "critical"},
            ),
            MemoryEntry(
                "Missing rate limiting on API",
                "2024-11-15T00:00:00Z",
                0.85,
                {"severity": "high"},
            ),
        ]

        patterns = [
            "Payment endpoints frequently lack input validation",
            "Database queries often vulnerable to SQL injection",
            "Rate limiting commonly missing on public APIs",
        ]

        context = ValidationMemoryContext(
            project_context=project,
            relevant_memories=memories,
            learned_patterns=patterns,
        )

        # Verify full context
        assert context.is_available is True
        assert context.project_context.domain == "fintech"
        assert "PCI-DSS" in context.project_context.compliance_requirements
        assert len(context.relevant_memories) == 2
        assert len(context.learned_patterns) == 3

        # Check memory relevance
        assert context.relevant_memories[0].relevance_score == 0.95
        assert "SQL injection" in context.relevant_memories[0].content

    def test_healthcare_project_context(self):
        """Test healthcare project with compliance requirements."""
        project = ProjectContext(
            name="HealthRecords",
            domain="healthcare",
            compliance_requirements=["HIPAA", "SOC2"],
            is_web_application=True,
        )

        patterns = [
            "PHI data must be encrypted at rest",
            "Audit logging required for all data access",
        ]

        context = ValidationMemoryContext(
            project_context=project, learned_patterns=patterns
        )

        assert context.is_available is True
        assert "HIPAA" in context.project_context.compliance_requirements
        assert any("PHI data" in p for p in context.learned_patterns)

    def test_library_project_minimal_context(self):
        """Test library project with minimal context."""
        project = ProjectContext(
            name="UtilityLib",
            primary_language="python",
            is_library=True,
        )

        context = ValidationMemoryContext(project_context=project)

        assert context.is_available is True
        assert context.project_context.is_library is True
        assert context.relevant_memories == []
        assert context.learned_patterns == []
