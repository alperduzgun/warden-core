"""
CLI commands for Warden infrastructure management.

Provides commands for installing Git hooks, generating CI templates, and more.
"""

import typer
from pathlib import Path
from typing import Optional, List
from rich.console import Console

from warden.infrastructure.hooks.installer import HookInstaller
from warden.infrastructure.ci.github_actions import (
    GitHubActionsTemplate,
    GitHubActionsConfig,
)
from warden.infrastructure.ci.gitlab_ci import GitLabCITemplate, GitLabCIConfig
from warden.infrastructure.ci.azure_pipelines import (
    AzurePipelinesTemplate,
    AzurePipelinesConfig,
)
from warden.infrastructure.installer import AutoInstaller

app = typer.Typer(
    name="infrastructure",
    help="Infrastructure management commands (Git hooks, CI templates, Docker)",
)
console = Console()


@app.command(name="install-hooks")
def install_hooks_cmd(
    hook: Optional[List[str]] = typer.Option(
        None,
        "--hook",
        "-h",
        help="Specific hooks to install: pre-commit, pre-push (default: all)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing hooks",
    ),
):
    """Install Git hooks for Warden validation."""
    console.print("🛡️  Installing Warden Git hooks...")

    # Find git directory
    git_dir = HookInstaller.find_git_dir()
    if git_dir is None:
        console.print("❌ Error: Not a git repository", style="red")
        raise typer.Exit(1)

    # Validate hook names
    if hook:
        valid_hooks = ["pre-commit", "pre-push"]
        for h in hook:
            if h not in valid_hooks:
                console.print(f"❌ Invalid hook: {h}", style="red")
                console.print(f"Valid hooks: {', '.join(valid_hooks)}")
                raise typer.Exit(1)

    # Install hooks
    hooks_to_install = hook if hook else None
    results = HookInstaller.install_hooks(
        hooks=hooks_to_install,
        git_dir=git_dir,
        force=force,
    )

    # Display results
    success_count = 0
    for result in results:
        if result.installed:
            console.print(f"✓ {result.hook_name}: {result.message}", style="green")
            success_count += 1
        else:
            console.print(f"⚠️  {result.hook_name}: {result.message}", style="yellow")

    if success_count > 0:
        console.print(
            f"\n✓ Installed {success_count} hook(s) successfully!", style="green"
        )
    else:
        console.print("\n⚠️  No hooks were installed.", style="yellow")


@app.command(name="uninstall-hooks")
def uninstall_hooks_cmd(
    hook: Optional[List[str]] = typer.Option(
        None,
        "--hook",
        "-h",
        help="Specific hooks to uninstall (default: all)",
    ),
):
    """Uninstall Git hooks for Warden."""
    console.print("🛡️  Uninstalling Warden Git hooks...")

    # Find git directory
    git_dir = HookInstaller.find_git_dir()
    if git_dir is None:
        console.print("❌ Error: Not a git repository", style="red")
        raise typer.Exit(1)

    # Uninstall hooks
    hooks_to_uninstall = hook if hook else None
    results = HookInstaller.uninstall_hooks(
        hooks=hooks_to_uninstall,
        git_dir=git_dir,
    )

    # Display results
    success_count = 0
    for result in results:
        if not result.installed:
            console.print(f"✓ {result.hook_name}: {result.message}", style="green")
            success_count += 1
        else:
            console.print(f"⚠️  {result.hook_name}: {result.message}", style="yellow")

    if success_count > 0:
        console.print(
            f"\n✓ Uninstalled {success_count} hook(s) successfully!", style="green"
        )
    else:
        console.print("\n⚠️  No hooks were uninstalled.", style="yellow")


@app.command(name="list-hooks")
def list_hooks_cmd():
    """List installed Git hooks status."""
    console.print("🛡️  Warden Git Hooks Status\n")

    # Find git directory
    git_dir = HookInstaller.find_git_dir()
    if git_dir is None:
        console.print("❌ Error: Not a git repository", style="red")
        raise typer.Exit(1)

    # Get hook status
    hook_status = HookInstaller.list_hooks(git_dir)

    # Display status
    for hook_name, is_installed in hook_status.items():
        status = "✓ Installed" if is_installed else "✗ Not installed"
        color = "green" if is_installed else "dim"
        console.print(f"{hook_name:15} {status}", style=color)


