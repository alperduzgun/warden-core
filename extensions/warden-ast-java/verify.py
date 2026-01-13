#!/usr/bin/env python3
"""
Verification script for warden-ast-java package.

Checks:
- Package structure
- Entry points
- Import functionality
- Provider metadata
"""

import sys
from pathlib import Path


def check_file_exists(file_path: Path) -> bool:
    """Check if file exists."""
    exists = file_path.exists()
    status = "OK" if exists else "MISSING"
    print(f"  [{status}] {file_path}")
    return exists


def check_package_structure() -> bool:
    """Check package structure."""
    print("\n1. Package Structure:")

    root = Path(__file__).parent
    required_files = [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "src/warden_ast_java/__init__.py",
        "src/warden_ast_java/provider.py",
        "tests/__init__.py",
        "tests/test_java_provider.py",
    ]

    all_exist = True
    for file in required_files:
        file_path = root / file
        if not check_file_exists(file_path):
            all_exist = False

    return all_exist


def check_imports() -> bool:
    """Check if package can be imported."""
    print("\n2. Import Check:")

    try:
        sys.path.insert(0, str(Path(__file__).parent / "src"))
        import warden_ast_java

        print(f"  [OK] warden_ast_java imported")
        print(f"  [OK] Version: {warden_ast_java.__version__}")

        from warden_ast_java import JavaParserProvider

        print(f"  [OK] JavaParserProvider imported")

        return True

    except ImportError as e:
        print(f"  [FAIL] Import failed: {e}")
        return False


def check_provider_metadata() -> bool:
    """Check provider metadata."""
    print("\n3. Provider Metadata:")

    try:
        from warden_ast_java import JavaParserProvider

        provider = JavaParserProvider()
        metadata = provider.metadata

        checks = [
            ("Name", metadata.name == "JavaParser"),
            ("Version", metadata.version == "0.1.0"),
            ("Priority", metadata.priority.name == "NATIVE"),
            ("Languages", len(metadata.supported_languages) == 1),
            ("Requires Installation", metadata.requires_installation is True),
        ]

        all_ok = True
        for check_name, check_result in checks:
            status = "OK" if check_result else "FAIL"
            print(f"  [{status}] {check_name}")
            if not check_result:
                all_ok = False

        return all_ok

    except Exception as e:
        print(f"  [FAIL] Metadata check failed: {e}")
        return False


def check_line_counts() -> bool:
    """Check file line counts (max 500 per file)."""
    print("\n4. Line Count Check (max 500 per file):")

    root = Path(__file__).parent
    python_files = [
        "src/warden_ast_java/__init__.py",
        "src/warden_ast_java/provider.py",
        "tests/test_java_provider.py",
    ]

    all_ok = True
    for file in python_files:
        file_path = root / file
        if file_path.exists():
            lines = len(file_path.read_text().splitlines())
            status = "OK" if lines <= 500 else "FAIL"
            print(f"  [{status}] {file}: {lines} lines")
            if lines > 500:
                all_ok = False

    return all_ok


def check_build_artifacts() -> bool:
    """Check if build artifacts exist."""
    print("\n5. Build Artifacts:")

    root = Path(__file__).parent
    dist_dir = root / "dist"

    if not dist_dir.exists():
        print("  [SKIP] No dist/ directory (run 'python -m build' first)")
        return True

    artifacts = list(dist_dir.glob("*"))
    if not artifacts:
        print("  [SKIP] No build artifacts")
        return True

    print(f"  [OK] Found {len(artifacts)} artifact(s):")
    for artifact in artifacts:
        print(f"       - {artifact.name}")

    return True


def main() -> int:
    """Run all checks."""
    print("=" * 70)
    print("WARDEN-AST-JAVA VERIFICATION")
    print("=" * 70)

    checks = [
        check_package_structure,
        check_imports,
        check_provider_metadata,
        check_line_counts,
        check_build_artifacts,
    ]

    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"\n[ERROR] Check failed with exception: {e}")
            results.append(False)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(results)
    total = len(results)

    print(f"\nPassed: {passed}/{total}")

    if all(results):
        print("\nSTATUS: ALL CHECKS PASSED")
        return 0
    else:
        print("\nSTATUS: SOME CHECKS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
