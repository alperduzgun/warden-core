"""
Central Language Registry.

Provides unified access to language metadata and discovery.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
from warden.ast.domain.enums import CodeLanguage
from warden.shared.languages.definitions import LANGUAGE_DEFINITIONS, LanguageDefinition


class LanguageRegistry:
    """
    Central registry for language-related operations.
    Unifies extension mapping, aliasing, and metadata.
    """

    _definitions: Dict[CodeLanguage, LanguageDefinition] = {d.id: d for d in LANGUAGE_DEFINITIONS}
    _extension_map: Dict[str, CodeLanguage] = {}

    @classmethod
    def _initialize_maps(cls):
        if not cls._extension_map:
            for defn in cls._definitions.values():
                for ext in defn.extensions:
                    cls._extension_map[ext.lower()] = defn.id

    @classmethod
    def get_language_from_path(cls, path: Path | str) -> CodeLanguage:
        """Detect language from file path extension."""
        cls._initialize_maps()
        if not path:
            return CodeLanguage.UNKNOWN
            
        ext = Path(path).suffix.lower()
        return cls._extension_map.get(ext, CodeLanguage.UNKNOWN)

    @classmethod
    def get_definition(cls, lang: CodeLanguage) -> Optional[LanguageDefinition]:
        """Get rich metadata for a language."""
        return cls._definitions.get(lang)

    @classmethod
    def get_primary_extension(cls, lang: CodeLanguage) -> str:
        """Get primary extension for a language."""
        defn = cls.get_definition(lang)
        return defn.primary_extension if defn else ""

    @classmethod
    def get_all_supported_extensions(cls) -> Set[str]:
        """Get all extensions supported by Warden."""
        cls._initialize_maps()
        return set(cls._extension_map.keys())

    @classmethod
    def get_code_languages(cls) -> List[CodeLanguage]:
        """Get all languages classified as code."""
        return list(cls._definitions.keys())

    @classmethod
    def is_compiled(cls, lang: CodeLanguage) -> bool:
        defn = cls.get_definition(lang)
        return defn.is_compiled if defn else False
