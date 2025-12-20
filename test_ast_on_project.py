#!/usr/bin/env python3
"""
Test AST module on entire Warden project.

Scans all Python files in src/warden and parses them using the AST module.
"""

import asyncio
from pathlib import Path
from warden.ast.providers.python_ast_provider import PythonASTProvider
from warden.ast.domain import CodeLanguage, ASTNodeType


async def scan_project():
    """Scan entire Warden project."""
    provider = PythonASTProvider()

    src_dir = Path("src/warden")
    python_files = list(src_dir.rglob("*.py"))

    print(f"🔍 Scanning Warden Project")
    print(f"=" * 60)
    print(f"Directory: {src_dir}")
    print(f"Total Python files: {len(python_files)}\n")

    # Statistics
    total_files = 0
    successful_parses = 0
    failed_parses = 0
    total_classes = 0
    total_functions = 0
    total_async_functions = 0
    total_imports = 0
    total_parse_time = 0.0

    errors = []

    for file_path in python_files:
        try:
            source_code = file_path.read_text()
            result = await provider.parse(source_code, CodeLanguage.PYTHON, str(file_path))

            total_files += 1

            if result.is_success():
                successful_parses += 1

                # Count nodes
                classes = result.ast_root.find_nodes(ASTNodeType.CLASS)
                functions = result.ast_root.find_nodes(ASTNodeType.FUNCTION)
                async_funcs = [f for f in functions if f.attributes.get("async")]
                imports = result.ast_root.find_nodes(ASTNodeType.IMPORT)

                total_classes += len(classes)
                total_functions += len(functions)
                total_async_functions += len(async_funcs)
                total_imports += len(imports)
                total_parse_time += result.parse_time_ms

                # Show progress for files with content
                if len(classes) > 0 or len(functions) > 0:
                    print(f"✅ {file_path.relative_to(src_dir)}")
                    print(f"   Classes: {len(classes)}, Functions: {len(functions)}, "
                          f"Async: {len(async_funcs)}, Imports: {len(imports)}, "
                          f"Time: {result.parse_time_ms:.2f}ms")
            else:
                failed_parses += 1
                errors.append((file_path, result.errors))
                print(f"❌ {file_path.relative_to(src_dir)}")
                for error in result.errors:
                    print(f"   Error: {error.message}")

        except Exception as e:
            failed_parses += 1
            errors.append((file_path, [str(e)]))
            print(f"❌ {file_path.relative_to(src_dir)}: {e}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"📊 SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total files scanned:     {total_files}")
    print(f"✅ Successful parses:     {successful_parses}")
    print(f"❌ Failed parses:         {failed_parses}")
    print(f"\n📈 CODE STATISTICS")
    print(f"{'=' * 60}")
    print(f"Total classes:           {total_classes}")
    print(f"Total functions/methods: {total_functions}")
    print(f"Total async functions:   {total_async_functions}")
    print(f"Total imports:           {total_imports}")
    print(f"\n⚡ PERFORMANCE")
    print(f"{'=' * 60}")
    print(f"Total parse time:        {total_parse_time:.2f}ms")
    print(f"Average per file:        {total_parse_time / total_files:.2f}ms")

    if errors:
        print(f"\n❌ ERRORS ({len(errors)})")
        print(f"{'=' * 60}")
        for file_path, error_list in errors:
            print(f"{file_path.relative_to(src_dir)}:")
            for err in error_list:
                print(f"  - {err}")
    else:
        print(f"\n🎉 ALL FILES PARSED SUCCESSFULLY!")

    # Success rate
    success_rate = (successful_parses / total_files * 100) if total_files > 0 else 0
    print(f"\n✨ Success Rate: {success_rate:.1f}%")

    return success_rate == 100.0


if __name__ == "__main__":
    success = asyncio.run(scan_project())
    exit(0 if success else 1)
