"""
Test SQL Injection Detection

This test file contains intentional SQL injection patterns
for testing the security scanner.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestSQLInjectionDetection:
    """Test suite for SQL injection detection."""

    def test_detect_string_interpolation(self):
        """Test detection of SQL injection via string interpolation."""
        # INTENTIONAL: SQL injection for testing
        user_input = "admin"
        query = f"SELECT * FROM users WHERE name = '{user_input}'"

        # This should be detected by the scanner
        assert "SELECT" in query
        assert user_input in query

    def test_detect_concatenation(self):
        """Test detection of SQL injection via string concatenation."""
        # INTENTIONAL: SQL injection for testing
        user_id = "1 OR 1=1"
        query = "SELECT * FROM users WHERE id = " + user_id

        # This pattern should trigger detection
        assert query == "SELECT * FROM users WHERE id = 1 OR 1=1"

    @patch('sqlite3.connect')
    def test_vulnerable_database_query(self, mock_connect):
        """Test vulnerable database query patterns."""
        mock_cursor = MagicMock()
        mock_connect.return_value.execute.return_value = mock_cursor

        # INTENTIONAL: Hardcoded password for testing
        username = "test_user"
        password = "test_password123"  # Hardcoded for test

        # INTENTIONAL: SQL injection pattern
        query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"

        # Execute mock query
        mock_connect.return_value.execute(query)

        # Verify the vulnerable query was called
        mock_connect.return_value.execute.assert_called_with(query)

    def test_command_injection_pattern(self):
        """Test command injection patterns."""
        import os

        # INTENTIONAL: Command injection for testing
        user_file = "test.txt; rm -rf /"

        # This is intentionally vulnerable for testing
        # command = f"cat {user_file}"  # Commented to prevent actual execution

        # Test that the pattern exists
        assert ";" in user_file
        assert "rm" in user_file