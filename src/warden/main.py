"""
Warden CLI
==========

The main entry point for the Warden Python CLI.
Provides commands for scanning, serving, and launching the interactive chat.
"""

import asyncio
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

# Internal imports
from warden.cli_bridge.bridge import WardenBridge
from warden.services.ipc_entry import main as ipc_main
from warden.services.grpc_entry import main as grpc_main

# Initialize Typer app
app = typer.Typer(
    name="warden",
    help="AI Code Guardian - Secure your code before production",
    add_completion=False,
    no_args_is_help=True
)

# Sub-app for server commands
serve_app = typer.Typer(name="serve", help="Start Warden backend services")
app.add_typer(serve_app, name="serve")

console = Console()


def _check_node_cli_installed() -> bool:
    """Check if warden-cli (Node.js) is installed and available."""
    # check for global executable
    if shutil.which("warden-cli"):
        return True
    
    # check if we are in dev environment where ../cli might exist
    # (This is a heuristic for local dev)
    dev_cli_path = Path(__file__).parents[2] / "cli"
    if dev_cli_path.exists() and (dev_cli_path / "package.json").exists():
        return True
        
    return False



def _get_installed_version() -> str:
    """Get the currently installed version of warden-core."""
    try:
        from importlib.metadata import version
        return version("warden-core")
    except Exception:
        return "0.1.0"  # Fallback


@app.command()
def version():
    """Show Warden version info."""
    # from warden.config.config_manager import ConfigManager
    # Try to get version from package metadata if possible, else hardcode for now
    version = "0.1.0" 
    
    table = Table(show_header=False, box=None)
    table.add_row("Warden Core", f"[bold green]v{version}[/bold green]")
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)
    
    console.print(Panel(table, title="[bold blue]Warden[/bold blue]", expand=False))


