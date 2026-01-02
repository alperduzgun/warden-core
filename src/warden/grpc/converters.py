"""
Proto Message Converters

Converts between Python dicts and Protocol Buffer messages.
"""

from pathlib import Path
from typing import Dict, Any

# Import generated protobuf code
try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None


class ProtoConverters:
    """Utility class for converting between dict and proto messages."""

    @staticmethod
    def severity_to_proto(severity: str) -> int:
        """Convert severity string to proto enum."""
        severity_map = {
            "critical": warden_pb2.CRITICAL,
            "high": warden_pb2.HIGH,
            "medium": warden_pb2.MEDIUM,
            "low": warden_pb2.LOW,
            "info": warden_pb2.INFO
        }
        return severity_map.get(severity.lower(), warden_pb2.SEVERITY_UNSPECIFIED)

    @staticmethod
    def state_to_proto(state: str) -> int:
        """Convert issue state string to proto enum."""
        state_map = {
            "open": warden_pb2.OPEN,
            "resolved": warden_pb2.RESOLVED,
            "suppressed": warden_pb2.SUPPRESSED,
            "reopened": warden_pb2.REOPENED
        }
        return state_map.get(state.lower(), warden_pb2.OPEN)

    @staticmethod
    def language_to_file_type(lang: str) -> int:
        """Convert language string to proto FileType enum."""
        type_map = {
            "py": warden_pb2.PYTHON,
            "python": warden_pb2.PYTHON,
            "js": warden_pb2.JAVASCRIPT,
            "javascript": warden_pb2.JAVASCRIPT,
            "ts": warden_pb2.TYPESCRIPT,
            "typescript": warden_pb2.TYPESCRIPT,
            "java": warden_pb2.JAVA,
            "cs": warden_pb2.CSHARP,
            "csharp": warden_pb2.CSHARP,
            "go": warden_pb2.GO,
            "rs": warden_pb2.RUST,
            "rust": warden_pb2.RUST,
            "cpp": warden_pb2.CPP,
            "rb": warden_pb2.RUBY,
            "ruby": warden_pb2.RUBY,
            "php": warden_pb2.PHP,
            "kt": warden_pb2.KOTLIN,
            "kotlin": warden_pb2.KOTLIN,
            "swift": warden_pb2.SWIFT,
            "scala": warden_pb2.SCALA
        }
        return type_map.get(lang.lower(), warden_pb2.OTHER)

    @staticmethod
    def convert_finding(finding: Dict[str, Any]) -> "warden_pb2.Finding":
        """Convert dict finding to proto Finding."""
        return warden_pb2.Finding(
            id=finding.get("id", ""),
            title=finding.get("title", ""),
            description=finding.get("description", ""),
            severity=ProtoConverters.severity_to_proto(finding.get("severity", "")),
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            column_number=finding.get("column_number", 0),
            code_snippet=finding.get("code_snippet", ""),
            suggestion=finding.get("suggestion", ""),
            frame_id=finding.get("frame_id", ""),
            cwe_id=finding.get("cwe_id", ""),
            owasp_category=finding.get("owasp_category", "")
        )

    @staticmethod
    def convert_fortification(fort: Dict[str, Any]) -> "warden_pb2.Fortification":
        """Convert dict fortification to proto Fortification."""
        return warden_pb2.Fortification(
            id=fort.get("id", ""),
            title=fort.get("title", ""),
            description=fort.get("description", ""),
            file_path=fort.get("file_path", ""),
            line_number=fort.get("line_number", 0),
            original_code=fort.get("original_code", ""),
            suggested_code=fort.get("suggested_code", ""),
            rationale=fort.get("rationale", "")
        )

    @staticmethod
    def convert_cleaning(clean: Dict[str, Any]) -> "warden_pb2.Cleaning":
        """Convert dict cleaning to proto Cleaning."""
        return warden_pb2.Cleaning(
            id=clean.get("id", ""),
            title=clean.get("title", ""),
            description=clean.get("description", ""),
            file_path=clean.get("file_path", ""),
            line_number=clean.get("line_number", 0),
            detail=clean.get("detail", "")
        )

    @staticmethod
    def convert_issue(issue: Dict[str, Any]) -> "warden_pb2.Issue":
        """Convert dict issue to proto Issue."""
        return warden_pb2.Issue(
            id=issue.get("id", ""),
            hash=issue.get("hash", ""),
            title=issue.get("title", ""),
            description=issue.get("description", ""),
            severity=ProtoConverters.severity_to_proto(issue.get("severity", "")),
            state=ProtoConverters.state_to_proto(issue.get("state", "open")),
            file_path=issue.get("file_path", ""),
            line_number=issue.get("line_number", 0),
            code_snippet=issue.get("code_snippet", ""),
            frame_id=issue.get("frame_id", ""),
            first_detected=issue.get("first_detected", ""),
            last_seen=issue.get("last_seen", ""),
            resolved_at=issue.get("resolved_at", "") or "",
            resolved_by=issue.get("resolved_by", "") or "",
            suppressed_at=issue.get("suppressed_at", "") or "",
            suppressed_by=issue.get("suppressed_by", "") or "",
            suppression_reason=issue.get("suppression_reason", "") or "",
            occurrence_count=issue.get("occurrence_count", 1)
        )

    @staticmethod
    def convert_code_chunk(chunk: Dict[str, Any]) -> "warden_pb2.CodeChunk":
        """Convert dict code chunk to proto CodeChunk."""
        return warden_pb2.CodeChunk(
            id=chunk.get("id", ""),
            file_path=chunk.get("file_path", ""),
            chunk_type=chunk.get("chunk_type", ""),
            name=chunk.get("name", ""),
            content=chunk.get("content", ""),
            start_line=chunk.get("start_line", 0),
            end_line=chunk.get("end_line", 0),
            language=chunk.get("language", ""),
            similarity_score=chunk.get("similarity_score", 0.0)
        )

    @staticmethod
    def convert_discovered_file(file: Dict[str, Any]) -> "warden_pb2.DiscoveredFile":
        """Convert dict file to proto DiscoveredFile."""
        lang = file.get("language", "").lower()
        file_type = ProtoConverters.language_to_file_type(lang)

        return warden_pb2.DiscoveredFile(
            path=file.get("path", ""),
            file_type=file_type,
            size_bytes=file.get("size_bytes", 0),
            line_count=file.get("line_count", 0),
            is_analyzable=file.get("is_analyzable", True),
            language=file.get("language", "")
        )

    @staticmethod
    def convert_framework(fw: Dict[str, Any]) -> "warden_pb2.DetectedFramework":
        """Convert dict framework to proto DetectedFramework."""
        return warden_pb2.DetectedFramework(
            name=fw.get("name", ""),
            version=fw.get("version", ""),
            language=fw.get("language", ""),
            confidence=fw.get("confidence", 0.0),
            detected_from=fw.get("detected_from", "")
        )

    @staticmethod
    def convert_suppression(suppression: Dict[str, Any]) -> "warden_pb2.Suppression":
        """Convert dict suppression to proto Suppression."""
        return warden_pb2.Suppression(
            id=suppression.get("id", ""),
            rule_id=suppression.get("rule_id", ""),
            file_path=suppression.get("file_path", ""),
            line_number=suppression.get("line_number", 0),
            justification=suppression.get("justification", ""),
            created_by=suppression.get("created_by", ""),
            created_at=suppression.get("created_at", ""),
            expires_at=suppression.get("expires_at", "") or "",
            is_global=suppression.get("is_global", False)
        )

    @staticmethod
    def convert_cleanup_suggestion(suggestion: Dict[str, Any]) -> "warden_pb2.CleanupSuggestion":
        """Convert dict cleanup suggestion to proto CleanupSuggestion."""
        return warden_pb2.CleanupSuggestion(
            id=suggestion.get("id", ""),
            analyzer=suggestion.get("analyzer", ""),
            title=suggestion.get("title", ""),
            description=suggestion.get("description", ""),
            file_path=suggestion.get("file_path", ""),
            line_number=suggestion.get("line_number", 0),
            code_snippet=suggestion.get("code_snippet", ""),
            suggested_fix=suggestion.get("suggested_fix", ""),
            priority=ProtoConverters.severity_to_proto(suggestion.get("priority", ""))
        )

    @staticmethod
    def convert_fortification_suggestion(
        suggestion: Dict[str, Any]
    ) -> "warden_pb2.FortificationSuggestion":
        """Convert dict fortification suggestion to proto FortificationSuggestion."""
        return warden_pb2.FortificationSuggestion(
            id=suggestion.get("id", ""),
            fortifier=suggestion.get("fortifier", ""),
            title=suggestion.get("title", ""),
            description=suggestion.get("description", ""),
            file_path=suggestion.get("file_path", ""),
            line_number=suggestion.get("line_number", 0),
            original_code=suggestion.get("original_code", ""),
            suggested_code=suggestion.get("suggested_code", ""),
            rationale=suggestion.get("rationale", ""),
            priority=ProtoConverters.severity_to_proto(suggestion.get("priority", ""))
        )

    @staticmethod
    def detect_language(path: Path) -> str:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".kt": "kotlin",
            ".swift": "swift",
            ".scala": "scala"
        }
        return ext_map.get(path.suffix.lower(), "")
