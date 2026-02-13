#!/usr/bin/env python3
"""
API Documentation Generator

Automatically generates API documentation from Python docstrings.
Outputs markdown documentation for all public APIs.

Issue #82 Fix: Auto-generate API docs from docstrings
"""

import ast
import os
from pathlib import Path
from typing import List, Dict, Any


class DocstringExtractor(ast.NodeVisitor):
    """Extract docstrings and type hints from Python modules."""

    def __init__(self):
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.current_class: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function definition and extract documentation."""
        doc = ast.get_docstring(node)
        if doc and not node.name.startswith("_"):  # Public functions only
            func_info = {
                "name": node.name,
                "docstring": doc,
                "args": [arg.arg for arg in node.args.args],
                "returns": ast.unparse(node.returns) if node.returns else "None",
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "class": self.current_class,
            }

            if self.current_class:
                # Add to last class
                if self.classes:
                    self.classes[-1]["methods"].append(func_info)
            else:
                self.functions.append(func_info)

        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # Handle async functions

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definition and extract documentation."""
        doc = ast.get_docstring(node)
        if doc and not node.name.startswith("_"):  # Public classes only
            self.current_class = node.name
            class_info = {
                "name": node.name,
                "docstring": doc,
                "methods": [],
                "bases": [ast.unparse(base) for base in node.bases],
            }
            self.classes.append(class_info)

        self.generic_visit(node)
        self.current_class = None


def generate_markdown(module_path: Path, extractor: DocstringExtractor) -> str:
    """Generate markdown documentation from extracted info."""
    lines = []

    # Module header
    module_name = module_path.stem
    lines.append(f"# {module_name}")
    lines.append("")
    lines.append(f"**File**: `{module_path.relative_to(Path.cwd())}`")
    lines.append("")

    # Classes
    if extractor.classes:
        lines.append("## Classes")
        lines.append("")

        for cls in extractor.classes:
            lines.append(f"### {cls['name']}")
            if cls["bases"]:
                lines.append(f"**Inherits from**: {', '.join(cls['bases'])}")
            lines.append("")
            lines.append(cls["docstring"])
            lines.append("")

            if cls["methods"]:
                lines.append("#### Methods")
                lines.append("")
                for method in cls["methods"]:
                    async_prefix = "async " if method["is_async"] else ""
                    args_str = ", ".join(method["args"])
                    lines.append(f"##### `{async_prefix}{method['name']}({args_str})`")
                    lines.append("")
                    lines.append(method["docstring"])
                    lines.append("")
                    if method["returns"] != "None":
                        lines.append(f"**Returns**: `{method['returns']}`")
                        lines.append("")

    # Functions
    if extractor.functions:
        lines.append("## Functions")
        lines.append("")

        for func in extractor.functions:
            async_prefix = "async " if func["is_async"] else ""
            args_str = ", ".join(func["args"])
            lines.append(f"### `{async_prefix}{func['name']}({args_str})`")
            lines.append("")
            lines.append(func["docstring"])
            lines.append("")
            if func["returns"] != "None":
                lines.append(f"**Returns**: `{func['returns']}`")
                lines.append("")

    return "\n".join(lines)


def generate_docs_for_directory(src_dir: Path, output_dir: Path):
    """Generate API documentation for all Python files in a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for py_file in src_dir.rglob("*.py"):
        # Skip __init__.py and private modules
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            extractor = DocstringExtractor()
            extractor.visit(tree)

            # Only generate docs if there's content
            if extractor.functions or extractor.classes:
                markdown = generate_markdown(py_file, extractor)

                # Output path mirrors source structure
                rel_path = py_file.relative_to(src_dir)
                output_path = output_dir / rel_path.with_suffix(".md")
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(markdown)

                print(f"✓ Generated: {output_path}")

        except Exception as e:
            print(f"✗ Failed to process {py_file}: {e}")


def main():
    """Generate API documentation for Warden."""
    src_dir = Path("src/warden")
    output_dir = Path("docs/api")

    print("Generating API Documentation...")
    print(f"Source: {src_dir}")
    print(f"Output: {output_dir}")
    print()

    generate_docs_for_directory(src_dir, output_dir)

    # Generate index
    index_content = """# Warden API Documentation

Auto-generated API documentation from Python docstrings.

## Modules

"""
    for md_file in sorted(output_dir.rglob("*.md")):
        if md_file.name != "index.md":
            rel_path = md_file.relative_to(output_dir)
            module_name = str(rel_path.with_suffix("")).replace(os.sep, ".")
            index_content += f"- [{module_name}]({rel_path})\n"

    with open(output_dir / "index.md", "w") as f:
        f.write(index_content)

    print()
    print(f"✓ Generated index: {output_dir / 'index.md'}")
    print("Done!")


if __name__ == "__main__":
    main()