@app.command(name="ci-init")
def ci_init_cmd(
    provider: str = typer.Option(
        "github",
        "--provider",
        "-p",
        help="CI provider: github, gitlab, azure",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: auto-detect based on provider)",
    ),
    frame: Optional[List[str]] = typer.Option(
        None,
        "--frame",
        "-f",
        help="Validation frames to run (default: security, fuzz, property)",
    ),
    fail_on_issues: bool = typer.Option(
        True,
        "--fail-on-issues/--no-fail-on-issues",
        help="Fail pipeline if issues found",
    ),
):
    """Generate CI/CD configuration template."""
    console.print(f"🛡️  Generating {provider} CI template...")

    # Validate provider
    valid_providers = ["github", "gitlab", "azure"]
    if provider not in valid_providers:
        console.print(f"❌ Invalid provider: {provider}", style="red")
        console.print(f"Valid providers: {', '.join(valid_providers)}")
        raise typer.Exit(1)

    # Determine output path
    if output:
        output_path = Path(output)
    else:
        if provider == "github":
            output_path = Path(".github/workflows/warden.yml")
        elif provider == "gitlab":
            output_path = Path(".gitlab-ci.yml")
        elif provider == "azure":
            output_path = Path("azure-pipelines.yml")

    # Check if file exists
    if output_path.exists():
        overwrite = typer.confirm(f"File {output_path} already exists. Overwrite?")
        if not overwrite:
            console.print("Aborted.", style="yellow")
            raise typer.Exit(0)

    # Generate template
    frames = list(frame) if frame else None

    try:
        if provider == "github":
            config = GitHubActionsConfig(
                frames=frames,
                fail_on_issues=fail_on_issues,
            )
            GitHubActionsTemplate.save_to_file(config, output_path)

        elif provider == "gitlab":
            config = GitLabCIConfig(
                frames=frames,
                fail_on_issues=fail_on_issues,
            )
            GitLabCITemplate.save_to_file(config, output_path)

        elif provider == "azure":
            config = AzurePipelinesConfig(
                frames=frames,
                fail_on_issues=fail_on_issues,
            )
            AzurePipelinesTemplate.save_to_file(config, output_path)

        console.print(f"✓ CI template generated: {output_path}", style="green")
        console.print("\nNext steps:")
        console.print(f"1. Review and customize {output_path}")
        console.print("2. Commit and push to your repository")
        console.print("3. CI will run Warden on pull requests")

    except Exception as e:
        console.print(f"❌ Error generating template: {str(e)}", style="red")
        raise typer.Exit(1)


@app.command(name="ci-validate")
def ci_validate_cmd(
    config_file: str = typer.Argument(
        ...,
        help="Path to CI configuration file",
    ),
    provider: str = typer.Option(
        ...,
        "--provider",
        "-p",
        help="CI provider: github, gitlab, azure",
    ),
):
    """Validate CI/CD configuration file."""
    console.print(f"🛡️  Validating {provider} CI config: {config_file}")

    config_path = Path(config_file)

    if not config_path.exists():
        console.print(f"❌ File not found: {config_file}", style="red")
        raise typer.Exit(1)

    # Validate provider
    valid_providers = ["github", "gitlab", "azure"]
    if provider not in valid_providers:
        console.print(f"❌ Invalid provider: {provider}", style="red")
        console.print(f"Valid providers: {', '.join(valid_providers)}")
        raise typer.Exit(1)

    try:
        if provider == "github":
            is_valid = GitHubActionsTemplate.validate_workflow(config_path)
        elif provider == "gitlab":
            is_valid = GitLabCITemplate.validate_pipeline(config_path)
        elif provider == "azure":
            is_valid = AzurePipelinesTemplate.validate_pipeline(config_path)

        if is_valid:
            console.print(f"✓ Configuration is valid!", style="green")
        else:
            console.print(f"❌ Configuration is invalid!", style="red")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"❌ Validation error: {str(e)}", style="red")
        raise typer.Exit(1)


@app.command(name="detect-ci")
def detect_ci_cmd():
    """Detect current CI/CD platform from environment."""
    console.print("🛡️  Detecting CI/CD platform...\n")

    platform = AutoInstaller.detect_ci_platform()

    if platform:
        console.print(f"✓ Detected platform: [bold cyan]{platform}[/bold cyan]")

        # Show environment info
        env_info = AutoInstaller.get_ci_env_info()
        if env_info:
            console.print("\nEnvironment variables:")
            for key, value in env_info.items():
                # Truncate long values
                display_value = value[:50] + "..." if len(value) > 50 else value
                console.print(f"  [dim]{key}:[/dim] {display_value}")
    else:
        console.print("⚠️  Not running in a recognized CI/CD platform", style="yellow")


@app.command(name="docker-init")
def docker_init_cmd(
    output: str = typer.Option(
        "Dockerfile.warden",
        "--output",
        "-o",
        help="Output Dockerfile path",
    ),
):
    """Generate Dockerfile for Warden."""
    console.print("🛡️  Generating Dockerfile for Warden...")

    output_path = Path(output)

    # Check if file exists
    if output_path.exists():
        overwrite = typer.confirm(f"File {output_path} already exists. Overwrite?")
        if not overwrite:
            console.print("Aborted.", style="yellow")
            raise typer.Exit(0)

    # Generate Dockerfile
    try:
        dockerfile_content = AutoInstaller.generate_dockerfile()
        output_path.write_text(dockerfile_content)

        console.print(f"✓ Dockerfile generated: {output_path}", style="green")
        console.print("\nNext steps:")
        console.print(f"1. docker build -f {output_path} -t warden-analyzer .")
        console.print("2. docker run warden-analyzer")

    except Exception as e:
        console.print(f"❌ Error generating Dockerfile: {str(e)}", style="red")
        raise typer.Exit(1)


# Export the app
__all__ = ["app"]
