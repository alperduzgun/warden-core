import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

class StatusReporter:
    """
    Handles parsing and displaying Warden status reports (SARIF).
    """

    @staticmethod
    def display_status(report_path: Path):
        """
        Parses the SARIF report at report_path and prints a summary table.
        """
        if not report_path.exists():
            console.print("[yellow]No report found.[/yellow]")
            console.print("Run [bold]warden scan[/bold] locally or [bold]warden status --fetch[/bold] to get CI results.")
            return

        try:
            with open(report_path) as f:
                sarif_data = json.load(f)
            
            runs = sarif_data.get("runs", [])
            if runs:
                results = runs[0].get("results", [])
                total = len(results)
                errors = sum(1 for r in results if r.get("level") == "error")
                warnings = sum(1 for r in results if r.get("level") == "warning")
                
                status_color = "red" if errors > 0 else "green"
                status_icon = "❌ FAIL" if errors > 0 else "✅ PASS"
                
                table = Table(title="Security Status (Local/CI)", box=None)
                table.add_row("Status", f"[{status_color}]{status_icon}[/{status_color}]")
                table.add_row("Critical/High", f"[{status_color}]{errors}[/{status_color}]")
                table.add_row("Warnings", str(warnings))
                table.add_row("Total Issues", str(total))
                table.add_row("Source", f"[dim]{report_path}[/dim]")
                
                console.print(Panel(table, border_style=status_color))
            else:
                 console.print("[yellow]SARIF file is valid but contains no runs.[/yellow]")

        except Exception as e:
            console.print(f"[red]Failed to parse report:[/red] {e}")
