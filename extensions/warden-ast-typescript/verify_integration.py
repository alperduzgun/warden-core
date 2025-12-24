#!/usr/bin/env python3
"""
Comprehensive verification script for TypeScript AST provider integration.

Verifies:
1. Entry point registration
2. Direct import functionality
3. Provider metadata
4. Dependency validation
5. TypeScript parsing (.ts files)
6. TSX parsing (.tsx files)
7. Decorator extraction
8. Generic type support
9. Warden discovery mechanism
10. CodeFile integration
"""

import asyncio
import sys
from typing import List


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_test(name: str, passed: bool, details: str = "") -> None:
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {name}")
    if details:
        print(f"      {details}")


async def verify_entry_point() -> bool:
    """Verify entry point registration."""
    print_header("1. Entry Point Registration")

    try:
        import importlib.metadata as metadata

        # Get entry points for warden.ast_providers
        entry_points = metadata.entry_points()

        if hasattr(entry_points, "select"):
            # Python 3.10+
            providers = entry_points.select(group="warden.ast_providers")
        else:
            # Python 3.9
            providers = entry_points.get("warden.ast_providers", [])

        typescript_entry = None
        for ep in providers:
            if ep.name == "typescript":
                typescript_entry = ep
                break

        if typescript_entry:
            print_test(
                "Entry point 'typescript' registered",
                True,
                f"Module: {typescript_entry.value}",
            )
            return True
        else:
            print_test("Entry point 'typescript' registered", False)
            return False

    except Exception as e:
        print_test("Entry point check", False, f"Error: {e}")
        return False


async def verify_direct_import() -> bool:
    """Verify direct import of provider."""
    print_header("2. Direct Import")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider

        provider = TypeScriptParserProvider()
        print_test("Import TypeScriptParserProvider", True)
        return True
    except Exception as e:
        print_test("Import TypeScriptParserProvider", False, f"Error: {e}")
        return False


async def verify_metadata() -> bool:
    """Verify provider metadata."""
    print_header("3. Provider Metadata")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider
        from warden.ast.domain.enums import CodeLanguage, ASTProviderPriority

        provider = TypeScriptParserProvider()
        metadata = provider.metadata

        tests = [
            ("Provider name", metadata.name == "typescript-parser"),
            ("Provider version", metadata.version == "0.1.0"),
            ("Supports TypeScript", CodeLanguage.TYPESCRIPT in metadata.supported_languages),
            ("Priority is NATIVE", metadata.priority == ASTProviderPriority.NATIVE),
            ("Has description", bool(metadata.description)),
            ("Has install command", bool(metadata.installation_command)),
        ]

        all_passed = True
        for test_name, passed in tests:
            print_test(test_name, passed)
            all_passed = all_passed and passed

        return all_passed

    except Exception as e:
        print_test("Metadata verification", False, f"Error: {e}")
        return False


async def verify_dependencies() -> bool:
    """Verify dependencies are installed."""
    print_header("4. Dependency Validation")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider

        provider = TypeScriptParserProvider()
        is_valid = await provider.validate()

        print_test("Dependencies installed", is_valid)
        return is_valid

    except Exception as e:
        print_test("Dependency validation", False, f"Error: {e}")
        return False


async def verify_typescript_parsing() -> bool:
    """Verify TypeScript parsing."""
    print_header("5. TypeScript Parsing (.ts)")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider
        from warden.ast.domain.enums import CodeLanguage, ParseStatus, ASTNodeType

        provider = TypeScriptParserProvider()

        # Test 1: Simple interface
        code1 = """
        interface User {
            id: number;
            name: string;
        }
        """
        result1 = await provider.parse(code1, CodeLanguage.TYPESCRIPT, "User.ts")
        test1_passed = (
            result1.status == ParseStatus.SUCCESS
            and result1.ast_root is not None
            and any(node.node_type == ASTNodeType.CLASS for node in result1.ast_root.children)
        )
        print_test("Parse interface", test1_passed)

        # Test 2: Class with method
        code2 = """
        class UserService {
            async getUser(id: number): Promise<User> {
                return { id, name: "test" };
            }
        }
        """
        result2 = await provider.parse(code2, CodeLanguage.TYPESCRIPT, "UserService.ts")
        test2_passed = (
            result2.status == ParseStatus.SUCCESS
            and result2.ast_root is not None
        )
        print_test("Parse class with method", test2_passed)

        # Test 3: Generics
        code3 = """
        function identity<T>(arg: T): T {
            return arg;
        }
        """
        result3 = await provider.parse(code3, CodeLanguage.TYPESCRIPT, "utils.ts")
        test3_passed = (
            result3.status == ParseStatus.SUCCESS
            and result3.ast_root is not None
        )
        print_test("Parse generic function", test3_passed)

        return test1_passed and test2_passed and test3_passed

    except Exception as e:
        print_test("TypeScript parsing", False, f"Error: {e}")
        return False


async def verify_tsx_parsing() -> bool:
    """Verify TSX parsing."""
    print_header("6. TSX Parsing (.tsx)")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider
        from warden.ast.domain.enums import CodeLanguage, ParseStatus

        provider = TypeScriptParserProvider()

        # Test TSX component
        code = """
        function UserCard({ name }: { name: string }) {
            return <div className="card">{name}</div>;
        }
        """
        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "UserCard.tsx")

        test_passed = result.status == ParseStatus.SUCCESS and result.ast_root is not None
        print_test("Parse TSX component", test_passed, f"File: UserCard.tsx")

        return test_passed

    except Exception as e:
        print_test("TSX parsing", False, f"Error: {e}")
        return False


