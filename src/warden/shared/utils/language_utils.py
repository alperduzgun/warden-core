from pathlib import Path
from typing import List, Set

from warden.ast.domain.enums import CodeLanguage
from warden.shared.languages.registry import LanguageRegistry

# For backward compatibility, though Registry is preferred
EXTENSION_TO_LANGUAGE = {
    ext: LanguageRegistry.get_language_from_path(ext) for ext in LanguageRegistry.get_all_supported_extensions()
}

LANGUAGE_TO_EXTENSION = {
    lang: LanguageRegistry.get_primary_extension(lang) for lang in LanguageRegistry.get_code_languages()
}


def get_language_from_path(path: Path | str) -> CodeLanguage:
    return LanguageRegistry.get_language_from_path(path)


def get_primary_extension(language: CodeLanguage | str) -> str:
    if isinstance(language, str):
        try:
            language = CodeLanguage(language.lower())
        except ValueError:
            return ""
    return LanguageRegistry.get_primary_extension(language)


def get_supported_extensions() -> list[str]:
    return list(LanguageRegistry.get_all_supported_extensions())


def get_code_extensions() -> set[str]:
    return LanguageRegistry.get_all_supported_extensions()