@app.command()
def chat(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Run in dev mode (npm run start:raw)")
):
    """
    Launch the interactive AI Chat interface (Node.js required).
    
    This delegates to the 'warden-cli' executable or local dev script.
    """
    console.print("[bold blue]🚀 Launching Warden AI Chat...[/bold blue]")

    # 1. Check for local dev environment
    # This logic assumes we are running from src/warden/cli.py
    # so project root is 3 levels up -> warden-core/
    repo_root = Path(__file__).parents[2] 
    cli_dir = repo_root / "cli"

    if dev and cli_dir.exists():
        console.print("[dim]Using local dev version...[/dim]")
        try:
            # We need to install dependencies first if not node_modules
            if not (cli_dir / "node_modules").exists():
                console.print("[yellow]📦 Installing CLI dependencies...[/yellow]")
                subprocess.run(["npm", "install"], cwd=cli_dir, check=True)

            cmd = ["npm", "run", "start:raw"]
            subprocess.run(cmd, cwd=cli_dir)
            return
        except Exception as e:
            console.print(f"[bold red]Failed to launch dev CLI:[/bold red] {e}")
            raise typer.Exit(1)

    # 2. Check for globally installed binary
    if shutil.which("warden-cli"):
        try:
            subprocess.run(["warden-cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return
    
    # 3. Check for npx
    if shutil.which("npx"):
        try:
            console.print("[dim]warden-cli not found, trying npx @warden/cli...[/dim]")
            # Note: This assumes package is published as @warden/cli
            subprocess.run(["npx", "-y", "@warden/cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return

    console.print("[bold red]❌ Error:[/bold red] Warden Interactive CLI (Node.js) not found.")
    console.print("Please install it running: [green]npm install -g @warden/cli[/green]")
    raise typer.Exit(1)


@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to scan (file or directory)"),
    frames: Optional[List[str]] = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    format: str = typer.Option("text", "--format", help="Output format: text, json, sarif, junit, html, pdf"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
):
    """
    Run the full Warden pipeline on a file or directory.
    """
    # We defer import to avoid slow startup for other commands
    from warden.shared.infrastructure.logging import get_logger
    
    # Run async scan function
    try:
        exit_code = asyncio.run(_run_scan_async(path, frames, format, output, verbose))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        raise typer.Exit(130)


async def _run_scan_async(path: str, frames: Optional[List[str]], format: str, output: Optional[str], verbose: bool) -> int:
    """Async implementation of scan command."""
    
    console.print(f"[bold cyan]🛡️  Warden Scanner[/bold cyan]")
    console.print(f"[dim]Scanning: {path}[/dim]\n")

    # Initialize bridge
    bridge = WardenBridge(project_root=Path.cwd())
    
    # Setup stats tracking
    stats = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0
    }

    final_result_data = None

    try:
        # Execute pipeline with streaming
        async for event in bridge.execute_pipeline_stream(
            file_path=path,
            frames=frames,
            verbose=verbose
        ):
            event_type = event.get("type")
            
            if event_type == "progress":
                evt = event['event']
                data = event.get('data', {})

                if format == "text":
                    if evt == "phase_started":
                        console.print(f"[bold blue]▶ Phase:[/bold blue] {data.get('phase')}")
                    
                    elif evt == "frame_completed":
                        stats["total"] += 1
                        status = data.get('status', 'unknown')
                        name = data.get('frame_name', 'Unknown')
                        
                        if status == "passed":
                            stats["passed"] += 1
                            icon = "✅"
                            style = "green"
                        elif status == "failed":
                            stats["failed"] += 1
                            icon = "❌"
                            style = "red"
                        else:
                            stats["skipped"] += 1
                            icon = "⏭️"
                            style = "yellow"
                            
                        console.print(f"  {icon} [{style}]{name}[/{style}] ({data.get('duration', 0):.2f}s) - {data.get('issues_found', 0)} issues")

            elif event_type == "result":
                # Final results
                final_result_data = event['data']
                res = final_result_data
                
                # Check critical findings
                critical = res.get('critical_findings', 0)
                
                if format == "text":
                    table = Table(title="Scan Results")
                    table.add_column("Metric", style="cyan")
                    table.add_column("Value", style="magenta")
                    
                    table.add_row("Total Frames", str(res.get('total_frames', 0)))
                    table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                    table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")
                    table.add_row("Total Issues", str(res.get('total_findings', 0)))
                    table.add_row("Critical Issues", f"[{'red' if critical > 0 else 'green'}]{critical}[/]")
                    
                    console.print("\n", table)
                    # Status check (COMPLETED=2)
                    status_raw = res.get('status')
                    # Handle both integer and string statuses (Enums are often serialized to name or value)
                    is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]
                    
                    if verbose:
                        console.print(f"[dim]Debug: status={status_raw} ({type(status_raw).__name__}), is_success={is_success}[/dim]")
                    
                    if is_success:
                        console.print(f"\n[bold green]✨ Scan Succeeded![/bold green]")
                    else:
                        console.print(f"\n[bold red]💥 Scan Failed![/bold red]")

        # Generate report if requested
        if output and final_result_data:
            from warden.reports.generator import ReportGenerator
            generator = ReportGenerator()
            out_path = Path(output)
            
            console.print(f"\n[dim]Generating {format.upper()} report to {output}...[/dim]")
            
            if format == "json":
                generator.generate_json_report(final_result_data, out_path)
            elif format == "sarif":
                generator.generate_sarif_report(final_result_data, out_path)
            elif format == "junit":
                generator.generate_junit_report(final_result_data, out_path)
            elif format == "html":
                generator.generate_html_report(final_result_data, out_path)
            elif format == "pdf":
                generator.generate_pdf_report(final_result_data, out_path)
            
            console.print(f"[bold green]Report saved![/bold green]")

        # Save lightweight AI status file (Token-optimized)
        try:
            warden_dir = Path(".warden")
            if warden_dir.exists():
                status_file = warden_dir / "ai_status.md"
                
                # Status check (COMPLETED=2)
                status_raw = final_result_data.get('status')
                is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED"]
                status_icon = "✅ PASS" if is_success else "❌ FAIL"
                critical_count = final_result_data.get('critical_findings', 0)
                total_count = final_result_data.get('total_findings', 0)
                scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                status_content = f"""# Warden Security Status
Updated: {scan_time}

**Status**: {status_icon}
**Critical Issues**: {critical_count}
**Total Issues**: {total_count}

> [!NOTE]
> If status is FAIL, please check the full report or run `warden scan` for details.
> Do not analyze full code unless you are resolving these specific issues.
"""
                with open(status_file, "w") as f:
                    f.write(status_content)
        except Exception:
            pass # Silent fail for aux file

        # Final exit code
        status_val = final_result_data.get('status')
        if final_result_data and str(status_val).upper() in ["2", "SUCCESS", "COMPLETED"]:
            return 0
        else:
            return 1
        return 0
        
    except Exception as e:
        console.print(f"[bold red]Error during scan:[/bold red] {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1


@serve_app.command("ipc")
def serve_ipc():
    """Start the IPC server (used by CLI/GUI integration)."""
    try:
        asyncio.run(ipc_main())
    except KeyboardInterrupt:
        pass


@serve_app.command("grpc")
def serve_grpc(port: int = typer.Option(50051, help="Port to listen on")):
    """Start the gRPC server (for C#/.NET integration)."""
    try:
        asyncio.run(grpc_main(port))
    except KeyboardInterrupt:
        pass

@app.command()
def init(
    ci: bool = typer.Option(False, "--ci", help="Generate GitHub Actions CI workflow"),
):
    """
    Initialize Warden configuration, LLM setup, and CI/CD integration.
    """
    console.print("[bold blue]🛡️  Initializing Warden...[/bold blue]")

    warden_dir = Path(".warden")
    if not warden_dir.exists():
        warden_dir.mkdir(parents=True, exist_ok=True)
        console.print("[green]Created .warden directory[/green]")

    # --- Step 1: LLM Configuration Wizard ---
    console.print("\n[bold cyan]🧠 AI & LLM Configuration[/bold cyan]")
    enable_llm = typer.confirm("Enable AI capabilities (Context Analysis, Fix Suggestions)?", default=True)
    
    llm_config_str = ""
    env_vars = {}
    
    if enable_llm:
        provider = typer.prompt("Select LLM Provider", default="openai", show_default=True)
        model = typer.prompt("Select Model", default="gpt-4o")
        
        if provider == "openai":
            api_key = typer.prompt("Enter OpenAI API Key (will be saved to .env)", hide_input=True)
            env_vars["OPENAI_API_KEY"] = api_key
            llm_config_str = f"""
llm:
  provider: openai
  model: {model}
  api_key: ${{OPENAI_API_KEY}}
  timeout: 60
"""
        elif provider == "azure":
            api_key = typer.prompt("Enter Azure API Key", hide_input=True)
            endpoint = typer.prompt("Enter Azure Endpoint")
            deployment = typer.prompt("Enter Deployment Name")
            env_vars["AZURE_OPENAI_API_KEY"] = api_key
            env_vars["AZURE_OPENAI_ENDPOINT"] = endpoint
            env_vars["AZURE_OPENAI_DEPLOYMENT_NAME"] = deployment
            llm_config_str = f"""
llm:
  provider: azure
  model: {model}
  azure:
    api_key: ${{AZURE_OPENAI_API_KEY}}
    endpoint: ${{AZURE_OPENAI_ENDPOINT}}
    deployment_name: ${{AZURE_OPENAI_DEPLOYMENT_NAME}}
    api_version: 2024-02-15-preview
"""
        elif provider == "groq":
             api_key = typer.prompt("Enter Groq API Key", hide_input=True)
             env_vars["GROQ_API_KEY"] = api_key
             llm_config_str = f"""
llm:
  provider: groq
  model: {model}
  api_key: ${{GROQ_API_KEY}}
"""
        else:
             console.print(f"[yellow]Unknown provider '{provider}', generating generic config.[/yellow]")
             llm_config_str = f"""
llm:
  provider: {provider}
  model: {model}
"""

        # Write to .env
        if env_vars:
            env_path = Path(".env")
            mode = "a" if env_path.exists() else "w"
            current_env = env_path.read_text() if env_path.exists() else ""
            
            with open(env_path, mode) as f:
                if mode == "a":
                    f.write("\n")
                f.write("# Warden AI Config\n")
                for key, val in env_vars.items():
                    if key not in current_env:
                        f.write(f"{key}={val}\n")
                        console.print(f"[green]Added {key} to .env[/green]")
                    else:
                        console.print(f"[dim]{key} already in .env, skipping write[/dim]")

    # --- Step 2: Config File Generation ---
    config_path = warden_dir / "config.yaml"
    if not config_path.exists():
        project_name = Path.cwd().name
        ai_enabled = enable_llm
        # If LLM was not enabled, provider and model might not be set, default them
        provider = provider if enable_llm else "none"
        model = model if enable_llm else "none"

        config_data = {
            "project_name": project_name,
            "version": "1.0.0",
            "ai": {
                "enabled": ai_enabled,
                "provider": provider,
                "model": model
            },
            "scan": {
                "ignore": [".git", "node_modules", "venv", "__pycache__", ".warden"]
            }
        }
        import yaml
        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)
        console.print(f"[green]Created config: {config_path}[/green]")
    else:
        console.print(f"[dim]Config file exists: {config_path}[/dim]")

    # Create rules file (Default Architectural Rules)
    rules_path = warden_dir / "rules.yaml"
    if not rules_path.exists():
        default_rules = {
            "rules": [
                {
                    "id": "clean_architecture",
                    "description": "Enforce layered architecture dependencies",
                    "severity": "high",
                    "files": ["**/*.py", "**/*.ts"],
                    "pattern": {
                        "type": "dependency",
                        "disallow": [
                            {"from": "infrastructure", "to": "ui"},
                            {"from": "core", "to": "infrastructure"}
                        ]
                    }
                },
                {
                    "id": "no_print",
                    "description": "Avoid print statements, use logger or rich",
                    "severity": "medium",
                    "files": ["src/**/*.py"],
                    "pattern": {
                        "type": "regex",
                        "regex": "print\\("
                    }
                },
                {
                    "id": "secrets_check",
                    "description": "Detect hardcoded secrets",
                    "severity": "critical",
                    "files": ["**/*"],
                    "pattern": {
                        "type": "regex",
                        "regex": "(?i)(api_key|secret|password)\\s*=\\s*['\"][^'\"]+['\"]"
                    }
                }
            ]
        }
        import yaml
        with open(rules_path, "w") as f:
            yaml.dump(default_rules, f, default_flow_style=False)
        console.print(f"[green]Created rules: {rules_path}[/green]")
    else:
        console.print(f"[dim]Rules file exists: {rules_path}[/dim]")

    # --- Step 4: AI Agent Integration ---
    agent_integration = typer.confirm("\nGenerate AI Agent rules (for Cursor, Claude, etc.) to auto-check Warden status?", default=True)
    
    if agent_integration:
        console.print("\n[dim]Select which AI Agents you use (comma separated, e.g. 1,2):[/dim]")
        console.print("1. Cursor / Windsurf (.cursorrules)")
        console.print("2. Claude Code (CLAUDE.md)")
        console.print("3. Gemini / Antigravity (GEMINI.md)")
        
        choices = typer.prompt("Selection", default="1,2,3")
        selected_indices = [s.strip() for s in choices.split(",")]
        
        # Shared context content
        warden_context_instruction = """
## Security (Warden)
This project is protected by Warden (AI Code Guardian).
- **Status Check:** Read `.warden/ai_status.md` first.
- **Fail Protocol:** If status is FAIL, read `warden-report.sarif/json` for details. Do not proceed until fixed.
- **Missing Report?:** 
  1. Run `warden scan` locally (Fastest).
  2. If scan is too slow, fetch latest status: `git fetch origin warden-reports && git show origin/warden-reports:ai_status.md > .warden/ai_status.md`
  3. For full details: `git show origin/warden-reports:warden-report.sarif > warden-report.sarif`
"""

        def _inject_rules(file_path: Path, content: str, name: str):
            """Helper to inject rules without duplicating or overwriting."""
            header = "# Warden Security Rules"
            
            if file_path.exists():
                current_content = file_path.read_text()
                if header in current_content or "Warden (AI Code Guardian)" in current_content:
                    console.print(f"[dim]{name} already contains Warden rules, skipping update.[/dim]")
                    return
                
                # Append to existing
                with open(file_path, "a") as f:
                    f.write("\n\n" + content)
                console.print(f"[green]Updated {name} (Appended rules)[/green]")
            else:
                # Create new
                with open(file_path, "w") as f:
                    f.write(content)
                console.print(f"[green]Created {name}[/green]")

        # 1. Cursor/Windsurf
        if "1" in selected_indices:
            cursor_content = f"""# Warden Security Rules
# WHAT IS WARDEN?
# Warden is the AI Code Guardian for this project.
# It acts as a hard gate against vulnerabilities and technical debt.

ALLWAYS READ .warden/ai_status.md AT THE START OF A SESSION.

{warden_context_instruction}
"""
            _inject_rules(Path(".cursorrules"), cursor_content, ".cursorrules")

        # 2. Claude Code
        if "2" in selected_indices:
            claude_content = f"""# Project Instructions
{warden_context_instruction}
"""
            _inject_rules(Path("CLAUDE.md"), claude_content, "CLAUDE.md")

        # 3. Gemini / Antigravity
        if "3" in selected_indices:
            gemini_content = f"""# Gemini / Antigravity Context
{warden_context_instruction}

> **Tip for Antigravity:** When starting a task, check the status file to see if previous scans failed.
"""
            _inject_rules(Path("GEMINI.md"), gemini_content, "GEMINI.md")

    # --- Step 5: CI Configuration ---
    # Trigger CI setup if requested explicitly OR if user wants to set it up now
    if not ci:
        ci = typer.confirm("\nDo you want to set up CI/CD pipeline now?", default=False)

    if ci:
        console.print("\n[bold cyan]🔧 CI/CD Configuration[/bold cyan]")
        
        # Check for AI capability (using the recently configured env vars if present)
        import os
        has_ai = enable_llm and ("OPENAI_API_KEY" in env_vars or "AZURE_OPENAI_API_KEY" in env_vars or "OPENAI_API_KEY" in os.environ)
        
        use_ai = False
        if has_ai:
            use_ai = typer.confirm(" ✨ AI-Powered Setup detected. Analyze project to auto-configure CI?", default=True)
            
        branch_yaml = ""
        pr_section = ""
        
        if use_ai:
             try:
                 console.print("[dim]Analyzing project structure...[/dim]")
                 current_branch = "main"
                 try:
                     result = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
                     if result.returncode == 0 and result.stdout.strip():
                         current_branch = result.stdout.strip()
                 except Exception:
                     pass
                     
                 console.print(f"[green]Detected primary branch: {current_branch}[/green]")
                 branch_list = [current_branch, "dev", "develop"] if current_branch not in ["dev", "develop"] else [current_branch]
                 branch_yaml = "\n    ".join([f"- {b}" for b in branch_list])
                 
                 enable_pr = True
                 pr_section = f"""
  pull_request:
    branches:
    {branch_yaml}"""
             except Exception as e:
                 console.print(f"[yellow]AI Analysis failed ({e}), falling back to interactive mode.[/yellow]")
                 use_ai = False

        if not use_ai:
            # Interactive prompts
            branches = typer.prompt("Which branches should trigger the scan? (comma separated)", default="main, master, dev")
            branch_list = [b.strip() for b in branches.split(",")]
            branch_yaml = "\n    ".join([f"- {b}" for b in branch_list])
            
            enable_pr = typer.confirm("Enable checks on Pull Requests?", default=True)
            if enable_pr:
                pr_section = f"""
  pull_request:
    branches:
    {branch_yaml}"""

        github_dir = Path(".github/workflows")
        github_dir.mkdir(parents=True, exist_ok=True)
        
        workflow_path = github_dir / "warden-ci.yml"
        if workflow_path.exists():
            overwrite = typer.confirm(f"Workflow {workflow_path} exists. Overwrite?", default=False)
            if not overwrite:
                console.print("[yellow]Skipping CI generation.[/yellow]")
                return

        workflow_content = f"""name: Warden Code Guardian

on:
  push:
    branches:
    {branch_yaml}{pr_section}

permissions:
  contents: read
  security-events: write

jobs:
  warden-scan:
    name: Security Scan
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Warden
        run: |
          pip install --upgrade pip
          # Pinned version to ensure stability (generated by warden init)
          pip install warden-core=={_get_installed_version()}

      - name: Run Warden Scan
        continue-on-error: true
        run: |
          warden scan . --format sarif --output warden-report.sarif

      - name: Upload SARIF to GitHub
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: warden-report.sarif
          category: warden-scan

      - name: Publish Report to Shadow Branch
        if: always()
        run: |
          git config --global user.name 'Warden CI'
          git config --global user.email 'warden-ci@users.noreply.github.com'
          cp warden-report.sarif /tmp/report.sarif
          if [ -f .warden/ai_status.md ]; then cp .warden/ai_status.md /tmp/ai_status.md; fi
          git fetch origin warden-reports:warden-reports || git checkout --orphan warden-reports
          git checkout warden-reports
          cp /tmp/report.sarif ./warden-report.sarif
          if [ -f /tmp/ai_status.md ]; then cp /tmp/ai_status.md ./ai_status.md; fi
          git add warden-report.sarif ai_status.md
          git commit -m "Update Security Report [skip ci]" || echo "No changes to report"
          git push origin warden-reports

"""
        with open(workflow_path, "w") as f:
            f.write(workflow_content)
        console.print(f"[bold green]✨ Created GitHub Actions workflow: {workflow_path}[/bold green]")
        console.print("[dim]This workflow will run Warden scans based on your branch configuration.[/dim]")


def main():
    """Entry point for setuptools."""
    app()


if __name__ == "__main__":
    app()
