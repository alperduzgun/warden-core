"""
Tests for fortification phase LLM integration.

Verifies:
1. Fortification uses system_prompt parameter in LLM calls
2. Fortification passes correct tier parameter (use_fast_tier)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.fortification.application.fortification_phase import FortificationPhase
from warden.llm.types import LlmResponse


class TestFortificationLlmIntegration:
    """Test that fortification phase passes correct parameters to LLM."""

    @pytest.mark.asyncio
    async def test_fortification_uses_system_prompt(self):
        """Test that _generate_llm_fixes_async passes system_prompt to LLM."""
        # Create mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        # Create fortification phase
        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        # Create test issues
        issues = [
            {
                "id": "ISSUE-001",
                "type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "critical",
                "message": "SQL injection vulnerability",
            }
        ]

        # Call _generate_llm_fixes_async
        await phase._generate_llm_fixes_async("sql_injection", issues)

        # Assert: complete_async was called with system_prompt
        mock_llm.complete_async.assert_called_once()
        call_kwargs = mock_llm.complete_async.call_args.kwargs

        assert "system_prompt" in call_kwargs
        system_prompt = call_kwargs["system_prompt"]
        assert "security" in system_prompt.lower()
        assert "senior security engineer" in system_prompt.lower() or "security engineer" in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_fortification_passes_tier_parameter_fast(self):
        """Test that _generate_llm_fixes_async uses fast tier for simple issues."""
        # Create mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        # Create fortification phase
        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        # Create test issues for hardcoded_secret (should use fast tier)
        issues = [
            {
                "id": "ISSUE-001",
                "type": "hardcoded_secret",
                "file_path": "config.py",
                "line_number": 5,
                "severity": "high",
                "message": "Hardcoded secret detected",
            }
        ]

        # Call _generate_llm_fixes_async
        await phase._generate_llm_fixes_async("hardcoded_secret", issues)

        # Assert: complete_async was called with use_fast_tier=True
        mock_llm.complete_async.assert_called_once()
        call_kwargs = mock_llm.complete_async.call_args.kwargs

        assert "use_fast_tier" in call_kwargs
        assert call_kwargs["use_fast_tier"] is True

    @pytest.mark.asyncio
    async def test_fortification_passes_tier_parameter_smart(self):
        """Test that _generate_llm_fixes_async uses smart tier for complex issues."""
        # Create mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        # Create fortification phase
        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        # Create test issues for sql_injection (should use smart tier)
        issues = [
            {
                "id": "ISSUE-001",
                "type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "critical",
                "message": "SQL injection vulnerability",
            }
        ]

        # Call _generate_llm_fixes_async
        await phase._generate_llm_fixes_async("sql_injection", issues)

        # Assert: complete_async was called with use_fast_tier=False
        mock_llm.complete_async.assert_called_once()
        call_kwargs = mock_llm.complete_async.call_args.kwargs

        assert "use_fast_tier" in call_kwargs
        assert call_kwargs["use_fast_tier"] is False


class TestFortificationTierSelection:
    """Test that fortification selects the correct tier for different issue types."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "issue_type,expected_fast_tier",
        [
            ("hardcoded_secret", True),  # Simple fix
            ("weak_crypto", True),  # Simple fix
            ("sql_injection", False),  # Complex analysis
            ("xss", False),  # Complex analysis
            ("path_traversal", False),  # Complex analysis
        ],
    )
    async def test_fortification_tier_selection_by_issue_type(self, issue_type, expected_fast_tier):
        """Test that fortification selects correct tier based on issue type."""
        # Create mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        # Create fortification phase
        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        # Create test issues
        issues = [
            {
                "id": "ISSUE-001",
                "type": issue_type,
                "file_path": "app.py",
                "line_number": 10,
                "severity": "high",
                "message": f"{issue_type} vulnerability",
            }
        ]

        # Call _generate_llm_fixes_async
        await phase._generate_llm_fixes_async(issue_type, issues)

        # Assert: correct tier used
        call_kwargs = mock_llm.complete_async.call_args.kwargs
        assert call_kwargs["use_fast_tier"] == expected_fast_tier


class TestFortificationLlmParameters:
    """Test that fortification passes all required LLM parameters."""

    @pytest.mark.asyncio
    async def test_fortification_passes_prompt_parameter(self):
        """Test that fortification passes prompt parameter to LLM."""
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        issues = [
            {
                "id": "ISSUE-001",
                "type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "critical",
                "message": "SQL injection vulnerability",
                "code": "query = f'SELECT * FROM users WHERE id = {user_id}'",
            }
        ]

        await phase._generate_llm_fixes_async("sql_injection", issues)

        # Assert: prompt parameter exists
        call_kwargs = mock_llm.complete_async.call_args.kwargs
        assert "prompt" in call_kwargs
        prompt = call_kwargs["prompt"]
        assert len(prompt) > 0
        assert "sql" in prompt.lower() or "injection" in prompt.lower()

    @pytest.mark.asyncio
    async def test_fortification_passes_model_parameter_from_context(self):
        """Test that fortification passes model parameter from context.llm_config."""
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(
            return_value=LlmResponse(
                content='{"fixes": []}',
                success=True,
            )
        )

        # Create context with llm_config
        context = {
            "llm_config": {
                "smart_model": "gpt-4",
            }
        }

        phase = FortificationPhase(
            config={"use_llm": True},
            context=context,
            llm_service=mock_llm,
        )

        issues = [
            {
                "id": "ISSUE-001",
                "type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "critical",
                "message": "SQL injection",
            }
        ]

        await phase._generate_llm_fixes_async("sql_injection", issues)

        # Assert: model parameter is passed
        call_kwargs = mock_llm.complete_async.call_args.kwargs
        assert "model" in call_kwargs
        assert call_kwargs["model"] == "gpt-4"


class TestFortificationLlmFallback:
    """Test that fortification falls back to rule-based fixes on LLM failure."""

    @pytest.mark.asyncio
    async def test_fortification_falls_back_on_llm_error(self):
        """Test that fortification falls back to rule-based fixes if LLM fails."""
        # Create mock LLM service that raises exception
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(side_effect=Exception("LLM service unavailable"))

        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        issues = [
            {
                "id": "ISSUE-001",
                "type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "critical",
                "message": "SQL injection vulnerability",
            }
        ]

        # Should not raise, should fall back to rule-based
        fixes = await phase._generate_llm_fixes_async("sql_injection", issues)

        # Assert: Rule-based fixes were returned
        assert len(fixes) > 0
        assert fixes[0].get("title") == "Use Parameterized Queries"

    @pytest.mark.asyncio
    async def test_fortification_falls_back_on_empty_response(self):
        """Test that fortification falls back if LLM returns empty response."""
        # Create mock LLM service that returns None
        mock_llm = MagicMock()
        mock_llm.complete_async = AsyncMock(return_value=None)

        phase = FortificationPhase(
            config={"use_llm": True},
            context={},
            llm_service=mock_llm,
        )

        issues = [
            {
                "id": "ISSUE-001",
                "type": "xss",
                "file_path": "template.js",
                "line_number": 5,
                "severity": "high",
                "message": "XSS vulnerability",
            }
        ]

        # Should fall back to rule-based
        fixes = await phase._generate_llm_fixes_async("xss", issues)

        # Assert: Rule-based fixes were returned
        assert len(fixes) > 0
        assert fixes[0].get("title") == "Escape HTML Output"
