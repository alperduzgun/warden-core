import pytest
from pathlib import Path
from warden.shared.utils.language_utils import (
    get_language_from_path,
    get_primary_extension,
    get_supported_extensions,
    get_code_extensions
)
from warden.ast.domain.enums import CodeLanguage

def test_get_language_from_path():
    assert get_language_from_path("test.py") == CodeLanguage.PYTHON
    assert get_language_from_path("main.go") == CodeLanguage.GO
    assert get_language_from_path("script.sh") == CodeLanguage.SHELL
    assert get_language_from_path("App.tsx") == CodeLanguage.TSX
    assert get_language_from_path("unknown.xyz") == CodeLanguage.UNKNOWN
    assert get_language_from_path(Path("nested/dir/file.java")) == CodeLanguage.JAVA

def test_get_primary_extension():
    assert get_primary_extension(CodeLanguage.PYTHON) == ".py"
    assert get_primary_extension("python") == ".py"
    assert get_primary_extension(CodeLanguage.KOTLIN) == ".kt"
    assert get_primary_extension("unknown") == ""

def test_get_supported_extensions():
    exts = get_supported_extensions()
    assert ".py" in exts
    assert ".ts" in exts
    assert ".dart" in exts
    assert len(exts) > 20

def test_get_code_extensions():
    exts = get_code_extensions()
    assert ".py" in exts
    assert ".proto" not in exts
    assert ".json" in exts # We map JSON to CodeLanguage.JSON now
