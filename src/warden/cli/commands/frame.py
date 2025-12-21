"""
Warden Frame Management CLI

Commands:
    warden frame create <name>    - Create new custom frame
    warden frame list             - List all available frames
    warden frame info <id>        - Show frame details
    warden frame validate <path>  - Validate frame structure
"""

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
import yaml

from warden.validation.infrastructure.frame_registry import get_registry
from warden.validation.domain.enums import FrameCategory, FramePriority, FrameScope

app = typer.Typer(
    name="frame",
    help="Manage custom validation frames",
    no_args_is_help=True,
)
console = Console()


@app.command()
def create(
    name: str = typer.Argument(..., help="Frame name (e.g., redis-security)"),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory (default: ~/.warden/frames/<name>)",
    ),
    category: str = typer.Option(
        "global",
        "--category",
        "-c",
        help="Frame category: global | language-specific | framework-specific",
    ),
    priority: str = typer.Option(
        "medium",
        "--priority",
        "-p",
        help="Frame priority: critical | high | medium | low",
    ),
    blocker: bool = typer.Option(
        False, "--blocker", "-b", help="Mark as blocker (fails validation if issues found)"
    ),
    author: Optional[str] = typer.Option(
        None, "--author", "-a", help="Author name (default: current user)"
    ),
):
    """
    Create a new custom validation frame from template.

    Examples:
        warden frame create redis-security
        warden frame create my-validator --priority critical --blocker
        warden frame create aws-compliance --output ./custom-frames
    """
    console.print(f"\n[cyan]🛠️  Creating custom frame: {name}[/cyan]\n")

    # Determine output directory
    if output_dir is None:
        output_dir = Path.home() / ".warden" / "frames" / name
    else:
        output_dir = output_dir / name

    # Check if frame already exists
    if output_dir.exists():
        console.print(
            f"[red]❌ Frame directory already exists: {output_dir}[/red]"
        )
        raise typer.Exit(1)

    # Create directory structure
    try:
        _create_frame_structure(
            name=name,
            output_dir=output_dir,
            category=category,
            priority=priority,
            blocker=blocker,
            author=author,
        )

        console.print(f"[green]✅ Frame created successfully![/green]\n")
        console.print(f"[dim]Location:[/dim] {output_dir}\n")

        # Show next steps
        _show_next_steps(name, output_dir)

    except Exception as e:
        console.print(f"[red]❌ Failed to create frame: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def list(
    show_community: bool = typer.Option(
        True, "--community/--no-community", help="Show community frames"
    ),
    show_builtin: bool = typer.Option(
        True, "--builtin/--no-builtin", help="Show built-in frames"
    ),
):
    """
    List all available validation frames.

    Shows both built-in and community frames with metadata.
    """
    console.print("\n[cyan]🔍 Discovering available frames...[/cyan]\n")

    # Discover all frames
    registry = get_registry()
    frames = registry.discover_all()

    if not frames:
        console.print("[yellow]No frames found.[/yellow]")
        return

    # Create table
    table = Table(title="Available Validation Frames", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Category", style="magenta")
    table.add_column("Priority", style="yellow")
    table.add_column("Blocker", style="red")
    table.add_column("Source", style="green")

    # Add rows
    for frame_class in frames:
        instance = frame_class()

        # Determine source (built-in vs community)
        source = _determine_frame_source(frame_class)

        # Filter based on options
        if source == "built-in" and not show_builtin:
            continue
        if source == "community" and not show_community:
            continue

        # Format priority (handle both enum and string)
        if hasattr(instance.priority, "value"):
            priority_str = str(instance.priority.value)
        else:
            priority_str = str(instance.priority)

        table.add_row(
            instance.frame_id,
            instance.name,
            instance.category.value if hasattr(instance.category, "value") else str(instance.category),
            priority_str,
            "✓" if instance.is_blocker else "✗",
            source,
        )

    console.print(table)
    console.print(f"\n[dim]Total frames: {len(frames)}[/dim]\n")


@app.command()
def info(
    frame_id: str = typer.Argument(..., help="Frame ID to show details for"),
):
    """
    Show detailed information about a specific frame.

    Example:
        warden frame info security
        warden frame info redis-security
    """
    console.print(f"\n[cyan]🔍 Looking up frame: {frame_id}[/cyan]\n")

    # Get frame from registry
    registry = get_registry()
    registry.discover_all()
    frame_class = registry.get(frame_id)

    if not frame_class:
        console.print(f"[red]❌ Frame not found: {frame_id}[/red]")
        raise typer.Exit(1)

    # Instantiate frame
    instance = frame_class()

    # Create info panel
    info_text = f"""
[bold cyan]{instance.name}[/bold cyan]
[dim]ID:[/dim] {instance.frame_id}
[dim]Category:[/dim] {instance.category.value if hasattr(instance.category, 'value') else str(instance.category)}
[dim]Priority:[/dim] {instance.priority.value if hasattr(instance.priority, 'value') else str(instance.priority)}
[dim]Blocker:[/dim] {instance.is_blocker}
[dim]Version:[/dim] {instance.version}
[dim]Author:[/dim] {instance.author}

[bold]Description:[/bold]
{instance.description}

[bold]Applicability:[/bold]
{', '.join([str(app) for app in instance.applicability])}

[bold]Source:[/bold]
{_determine_frame_source(frame_class)}
"""

    console.print(Panel(info_text, border_style="cyan"))


@app.command()
def validate(
    frame_path: Path = typer.Argument(
        ..., help="Path to frame directory to validate", exists=True, file_okay=False
    ),
):
    """
    Validate custom frame structure and configuration.

    Checks:
    - frame.yaml exists and is valid
    - frame.py exists and contains ValidationFrame subclass
    - Required fields are present
    - Configuration schema is valid

    Example:
        warden frame validate ~/.warden/frames/redis-security
    """
    console.print(f"\n[cyan]🔍 Validating frame: {frame_path}[/cyan]\n")

    errors = []
    warnings = []

    # Check frame.yaml
    frame_yaml = frame_path / "frame.yaml"
    if not frame_yaml.exists():
        errors.append("Missing frame.yaml")
    else:
        try:
            with open(frame_yaml) as f:
                metadata = yaml.safe_load(f)

            # Validate required fields
            required_fields = ["name", "id", "version", "author", "description"]
            for field in required_fields:
                if field not in metadata:
                    errors.append(f"Missing required field in frame.yaml: {field}")

            # Validate category
            if "category" in metadata:
                valid_categories = ["global", "language-specific", "framework-specific"]
                if metadata["category"] not in valid_categories:
                    warnings.append(
                        f"Invalid category: {metadata['category']}. Use: {', '.join(valid_categories)}"
                    )

            # Validate priority
            if "priority" in metadata:
                valid_priorities = ["critical", "high", "medium", "low"]
                if metadata["priority"] not in valid_priorities:
                    warnings.append(
                        f"Invalid priority: {metadata['priority']}. Use: {', '.join(valid_priorities)}"
                    )

        except yaml.YAMLError as e:
            errors.append(f"Invalid YAML in frame.yaml: {e}")

    # Check frame.py
    frame_py = frame_path / "frame.py"
    if not frame_py.exists():
        errors.append("Missing frame.py")
    else:
        # Basic validation: check for ValidationFrame class
        with open(frame_py) as f:
            content = f.read()
            if "ValidationFrame" not in content:
                warnings.append("frame.py should contain a ValidationFrame subclass")

    # Check tests directory
    tests_dir = frame_path / "tests"
    if not tests_dir.exists():
        warnings.append("Missing tests/ directory (recommended)")

    # Show results
    if errors:
        console.print("[red]❌ Validation failed:[/red]\n")
        for error in errors:
            console.print(f"  [red]• {error}[/red]")
        console.print()

    if warnings:
        console.print("[yellow]⚠️  Warnings:[/yellow]\n")
        for warning in warnings:
            console.print(f"  [yellow]• {warning}[/yellow]")
        console.print()

    if not errors and not warnings:
        console.print("[green]✅ Frame is valid![/green]\n")
    elif not errors:
        console.print("[green]✅ Frame is valid (with warnings)[/green]\n")
    else:
        raise typer.Exit(1)


# ============================================================================
# Helper Functions
# ============================================================================


def _create_frame_structure(
    name: str,
    output_dir: Path,
    category: str,
    priority: str,
    blocker: bool,
    author: Optional[str],
) -> None:
    """Create frame directory structure with templates."""
    import os

    # Create directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "checks").mkdir(exist_ok=True)
    (output_dir / "tests").mkdir(exist_ok=True)

    # Determine author
    if author is None:
        author = os.environ.get("USER", "Unknown")

    # Create frame.yaml
    frame_yaml = output_dir / "frame.yaml"
    yaml_content = _generate_frame_yaml(
        name=name,
        category=category,
        priority=priority,
        blocker=blocker,
        author=author,
    )
    frame_yaml.write_text(yaml_content)

    # Create frame.py
    frame_py = output_dir / "frame.py"
    py_content = _generate_frame_py(name=name, category=category, priority=priority, blocker=blocker)
    frame_py.write_text(py_content)

    # Create checks/__init__.py
    (output_dir / "checks" / "__init__.py").write_text('"""Frame-specific checks."""\n')

    # Create tests/__init__.py
    (output_dir / "tests" / "__init__.py").write_text('"""Frame tests."""\n')

    # Create tests/test_frame.py
    test_file = output_dir / "tests" / "test_frame.py"
    test_content = _generate_test_file(name=name)
    test_file.write_text(test_content)

    # Create README.md
    readme = output_dir / "README.md"
    readme_content = _generate_readme(name=name)
    readme.write_text(readme_content)


def _generate_frame_yaml(
    name: str, category: str, priority: str, blocker: bool, author: str
) -> str:
    """Generate frame.yaml template."""
    frame_id = name.lower().replace(" ", "-").replace("_", "-")

    return f"""# Warden Custom Frame Metadata
# Generated by: warden frame create {name}

name: "{name}"
id: "{frame_id}"
version: "1.0.0"
author: "{author}"
description: "Custom validation frame for {name}"

# Frame classification
category: "{category}"  # global | language-specific | framework-specific
priority: "{priority}"     # critical | high | medium | low
scope: "file_level"     # file_level | repository_level
is_blocker: {str(blocker).lower()}

# Optional: Applicability filters
applicability:
  - language: "python"
  # - language: "typescript"
  # - framework: "fastapi"

# Optional: Required Warden version
min_warden_version: "1.0.0"
# max_warden_version: "2.0.0"

# Optional: Configuration schema
config_schema:
  enabled:
    type: "boolean"
    default: true
    description: "Enable this frame"

  # Add your custom config fields here
  # check_ssl:
  #   type: "boolean"
  #   default: true
  #   description: "Check SSL requirement"

# Optional: Tags for discoverability
tags:
  - "custom"
  - "security"
  # Add relevant tags
"""


def _generate_frame_py(name: str, category: str, priority: str, blocker: bool) -> str:
    """Generate frame.py template."""
    class_name = "".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())
    if not class_name.endswith("Frame"):
        class_name += "Frame"

    return f'''"""
{name} Validation Frame

Custom validation frame for {name}.
Generated by: warden frame create {name}
"""

import time
from typing import List, Dict, Any

from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    Finding,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class {class_name}(ValidationFrame):
    """
    {name} validation frame.

    Validates:
    - TODO: Add validation description
    - TODO: Add more checks

    Priority: {priority.upper()}
    Applicability: TODO
    """

    # Required metadata
    name = "{name}"
    description = "Custom validation frame for {name}"
    category = FrameCategory.{category.upper().replace("-", "_")}
    priority = FramePriority.{priority.upper()}
    scope = FrameScope.FILE_LEVEL
    is_blocker = {blocker}
    version = "1.0.0"
    author = "Custom Frame Developer"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        Initialize {class_name}.

        Args:
            config: Frame configuration from .warden/config.yaml
        """
        super().__init__(config)
        logger.info(
            "frame_initialized",
            frame=self.name,
            version=self.version,
        )

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """
        Execute {name} validation on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with findings
        """
        start_time = time.perf_counter()

        logger.info(
            "frame_execution_started",
            frame=self.name,
            file_path=code_file.path,
            language=code_file.language,
        )

        findings: List[Finding] = []

        # TODO: Implement your validation logic here
        # Example:
        # if "TODO" in code_file.content:
        #     findings.append(Finding(
        #         id=f"{{self.frame_id}}-todo-found",
        #         severity="low",
        #         message="TODO comment found",
        #         location=code_file.path,
        #         detail="Consider resolving TODO items before committing",
        #         code=None
        #     ))

        # Determine status
        status = "passed" if len(findings) == 0 else "failed"

        # Calculate duration
        duration = time.perf_counter() - start_time

        logger.info(
            "frame_execution_completed",
            frame=self.name,
            file_path=code_file.path,
            status=status,
            findings_count=len(findings),
            duration=f"{{duration:.2f}}s",
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=self.is_blocker,
            findings=findings,
            metadata={{
                "config": self.config,
                "file_size": code_file.size_bytes,
                "line_count": code_file.line_count,
            }},
        )
'''


