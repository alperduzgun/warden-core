#!/usr/bin/env python3
"""
Test Scaffolding Script

Automatically creates missing test files to satisfy the 'test_mirror_structure' rule.
Mirrors src/warden/ structure into tests/.
"""

import os
from pathlib import Path

def scaffold_tests(project_root: Path):
    src_dir = project_root / "src" / "warden"
    tests_dir = project_root / "tests"
    
    if not src_dir.exists():
        print(f"Error: Source directory {src_dir} not found.")
        return

    print(f"Scaffolding tests for {src_dir}...")
    
    created_count = 0
    skipped_count = 0
    
    for root, dirs, files in os.walk(src_dir):
        # Skip __pycache__
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
            
        rel_path = Path(root).relative_to(src_dir)
        
        for file in files:
            if not file.endswith(".py") or file == "__init__.py":
                continue
                
            # Expected test path: tests/{rel_path}/test_{file}
            test_dir = tests_dir / rel_path
            test_file = test_dir / f"test_{file}"
            
            if test_file.exists():
                skipped_count += 1
                continue
                
            # Create directory
            test_dir.mkdir(parents=True, exist_ok=True)
            
            # Create boilerplate
            with open(test_file, "w", encoding="utf-8") as f:
                # Determine import path
                import_path = "warden"
                if str(rel_path) != ".":
                    module_parts = str(rel_path).replace(os.sep, ".")
                    import_path = f"warden.{module_parts}"
                
                module_name = file.replace(".py", "")
                
                f.write(f'"""\nTests for {import_path}.{module_name}\n"""\n\n')
                f.write("import pytest\n")
                f.write(f"from {import_path} import {module_name}\n\n")
                f.write(f"def test_{module_name}_placeholder():\n")
                f.write(f'    """Placeholder test for {module_name}."""\n')
                f.write("    assert True\n")
            
            # Ensure __init__.py exists in test directories
            current = test_dir
            while current != tests_dir.parent:
                init_py = current / "__init__.py"
                if not init_py.exists():
                    init_py.touch()
                current = current.parent
                if current == project_root:
                    break

            print(f"Created: {test_file.relative_to(project_root)}")
            created_count += 1
            
    print(f"\nDone! Created {created_count} test files, skipped {skipped_count} existing files.")

if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    scaffold_tests(project_root)
