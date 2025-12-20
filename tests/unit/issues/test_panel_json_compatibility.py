"""
Panel JSON compatibility tests for Issue models.

CRITICAL: These tests verify that our Python models serialize/deserialize
correctly with Panel TypeScript types.

Panel Source: /warden-panel-development/src/lib/types/warden.ts
"""

from datetime import datetime
import pytest

from warden.issues.domain.models import WardenIssue, StateTransition
from warden.issues.domain.enums import IssueSeverity, IssueState


class TestStateTransitionPanelJSON:
    """Test StateTransition Panel JSON compatibility."""

    def test_to_json_camel_case(self) -> None:
        """Ensure to_json() returns camelCase keys."""
        transition = StateTransition(
            from_state=IssueState.OPEN,
            to_state=IssueState.RESOLVED,
            timestamp=datetime(2025, 12, 20, 10, 30, 0),
            transitioned_by="user",
            comment="Fixed the bug",
        )

        json_data = transition.to_json()

        # Check camelCase (Panel expectation)
        assert "fromState" in json_data
        assert "toState" in json_data
        assert "transitionedBy" in json_data

        # Check NOT snake_case
        assert "from_state" not in json_data
        assert "to_state" not in json_data
        assert "transitioned_by" not in json_data

    def test_enum_values_are_integers(self) -> None:
        """Ensure Enum values are serialized as integers (not strings)."""
        transition = StateTransition(
            from_state=IssueState.OPEN,
            to_state=IssueState.RESOLVED,
            timestamp=datetime(2025, 12, 20, 10, 30, 0),
            transitioned_by="system",
            comment="Auto-resolved",
        )

        json_data = transition.to_json()

        # Panel expects integers
        assert json_data["fromState"] == 0  # IssueState.OPEN = 0
        assert json_data["toState"] == 1  # IssueState.RESOLVED = 1
        assert isinstance(json_data["fromState"], int)
        assert isinstance(json_data["toState"], int)

    def test_date_is_iso8601_string(self) -> None:
        """Ensure dates are serialized as ISO 8601 strings."""
        transition = StateTransition(
            from_state=IssueState.OPEN,
            to_state=IssueState.RESOLVED,
            timestamp=datetime(2025, 12, 20, 10, 30, 0),
            transitioned_by="user",
            comment="Test",
        )

        json_data = transition.to_json()

        assert isinstance(json_data["timestamp"], str)
        assert json_data["timestamp"] == "2025-12-20T10:30:00"

    def test_roundtrip_json(self) -> None:
        """Ensure to_json() → from_json() roundtrip works correctly."""
        original = StateTransition(
            from_state=IssueState.OPEN,
            to_state=IssueState.SUPPRESSED,
            timestamp=datetime(2025, 12, 20, 10, 30, 0),
            transitioned_by="ci/cd",
            comment="CI detected false positive",
        )

        # Serialize
        json_data = original.to_json()

        # Deserialize
        parsed = StateTransition.from_json(json_data)

        # Verify
        assert parsed.from_state == original.from_state
        assert parsed.to_state == original.to_state
        assert parsed.timestamp == original.timestamp
        assert parsed.transitioned_by == original.transitioned_by
        assert parsed.comment == original.comment