def _generate_test_file(name: str) -> str:
    """Generate test_frame.py template."""
    class_name = "".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())
    if not class_name.endswith("Frame"):
        class_name += "Frame"

    return f'''"""
Tests for {name} validation frame.
"""

import pytest
from warden.validation.domain.frame import CodeFile
from frame import {class_name}


@pytest.mark.asyncio
async def test_frame_initialization():
    """Test frame can be initialized."""
    frame = {class_name}()
    assert frame.name == "{name}"
    assert frame.version == "1.0.0"


@pytest.mark.asyncio
async def test_frame_executes_without_error():
    """Test frame executes successfully."""
    frame = {class_name}()

    # Create test code file
    code_file = CodeFile(
        path="test.py",
        content="def hello(): pass",
        language="python",
    )

    # Execute frame
    result = await frame.execute(code_file)

    # Verify result
    assert result.frame_id == frame.frame_id
    assert result.frame_name == frame.name
    assert result.status in ["passed", "failed", "warning"]
    assert result.duration >= 0
    assert isinstance(result.findings, list)


@pytest.mark.asyncio
async def test_frame_detects_issues():
    """Test frame detects validation issues."""
    frame = {class_name}()

    # TODO: Create code file with known issues
    code_file = CodeFile(
        path="test.py",
        content="# TODO: Add your test code here",
        language="python",
    )

    result = await frame.execute(code_file)

    # TODO: Add assertions for expected findings
    # assert len(result.findings) > 0
    # assert result.findings[0].severity == "critical"


@pytest.mark.asyncio
async def test_frame_passes_valid_code():
    """Test frame passes on valid code."""
    frame = {class_name}()

    # TODO: Create code file with valid code
    code_file = CodeFile(
        path="test.py",
        content="def valid_function(): return True",
        language="python",
    )

    result = await frame.execute(code_file)

    # TODO: Add assertions
    # assert result.status == "passed"
    # assert len(result.findings) == 0
'''


