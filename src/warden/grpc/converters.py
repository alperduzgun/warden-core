"""
Proto Message Converters

Converts between Python dicts and Protocol Buffer messages.
"""

from pathlib import Path
from typing import Any, Dict

# Import generated protobuf code
try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None


class ProtoConverters:
    """Utility class for converting between dict and proto messages."""

    @staticmethod
    def _to_proto_enum(pb_module, enum_name: str, fallback: int) -> int:
        """Generic dynamic enum lookup."""
        return getattr(pb_module, enum_name.upper(), fallback)

    @staticmethod
    def severity_to_proto(severity: str) -> int:
        """Convert severity string to proto enum."""
        return ProtoConverters._to_proto_enum(warden_pb2, severity, warden_pb2.SEVERITY_UNSPECIFIED)

    @staticmethod
    def state_to_proto(state: str) -> int:
        """Convert issue state string to proto enum."""
        return ProtoConverters._to_proto_enum(warden_pb2, state, warden_pb2.OPEN)

    @staticmethod
    def language_to_file_type(lang: str) -> int:
        """Convert language string to proto FileType enum."""
        from warden.ast.domain.enums import CodeLanguage
        from warden.shared.languages.registry import LanguageRegistry

        # 1. Resolve to CodeLanguage enum
        try:
            if lang.startswith("."): # It's an extension
                lang_enum = LanguageRegistry.get_language_from_path(lang)
            else: # It's a name or id
                lang_enum = CodeLanguage(lang.lower())
        except ValueError:
            # Fallback for names not exactly matching enum value
            lang_enum = LanguageRegistry.get_language_from_path(f"dummy.{lang}")

        # 2. Get Registry definition
        defn = LanguageRegistry.get_definition(lang_enum)
        if defn and defn.proto_type_name:
             return getattr(warden_pb2, defn.proto_type_name.upper(), warden_pb2.OTHER)

        # 3. Fallback to name-based lookup if no definition found
        return ProtoConverters._to_proto_enum(warden_pb2, lang_enum.value, warden_pb2.OTHER)

    @staticmethod
    def convert_finding(finding: Any) -> "warden_pb2.Finding":
        """Convert finding to proto Finding."""
        return warden_pb2.Finding(
            id=get_finding_attribute(finding, "id", ""),
            title=get_finding_attribute(finding, "title", ""),
            description=get_finding_attribute(finding, "description", ""),
            severity=ProtoConverters.severity_to_proto(get_finding_attribute(finding, "severity", "")),
            file_path=get_finding_attribute(finding, "file_path", ""),
            line_number=get_finding_attribute(finding, "line_number", 0),
            column_number=get_finding_attribute(finding, "column_number", 0),
            code_snippet=get_finding_attribute(finding, "code_snippet", ""),
            suggestion=get_finding_attribute(finding, "suggestion", ""),
            frame_id=get_finding_attribute(finding, "frame_id", ""),
            cwe_id=get_finding_attribute(finding, "cwe_id", ""),
            owasp_category=get_finding_attribute(finding, "owasp_category", "")
        )

    @staticmethod
    def convert_fortification(fort: dict[str, Any]) -> "warden_pb2.Fortification":
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
    def convert_cleaning(clean: dict[str, Any]) -> "warden_pb2.Cleaning":
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
    def convert_issue(issue: dict[str, Any]) -> "warden_pb2.Issue":
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
    def convert_code_chunk(chunk: dict[str, Any]) -> "warden_pb2.CodeChunk":
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
    def convert_discovered_file(file: dict[str, Any]) -> "warden_pb2.DiscoveredFile":
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
    def convert_framework(fw: dict[str, Any]) -> "warden_pb2.DetectedFramework":
        """Convert dict framework to proto DetectedFramework."""
        return warden_pb2.DetectedFramework(
            name=fw.get("name", ""),
            version=fw.get("version", ""),
            language=fw.get("language", ""),
            confidence=fw.get("confidence", 0.0),
            detected_from=fw.get("detected_from", "")
        )

    @staticmethod
    def convert_suppression(suppression: dict[str, Any]) -> "warden_pb2.Suppression":
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
    def convert_cleanup_suggestion(suggestion: dict[str, Any]) -> "warden_pb2.CleanupSuggestion":
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
        suggestion: dict[str, Any]
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
        """Detect language using central LanguageRegistry."""
        from warden.shared.languages.registry import LanguageRegistry
        lang_enum = LanguageRegistry.get_language_from_path(path)
        return lang_enum.value if lang_enum != CodeLanguage.UNKNOWN else ""
