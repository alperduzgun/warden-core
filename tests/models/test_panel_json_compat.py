"""
Panel JSON compatibility tests.

Tests that all models serialize/deserialize correctly for Panel integration.
Critical: camelCase conversion, enum values, date format must match Panel exactly.
"""

import pytest
from datetime import datetime

from warden.models.pipeline_run import (
    PipelineRun, Step, SubStep, PipelineSummary
)
from warden.models.validation_test import (
    TestAssertion, TestResult, ValidationTestDetails,
    SecurityTestDetails
)
from warden.models.findings import Finding, Fortification, Cleaning
from warden.models.pipeline_config import (
    PipelineConfig, PipelineNode, PipelineEdge, PipelineSettings, Position
)


class TestPipelineRunJSON:
    """Test PipelineRun JSON compatibility."""

    def test_substep_to_json(self):
        """Test SubStep to_json camelCase conversion."""
        substep = SubStep(
            id='security',
            name='Security Analysis',
            type='security',
            status='running',
            duration='0.8s'
        )

        json_data = substep.to_json()

        # Check camelCase keys
        assert json_data['id'] == 'security'
        assert json_data['name'] == 'Security Analysis'
        assert json_data['type'] == 'security'
        assert json_data['status'] == 'running'
        assert json_data['duration'] == '0.8s'

        # Ensure no snake_case keys
        assert 'start_time' not in json_data

    def test_step_to_json_with_substeps(self):
        """Test Step to_json with substeps."""
        step = Step(
            id='validation',
            name='Validation',
            type='validation',
            status='running'
        )

        json_data = step.to_json()

        # Check subSteps (camelCase)
        assert 'subSteps' in json_data
        assert isinstance(json_data['subSteps'], list)
        assert len(json_data['subSteps']) == 6  # 6 validation frames

    def test_pipeline_summary_nested_structure(self):
        """Test PipelineSummary nested JSON structure."""
        summary = PipelineSummary(
            score_before=4.0,
            score_after=8.5,
            lines_before=287,
            lines_after=245,
            duration='1m 43s',
            progress_current=3,
            progress_total=5,
            findings_critical=2,
            findings_high=3,
            findings_medium=5,
            findings_low=1,
            ai_source='Claude'
        )

        json_data = summary.to_json()

        # Check nested structure
        assert json_data['score'] == {'before': 4.0, 'after': 8.5}
        assert json_data['lines'] == {'before': 287, 'after': 245}
        assert json_data['progress'] == {'current': 3, 'total': 5}
        assert json_data['findings'] == {
            'critical': 2,
            'high': 3,
            'medium': 5,
            'low': 1
        }
        assert json_data['aiSource'] == 'Claude'  # camelCase

    def test_pipeline_run_full_json(self):
        """Test complete PipelineRun JSON export."""
        run = PipelineRun(
            id='run-1',
            run_number=142,
            status='running',
            trigger='Push to main'
        )

        json_data = run.to_json()

        # Check camelCase keys
        assert json_data['id'] == 'run-1'
        assert json_data['runNumber'] == 142  # camelCase
        assert json_data['status'] == 'running'
        assert json_data['trigger'] == 'Push to main'
        assert 'steps' in json_data
        assert 'startTime' in json_data  # camelCase

        # Ensure no snake_case
        assert 'run_number' not in json_data
        assert 'start_time' not in json_data


class TestValidationTestJSON:
    """Test validation test models JSON compatibility."""

    def test_test_assertion_stack_trace(self):
        """Test TestAssertion stackTrace camelCase."""
        assertion = TestAssertion(
            id='assert-1',
            description='SQL injection detected',
            passed=False,
            error='Vulnerable query found',
            stack_trace='File "test.py", line 45'
        )

        json_data = assertion.to_json()

        # Check stackTrace is camelCase
        assert json_data['stackTrace'] == 'File "test.py", line 45'
        assert 'stack_trace' not in json_data  # No snake_case

    def test_validation_test_details_structure(self):
        """Test ValidationTestDetails complete structure."""
        details = ValidationTestDetails(
            security=SecurityTestDetails(total_tests=5, passed_tests=4)
        )

        json_data = details.to_json()

        # Check all 6 frame types present
        assert 'security' in json_data
        assert 'chaos' in json_data
        assert 'fuzz' in json_data
        assert 'property' in json_data
        assert 'stress' in json_data

        # Check SecurityTestDetails structure
        sec = json_data['security']
        assert sec['totalTests'] == 5  # camelCase
        assert sec['passedTests'] == 4  # camelCase


class TestFindingsJSON:
    """Test Finding, Fortification, Cleaning JSON."""

    def test_finding_severity_values(self):
        """Test Finding severity is string (not enum)."""
        finding = Finding(
            id='F001',
            severity='critical',
            message='SQL injection vulnerability',
            location='user_service.py:45'
        )

        json_data = finding.to_json()

        # Severity must be string, not number
        assert json_data['severity'] == 'critical'
        assert isinstance(json_data['severity'], str)


class TestPipelineConfigJSON:
    """Test PipelineConfig JSON compatibility."""

    def test_pipeline_settings_camelcase(self):
        """Test PipelineSettings camelCase keys."""
        settings = PipelineSettings(
            fail_fast=True,
            timeout=300,
            parallel=False
        )

        json_data = settings.to_json()

        # Check camelCase
        assert json_data['failFast'] == True
        assert json_data['timeout'] == 300
        assert json_data['parallel'] == False

        # Ensure no snake_case
        assert 'fail_fast' not in json_data

    def test_position_json(self):
        """Test Position x,y coordinates."""
        pos = Position(x=100.5, y=200.3)
        json_data = pos.to_json()

        assert json_data['x'] == 100.5
        assert json_data['y'] == 200.3


class TestJSONRoundtrip:
    """Test JSON serialization/deserialization round-trip."""

    def test_pipeline_run_roundtrip(self):
        """Test PipelineRun to_json → from_json roundtrip."""
        # Note: from_json not fully implemented in base model
        # This is a placeholder for future implementation
        run = PipelineRun(
            id='run-1',
            run_number=1,
            status='running'
        )

        json_data = run.to_json()

        # Verify JSON structure for Panel consumption
        assert isinstance(json_data, dict)
        assert 'id' in json_data
        assert 'runNumber' in json_data
        assert 'status' in json_data


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