def _generate_readme(name: str) -> str:
    """Generate README.md template."""
    return f"""# {name} Validation Frame

Custom Warden validation frame for {name}.

## Description

TODO: Add detailed description of what this frame validates.

## Features

- TODO: List key features
- TODO: Add validation checks
- TODO: Document capabilities

## Configuration

This frame supports the following configuration options in `.warden/config.yaml`:

```yaml
frames:
  {name.lower().replace(" ", "-")}:
    enabled: true
    # Add your custom config options here
```

## Examples

### Valid Code

```python
# TODO: Add example of code that passes validation
```

### Invalid Code

```python
# TODO: Add example of code that fails validation
```

## Installation

```bash
# Install frame
cp -r . ~/.warden/frames/{name.lower().replace(" ", "-")}

# Verify installation
warden frame list
```

## Development

```bash
# Run tests
pytest tests/

# Validate frame structure
warden frame validate .
```

## Author

TODO: Add author information

## License

TODO: Add license information
"""


def _show_next_steps(name: str, output_dir: Path):
    """Show next steps after frame creation."""
    console.print(Panel(
        f"""[bold]Next Steps:[/bold]

1. [cyan]Edit frame implementation:[/cyan]
   {output_dir}/frame.py

2. [cyan]Add validation logic:[/cyan]
   Implement your checks in the execute() method

3. [cyan]Write tests:[/cyan]
   {output_dir}/tests/test_frame.py

4. [cyan]Update configuration:[/cyan]
   {output_dir}/frame.yaml

5. [cyan]Validate your frame:[/cyan]
   warden frame validate {output_dir}

6. [cyan]Test your frame:[/cyan]
   pytest {output_dir}/tests/

7. [cyan]Use in validation:[/cyan]
   Frame will be auto-discovered on next warden run
""",
        title="🚀 Frame Created Successfully",
        border_style="green",
    ))


def _determine_frame_source(frame_class) -> str:
    """Determine if frame is built-in or community."""
    module = frame_class.__module__

    if module.startswith("warden.validation.frames."):
        return "built-in"
    elif module.startswith("warden.external."):
        return "community"
    else:
        return "external"


if __name__ == "__main__":
    app()
