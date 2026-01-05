import typer
import subprocess
from pathlib import Path
from rich.console import Console
from warden.cli.utils import get_installed_version

console = Console()

def init_command(
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
          pip install warden-core=={get_installed_version()}

      - name: Run Warden Scan
        continue-on-error: true
        run: |
          warden scan . --format sarif --output warden-report.sarif

      - name: Archive SARIF Artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: warden-scan-results
          path: warden-report.sarif

"""
        with open(workflow_path, "w") as f:
            f.write(workflow_content)
        console.print(f"[bold green]✨ Created GitHub Actions workflow: {workflow_path}[/bold green]")
        console.print("[dim]This workflow will run Warden scans based on your branch configuration.[/dim]")