class TestWardenIssuePanelJSON:
    """Test WardenIssue Panel JSON compatibility."""

    def test_to_json_camel_case(self) -> None:
        """Ensure to_json() returns camelCase keys."""
        issue = WardenIssue(
            id="W001",
            type="Security Analysis",
            severity=IssueSeverity.CRITICAL,
            file_path="src/user_service.py",
            message="SQL injection vulnerability",
            code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
            code_hash="abc123",
            state=IssueState.OPEN,
            first_detected=datetime(2025, 12, 20, 10, 0, 0),
            last_updated=datetime(2025, 12, 20, 10, 0, 0),
            reopen_count=0,
            state_history=[],
        )

        json_data = issue.to_json()

        # Check camelCase keys (Panel expectation)
        expected_keys = {
            "id",
            "type",
            "severity",
            "filePath",  # NOT file_path
            "message",
            "codeSnippet",  # NOT code_snippet
            "codeHash",  # NOT code_hash
            "state",
            "firstDetected",  # NOT first_detected
            "lastUpdated",  # NOT last_updated
            "reopenCount",  # NOT reopen_count
            "stateHistory",  # NOT state_history
        }
        assert set(json_data.keys()) == expected_keys

        # Check NOT snake_case
        assert "file_path" not in json_data
        assert "code_snippet" not in json_data
        assert "code_hash" not in json_data
        assert "first_detected" not in json_data
        assert "last_updated" not in json_data
        assert "reopen_count" not in json_data
        assert "state_history" not in json_data

    def test_severity_enum_values_match_panel(self) -> None:
        """Ensure severity enum values match Panel exactly."""
        test_cases = [
            (IssueSeverity.CRITICAL, 0),
            (IssueSeverity.HIGH, 1),
            (IssueSeverity.MEDIUM, 2),
            (IssueSeverity.LOW, 3),
        ]

        for severity, expected_value in test_cases:
            issue = WardenIssue(
                id="W001",
                type="Test",
                severity=severity,
                file_path="test.py",
                message="Test",
                code_snippet="",
                code_hash="",
                state=IssueState.OPEN,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
            )

            json_data = issue.to_json()
            assert json_data["severity"] == expected_value
            assert isinstance(json_data["severity"], int)

    def test_state_enum_values_match_panel(self) -> None:
        """Ensure state enum values match Panel exactly."""
        test_cases = [
            (IssueState.OPEN, 0),
            (IssueState.RESOLVED, 1),
            (IssueState.SUPPRESSED, 2),
        ]

        for state, expected_value in test_cases:
            issue = WardenIssue(
                id="W001",
                type="Test",
                severity=IssueSeverity.LOW,
                file_path="test.py",
                message="Test",
                code_snippet="",
                code_hash="",
                state=state,
                first_detected=datetime.now(),
                last_updated=datetime.now(),
                reopen_count=0,
                state_history=[],
            )

            json_data = issue.to_json()
            assert json_data["state"] == expected_value
            assert isinstance(json_data["state"], int)

    def test_nested_state_history_serialization(self) -> None:
        """Ensure nested stateHistory array serializes correctly."""
        issue = WardenIssue(
            id="W001",
            type="Test",
            severity=IssueSeverity.HIGH,
            file_path="test.py",
            message="Test",
            code_snippet="",
            code_hash="",
            state=IssueState.RESOLVED,
            first_detected=datetime(2025, 12, 20, 10, 0, 0),
            last_updated=datetime(2025, 12, 20, 11, 0, 0),
            reopen_count=0,
            state_history=[
                StateTransition(
                    from_state=IssueState.OPEN,
                    to_state=IssueState.RESOLVED,
                    timestamp=datetime(2025, 12, 20, 11, 0, 0),
                    transitioned_by="user",
                    comment="Fixed",
                )
            ],
        )

        json_data = issue.to_json()

        # Check stateHistory is array
        assert "stateHistory" in json_data
        assert isinstance(json_data["stateHistory"], list)
        assert len(json_data["stateHistory"]) == 1

        # Check nested object is camelCase
        history_item = json_data["stateHistory"][0]
        assert "fromState" in history_item
        assert "toState" in history_item
        assert "transitionedBy" in history_item

    def test_roundtrip_json_with_state_history(self) -> None:
        """Ensure complete roundtrip with nested objects works."""
        original = WardenIssue(
            id="W001",
            type="Security Analysis",
            severity=IssueSeverity.CRITICAL,
            file_path="src/auth.py",
            message="Hardcoded password detected",
            code_snippet='password = "admin123"',
            code_hash="def456",
            state=IssueState.OPEN,
            first_detected=datetime(2025, 12, 20, 9, 0, 0),
            last_updated=datetime(2025, 12, 20, 9, 0, 0),
            reopen_count=0,
            state_history=[],
        )

        # Resolve the issue
        original.resolve(resolved_by="developer", comment="Password moved to .env")

        # Serialize
        json_data = original.to_json()

        # Deserialize
        parsed = WardenIssue.from_json(json_data)

        # Verify all fields
        assert parsed.id == original.id
        assert parsed.type == original.type
        assert parsed.severity == original.severity
        assert parsed.file_path == original.file_path
        assert parsed.message == original.message
        assert parsed.code_snippet == original.code_snippet
        assert parsed.code_hash == original.code_hash
        assert parsed.state == original.state
        assert parsed.first_detected == original.first_detected
        assert parsed.reopen_count == original.reopen_count
        assert len(parsed.state_history) == len(original.state_history)

    def test_panel_can_parse_our_json(self) -> None:
        """
        Simulate Panel receiving our JSON.

        This test verifies the exact format Panel expects.
        """
        issue = WardenIssue(
            id="W001",
            type="Chaos Engineering",
            severity=IssueSeverity.HIGH,
            file_path="src/api/endpoints.py",
            message="Missing timeout on external HTTP call",
            code_snippet="response = requests.get(url)",
            code_hash="xyz789",
            state=IssueState.OPEN,
            first_detected=datetime(2025, 12, 20, 10, 15, 30),
            last_updated=datetime(2025, 12, 20, 10, 15, 30),
            reopen_count=0,
            state_history=[],
        )

        json_data = issue.to_json()

        # Panel expects these exact types
        assert isinstance(json_data["id"], str)
        assert isinstance(json_data["type"], str)
        assert isinstance(json_data["severity"], int)
        assert isinstance(json_data["filePath"], str)
        assert isinstance(json_data["message"], str)
        assert isinstance(json_data["codeSnippet"], str)
        assert isinstance(json_data["codeHash"], str)
        assert isinstance(json_data["state"], int)
        assert isinstance(json_data["firstDetected"], str)
        assert isinstance(json_data["lastUpdated"], str)
        assert isinstance(json_data["reopenCount"], int)
        assert isinstance(json_data["stateHistory"], list)

        # Panel expects ISO 8601 date format
        assert "T" in json_data["firstDetected"]  # ISO format has 'T'
        assert ":" in json_data["firstDetected"]  # ISO format has time
