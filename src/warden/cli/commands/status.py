import typer
from pathlib import Path
from rich.console import Console
from warden.infrastructure.ci.github_cli import GitHubCli
from warden.reports.status_reporter import StatusReporter

console = Console()

def status_command(
    ctx: typer.Context,
    fetch: bool = typer.Option(False, "--fetch", "-f", help="Fetch latest status from CI (remote)"),
):
    """
    Check the current security status of the project.
    
    Reads from .warden/reports/warden.sarif. 
    Use --fetch to download artifacts from the latest CI run.
    """
    warden_dir = Path(".warden")
    report_dir = warden_dir / "reports"
    target_local_path = report_dir / "warden-report.sarif"

    if fetch:
        # 1. Dependency Check
        if not GitHubCli.is_installed():
            if not GitHubCli.install_interactive():
                raise typer.Exit(1)
                
        # 2. Authentication Check
        if not GitHubCli.ensure_auth():
             console.print("[red]Authentication required to fetch artifacts.[/red]")
             raise typer.Exit(1)
             
        # 3. Download Logic with Retry & Circuit Breaker
        console.print(f"[dim]Downloading 'warden-scan-results' artifact...[/dim]")
        tmp_download = warden_dir / "tmp_download"
        
        import time
        max_retries = 3
        backoff_factor = 2
        
        success = False
        for attempt in range(max_retries):
            try:
                if tmp_download.exists():
                    import shutil
                    shutil.rmtree(tmp_download)
                tmp_download.mkdir(parents=True, exist_ok=True)
                
                if GitHubCli.download_artifact("warden-scan-results", tmp_download):
                    success = True
                    break
            except Exception as e:
                wait_time = backoff_factor ** attempt
                console.print(f"[yellow]⚠️  Download failed (Attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait_time}s...[/yellow]")
                time.sleep(wait_time)
                
        if success:
            downloaded = tmp_download / "warden.sarif"
            if downloaded.exists():
                import shutil
                report_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(downloaded), str(target_local_path))
                console.print(f"  ✅ [cyan]warden.sarif[/cyan] downloaded and updated.")
            else:
                console.print(f"[yellow]Artifact downloaded but contents unexpected.[/yellow]")
        else:
             console.print(f"[bold red]❌ Failed to download artifacts after {max_retries} attempts.[/bold red]")
             raise typer.Exit(1)
        
        # Cleanup acts as "finally" but we only do it if we are done
        if tmp_download.exists():
            import shutil
            shutil.rmtree(tmp_download, ignore_errors=True)

    # 4. Display Logic
    StatusReporter.display_status(target_local_path)