async def verify_decorator_extraction() -> bool:
    """Verify decorator extraction."""
    print_header("7. Decorator Extraction")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider
        from warden.ast.domain.enums import CodeLanguage, ParseStatus, ASTNodeType

        provider = TypeScriptParserProvider()

        code = """
        @Injectable()
        class UserService {
            @Get('/users')
            getUsers(): void {
                return;
            }
        }
        """
        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "user.service.ts")

        if result.status != ParseStatus.SUCCESS:
            print_test("Decorator extraction", False, "Parse failed")
            return False

        # Find class with decorator
        class_nodes = [n for n in result.ast_root.children if n.node_type == ASTNodeType.CLASS]
        class_has_decorator = (
            len(class_nodes) > 0
            and "decorators" in class_nodes[0].attributes
        )
        print_test("Class decorator extracted", class_has_decorator)

        # Find method with decorator
        if class_nodes:
            method_nodes = [n for n in class_nodes[0].children if n.node_type == ASTNodeType.FUNCTION]
            method_has_decorator = (
                len(method_nodes) > 0
                and "decorators" in method_nodes[0].attributes
            )
            print_test("Method decorator extracted", method_has_decorator)
            return class_has_decorator and method_has_decorator
        else:
            return False

    except Exception as e:
        print_test("Decorator extraction", False, f"Error: {e}")
        return False


async def verify_generic_support() -> bool:
    """Verify generic type support."""
    print_header("8. Generic Type Support")

    try:
        from warden_ast_typescript.provider import TypeScriptParserProvider
        from warden.ast.domain.enums import CodeLanguage, ParseStatus, ASTNodeType

        provider = TypeScriptParserProvider()

        code = """
        interface Repository<T> {
            findById(id: number): T;
        }
        """
        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "Repository.ts")

        if result.status != ParseStatus.SUCCESS:
            print_test("Generic support", False, "Parse failed")
            return False

        # Check for generic attribute
        interface_nodes = [n for n in result.ast_root.children if n.node_type == ASTNodeType.CLASS]
        has_generic = (
            len(interface_nodes) > 0
            and interface_nodes[0].attributes.get("generic", False)
        )
        print_test("Generic type detected", has_generic)

        return has_generic

    except Exception as e:
        print_test("Generic support", False, f"Error: {e}")
        return False


async def verify_warden_discovery() -> bool:
    """Verify Warden can discover the provider."""
    print_header("9. Warden Discovery")

    try:
        from warden.ast.application.provider_discovery import ProviderDiscovery
        from warden.ast.domain.enums import CodeLanguage

        discovery = ProviderDiscovery()
        await discovery.discover_providers()

        # Check if TypeScript provider is discovered
        typescript_provider = discovery.get_provider_for_language(CodeLanguage.TYPESCRIPT)

        if typescript_provider:
            print_test(
                "Provider discovered by Warden",
                True,
                f"Provider: {typescript_provider.metadata.name}",
            )
            return True
        else:
            print_test("Provider discovered by Warden", False, "Not found")
            return False

    except Exception as e:
        print_test("Warden discovery", False, f"Error: {e}")
        return False


async def verify_codefile_integration() -> bool:
    """Verify CodeFile integration."""
    print_header("10. CodeFile Integration")

    try:
        from warden.ast.application.code_file import CodeFile
        from warden.ast.domain.enums import CodeLanguage, ParseStatus

        # Test with TypeScript file
        ts_code = """
        interface Config {
            apiUrl: string;
            timeout: number;
        }

        export const config: Config = {
            apiUrl: "https://api.example.com",
            timeout: 5000
        };
        """

        code_file = CodeFile(
            file_path="config.ts",
            language=CodeLanguage.TYPESCRIPT,
            content=ts_code,
        )

        result = await code_file.parse()

        test_passed = (
            result.status == ParseStatus.SUCCESS
            and result.provider_name == "typescript-parser"
        )

        print_test("CodeFile TypeScript parsing", test_passed)

        # Test with TSX file
        tsx_code = """
        export const App = () => {
            return <h1>Hello World</h1>;
        };
        """

        tsx_file = CodeFile(
            file_path="App.tsx",
            language=CodeLanguage.TYPESCRIPT,
            content=tsx_code,
        )

        tsx_result = await tsx_file.parse()
        tsx_test_passed = tsx_result.status == ParseStatus.SUCCESS

        print_test("CodeFile TSX parsing", tsx_test_passed)

        return test_passed and tsx_test_passed

    except Exception as e:
        print_test("CodeFile integration", False, f"Error: {e}")
        return False


async def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("  TypeScript AST Provider - Comprehensive Verification")
    print("=" * 70)

    tests: List[tuple[str, callable]] = [
        ("Entry Point Registration", verify_entry_point),
        ("Direct Import", verify_direct_import),
        ("Provider Metadata", verify_metadata),
        ("Dependency Validation", verify_dependencies),
        ("TypeScript Parsing", verify_typescript_parsing),
        ("TSX Parsing", verify_tsx_parsing),
        ("Decorator Extraction", verify_decorator_extraction),
        ("Generic Type Support", verify_generic_support),
        ("Warden Discovery", verify_warden_discovery),
        ("CodeFile Integration", verify_codefile_integration),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ ERROR in {test_name}: {e}")
            results.append((test_name, False))

    # Summary
    print_header("VERIFICATION SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n" + "=" * 70)
        print("✅ ALL VERIFICATION TESTS PASSED!")
        print("=" * 70)
        print("\n🎉 TypeScript AST Provider is fully integrated and working!\n")
        print("Next steps:")
        print("  1. ✅ TypeScript provider ready for production use")
        print("  2. 🚀 Provider supports both .ts and .tsx files")
        print("  3. 💡 Decorators, generics, and modern TS features supported\n")
        return 0
    else:
        print("\n" + "=" * 70)
        print(f"❌ {total - passed} test(s) failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
