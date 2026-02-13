"""
SARIF Report Generator for Spec Analysis.

Generates SARIF (Static Analysis Results Interchange Format) reports
for contract gap analysis results.

SARIF Specification: https://sarifweb.azurewebsites.net/

Author: Warden Team
Version: 1.0.0
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.validation.frames.spec.models import (
    ContractGap,
    GapSeverity,
    SpecAnalysisResult,
)

# SARIF severity mapping
SEVERITY_TO_SARIF_LEVEL = {
    GapSeverity.CRITICAL: "error",
    GapSeverity.HIGH: "error",
    GapSeverity.MEDIUM: "warning",
    GapSeverity.LOW: "note",
}

# Gap type to SARIF rule mapping
GAP_TYPE_RULES = {
    "missing_operation": {
        "id": "SPEC001",
        "name": "MissingOperation",
        "shortDescription": "Consumer expects an operation that provider doesn't offer",
        "fullDescription": "The consumer contract references an API operation that is not defined in the provider contract. This will cause runtime errors when the consumer attempts to call the missing endpoint.",
        "helpUri": "https://warden.dev/docs/spec/gaps#missing-operation",
    },
    "unused_operation": {
        "id": "SPEC002",
        "name": "UnusedOperation",
        "shortDescription": "Provider offers an operation that consumer doesn't use",
        "fullDescription": "The provider contract defines an API operation that is not used by the consumer. This may indicate dead code or an incomplete consumer implementation.",
        "helpUri": "https://warden.dev/docs/spec/gaps#unused-operation",
    },
    "input_type_mismatch": {
        "id": "SPEC003",
        "name": "InputTypeMismatch",
        "shortDescription": "Input type mismatch between consumer and provider",
        "fullDescription": "The consumer sends a different input type than what the provider expects. This may cause serialization errors or data loss.",
        "helpUri": "https://warden.dev/docs/spec/gaps#type-mismatch",
    },
    "output_type_mismatch": {
        "id": "SPEC004",
        "name": "OutputTypeMismatch",
        "shortDescription": "Output type mismatch between consumer and provider",
        "fullDescription": "The consumer expects a different output type than what the provider returns. This may cause deserialization errors.",
        "helpUri": "https://warden.dev/docs/spec/gaps#type-mismatch",
    },
    "input_type_missing": {
        "id": "SPEC005",
        "name": "InputTypeMissing",
        "shortDescription": "Consumer sends input but provider doesn't expect it",
        "fullDescription": "The consumer sends request body data that the provider doesn't expect or process.",
        "helpUri": "https://warden.dev/docs/spec/gaps#type-mismatch",
    },
    "missing_field": {
        "id": "SPEC006",
        "name": "MissingField",
        "shortDescription": "Field expected by consumer is missing in provider model",
        "fullDescription": "A field that the consumer expects in a model is not present in the provider's model definition.",
        "helpUri": "https://warden.dev/docs/spec/gaps#missing-field",
    },
    "field_type_mismatch": {
        "id": "SPEC007",
        "name": "FieldTypeMismatch",
        "shortDescription": "Field type mismatch between consumer and provider",
        "fullDescription": "A field has different types in the consumer and provider model definitions.",
        "helpUri": "https://warden.dev/docs/spec/gaps#field-type-mismatch",
    },
    "nullable_mismatch": {
        "id": "SPEC008",
        "name": "NullableMismatch",
        "shortDescription": "Field optionality mismatch",
        "fullDescription": "A field is required by consumer but optional in provider, which may cause null pointer exceptions.",
        "helpUri": "https://warden.dev/docs/spec/gaps#nullable-mismatch",
    },
    "enum_value_missing": {
        "id": "SPEC009",
        "name": "EnumValueMissing",
        "shortDescription": "Enum value expected by consumer is missing in provider",
        "fullDescription": "An enum value that the consumer may use is not defined in the provider's enum.",
        "helpUri": "https://warden.dev/docs/spec/gaps#enum-mismatch",
    },
    "enum_value_extra": {
        "id": "SPEC010",
        "name": "EnumValueExtra",
        "shortDescription": "Provider has extra enum values not used by consumer",
        "fullDescription": "The provider defines enum values that the consumer doesn't handle.",
        "helpUri": "https://warden.dev/docs/spec/gaps#enum-mismatch",
    },
}


class SarifReportGenerator:
    """
    Generates SARIF reports from spec analysis results.

    Usage:
        generator = SarifReportGenerator()
        sarif = generator.generate(analysis_result)
        generator.save(sarif, "spec-report.sarif")
    """

    SARIF_VERSION = "2.1.0"
    SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

    def __init__(
        self,
        tool_name: str = "warden-spec",
        tool_version: str = "1.0.0",
        tool_uri: str = "https://warden.dev",
    ):
        """
        Initialize SARIF generator.

        Args:
            tool_name: Name of the tool generating the report
            tool_version: Version of the tool
            tool_uri: URI for tool information
        """
        self.tool_name = tool_name
        self.tool_version = tool_version
        self.tool_uri = tool_uri

    def generate(
        self,
        result: SpecAnalysisResult,
        project_root: Path | None = None,
    ) -> dict[str, Any]:
        """
        Generate SARIF report from analysis result.

        Args:
            result: Spec analysis result with gaps
            project_root: Optional project root for relative paths

        Returns:
            SARIF report as dictionary
        """
        # Collect unique rules from gaps
        rules = self._build_rules(result.gaps)

        # Build results from gaps
        results = self._build_results(result.gaps, project_root)

        # Build invocation info
        invocation = self._build_invocation(result)

        sarif = {
            "$schema": self.SARIF_SCHEMA,
            "version": self.SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": self.tool_name,
                            "version": self.tool_version,
                            "informationUri": self.tool_uri,
                            "rules": rules,
                        },
                    },
                    "invocations": [invocation],
                    "results": results,
                    "properties": {
                        "consumer": result.consumer_contract.name,
                        "provider": result.provider_contract.name,
                        "summary": {
                            "totalConsumerOperations": result.total_consumer_operations,
                            "totalProviderOperations": result.total_provider_operations,
                            "matchedOperations": result.matched_operations,
                            "missingOperations": result.missing_operations,
                            "unusedOperations": result.unused_operations,
                            "typeMismatches": result.type_mismatches,
                            "totalGaps": len(result.gaps),
                        },
                    },
                },
            ],
        }

        return sarif

    def _build_rules(self, gaps: list[ContractGap]) -> list[dict[str, Any]]:
        """Build SARIF rules from gaps."""
        seen_rule_ids = set()
        rules = []

        for gap in gaps:
            rule_info = GAP_TYPE_RULES.get(gap.gap_type)
            if not rule_info:
                # Unknown gap type - create generic rule
                rule_id = f"SPEC999-{gap.gap_type}"
                if rule_id in seen_rule_ids:
                    continue
                seen_rule_ids.add(rule_id)
                rules.append(
                    {
                        "id": rule_id,
                        "name": gap.gap_type,
                        "shortDescription": {"text": f"Contract gap: {gap.gap_type}"},
                        "defaultConfiguration": {
                            "level": SEVERITY_TO_SARIF_LEVEL.get(gap.severity, "warning"),
                        },
                    }
                )
            else:
                if rule_info["id"] in seen_rule_ids:
                    continue
                seen_rule_ids.add(rule_info["id"])
                rules.append(
                    {
                        "id": rule_info["id"],
                        "name": rule_info["name"],
                        "shortDescription": {"text": rule_info["shortDescription"]},
                        "fullDescription": {"text": rule_info["fullDescription"]},
                        "helpUri": rule_info["helpUri"],
                        "defaultConfiguration": {
                            "level": SEVERITY_TO_SARIF_LEVEL.get(gap.severity, "warning"),
                        },
                    }
                )

        return rules

    def _build_results(
        self,
        gaps: list[ContractGap],
        project_root: Path | None,
    ) -> list[dict[str, Any]]:
        """Build SARIF results from gaps."""
        results = []

        for gap in gaps:
            rule_info = GAP_TYPE_RULES.get(gap.gap_type, {"id": f"SPEC999-{gap.gap_type}"})

            result_entry: dict[str, Any] = {
                "ruleId": rule_info["id"],
                "level": SEVERITY_TO_SARIF_LEVEL.get(gap.severity, "warning"),
                "message": {
                    "text": gap.message,
                },
                "properties": {
                    "gapType": gap.gap_type,
                    "consumerPlatform": gap.consumer_platform,
                    "providerPlatform": gap.provider_platform,
                },
            }

            # Add detail if present
            if gap.detail:
                result_entry["message"]["markdown"] = f"{gap.message}\n\n{gap.detail}"

            # Add operation name if present
            if gap.operation_name:
                result_entry["properties"]["operationName"] = gap.operation_name

            # Add field name if present
            if gap.field_name:
                result_entry["properties"]["fieldName"] = gap.field_name

            # Add locations
            locations = []

            # Consumer location
            if gap.consumer_file:
                consumer_loc = self._build_location(
                    gap.consumer_file,
                    gap.consumer_line,
                    project_root,
                    "consumer",
                )
                locations.append(consumer_loc)

            # Provider location (as related location)
            if gap.provider_file:
                provider_loc = self._build_location(
                    gap.provider_file,
                    gap.provider_line,
                    project_root,
                    "provider",
                )
                if locations:
                    result_entry["relatedLocations"] = [provider_loc]
                else:
                    locations.append(provider_loc)

            if locations:
                result_entry["locations"] = locations

            results.append(result_entry)

        return results

    def _build_location(
        self,
        file_path: str,
        line: int | None,
        project_root: Path | None,
        description: str,
    ) -> dict[str, Any]:
        """Build SARIF location object."""
        # Make path relative if project_root provided
        if project_root:
            try:
                rel_path = Path(file_path).relative_to(project_root)
                uri = str(rel_path)
            except ValueError:
                uri = file_path
        else:
            uri = file_path

        location: dict[str, Any] = {
            "physicalLocation": {
                "artifactLocation": {
                    "uri": uri,
                },
            },
            "message": {
                "text": f"Location in {description}",
            },
        }

        if line:
            location["physicalLocation"]["region"] = {
                "startLine": line,
            }

        return location

    def _build_invocation(self, result: SpecAnalysisResult) -> dict[str, Any]:
        """Build SARIF invocation object."""
        return {
            "executionSuccessful": True,
            "endTimeUtc": datetime.now(timezone.utc).isoformat(),
            "properties": {
                "consumerContract": result.consumer_contract.name,
                "providerContract": result.provider_contract.name,
            },
        }

    def save(
        self,
        sarif: dict[str, Any],
        output_path: str | Path,
        indent: int = 2,
    ) -> None:
        """
        Save SARIF report to file.

        Args:
            sarif: SARIF report dictionary
            output_path: Output file path
            indent: JSON indentation
        """
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sarif, f, indent=indent)

    def to_json(self, sarif: dict[str, Any], indent: int = 2) -> str:
        """
        Convert SARIF report to JSON string.

        Args:
            sarif: SARIF report dictionary
            indent: JSON indentation

        Returns:
            JSON string
        """
        return json.dump(sarif, indent=indent)


def generate_sarif_report(
    result: SpecAnalysisResult,
    output_path: str | Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """
    Convenience function to generate SARIF report.

    Args:
        result: Spec analysis result
        output_path: Optional output file path
        project_root: Optional project root for relative paths

    Returns:
        SARIF report dictionary
    """
    generator = SarifReportGenerator()
    sarif = generator.generate(result, project_root)

    if output_path:
        generator.save(sarif, output_path)

    return sarif
