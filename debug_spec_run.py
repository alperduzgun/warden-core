import asyncio
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Add src to python path
sys.path.insert(0, os.path.abspath("src"))

from warden.validation.frames.spec.extractors.flutter_extractor import FlutterExtractor
from warden.validation.frames.spec.extractors.express_extractor import ExpressExtractor
from warden.validation.frames.spec.analyzer import GapAnalyzer, GapAnalyzerConfig
from warden.validation.frames.spec.spec_frame import SpecFrame
from warden.validation.frames.spec.models import PlatformRole

console = Console()

async def main():
    console.print("[bold blue]🚀 Starting SpecFrame Debug Run on OhMyLove[/bold blue]")

    # 1. Define Paths
    MOBILE_PATH = Path("/Users/alper/Documents/Development/Personal/OhMyLove")
    BACKEND_PATH = Path("/Users/alper/Documents/Development/Personal/OhMyLove/functions")

    console.print(f"📱 Mobile Path: {MOBILE_PATH}")
    console.print(f"☁️  Backend Path: {BACKEND_PATH}")

    # 2. Extract Mobile Contract
    console.print("\n[bold yellow]📦 Extracting Mobile Contract (Flutter)...[/bold yellow]")
    flutter_extractor = FlutterExtractor(MOBILE_PATH, PlatformRole.CONSUMER)
    mobile_contract = await flutter_extractor.extract()
    
    table = Table(title="Mobile Operations")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Source", style="green")
    
    for op in mobile_contract.operations:
        table.add_row(op.name, op.operation_type.value, f"{Path(op.source_file).name}:{op.source_line}")
    
    console.print(table)
    console.print(f"✅ Found {len(mobile_contract.operations)} operations on Mobile.")

    # 3. Extract Backend Contract
    console.print("\n[bold yellow]📦 Extracting Backend Contract (Express)...[/bold yellow]")
    express_extractor = ExpressExtractor(BACKEND_PATH, PlatformRole.PROVIDER)
    backend_contract = await express_extractor.extract()

    table = Table(title="Backend Operations")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Source", style="green")
    
    for op in backend_contract.operations:
        table.add_row(op.name, op.operation_type.value, f"{Path(op.source_file).name}:{op.source_line}")
    
    console.print(table)
    console.print(f"✅ Found {len(backend_contract.operations)} operations on Backend.")

    # 4. Analyze Gaps
    console.print("\n[bold yellow]🔍 Performing Gap Analysis...[/bold yellow]")
    
    # Configure Analyzer
    config = GapAnalyzerConfig(
        enable_fuzzy_matching=True,
        fuzzy_match_threshold=0.6, # Lower threshold for demo
    )
    
    # Initialize Analyzer (No LLM for this debug run unless we mock it, or just rely on fuzzy)
    analyzer = GapAnalyzer(config=config)
    
    results = analyzer.analyze(
        consumer=mobile_contract,
        provider=backend_contract,
        consumer_platform="mobile",
        provider_platform="backend"
    )

    # 5. Report Results
    console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold white]           SPECFRAME ANALYSIS RESULTS[/bold white]")
    console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]\n")
    
    r_table = Table(title="Contract Statistics", show_header=True, header_style="bold magenta")
    r_table.add_column("Metric", style="bold")
    r_table.add_column("Value", style="cyan", justify="right")
    
    # Calculate coverage percentage
    if results.total_consumer_operations > 0:
        coverage = (results.matched_operations / results.total_consumer_operations) * 100
    else:
        coverage = 0.0
    
    r_table.add_row("Consumer Operations", str(results.total_consumer_operations))
    r_table.add_row("Provider Operations", str(results.total_provider_operations))
    r_table.add_row("Matched Operations", f"[green]{results.matched_operations}[/green]")
    r_table.add_row("Coverage", f"[green]{coverage:.1f}%[/green]")
    r_table.add_row("Missing Endpoints", f"[red]{results.missing_operations}[/red]" if results.missing_operations > 0 else "[green]0[/green]")
    r_table.add_row("Zombie Endpoints", f"[yellow]{results.unused_operations}[/yellow]" if results.unused_operations > 0 else "[green]0[/green]")
    r_table.add_row("Type Mismatches", f"[orange1]{results.type_mismatches}[/orange1]" if results.type_mismatches > 0 else "[green]0[/green]")
    r_table.add_row("Total Gaps", f"[red bold]{len(results.gaps)}[/red bold]" if len(results.gaps) > 0 else "[green]0[/green]")
    
    console.print(r_table)

    # Show gap details
    if results.gaps:
        console.print("\n[bold red]⚠️  IDENTIFIED GAPS:[/bold red]\n")
        
        gap_table = Table(show_header=True, header_style="bold yellow")
        gap_table.add_column("Type", style="cyan")
        gap_table.add_column("Severity", style="magenta")
        gap_table.add_column("Message", style="white")
        gap_table.add_column("Details", style="dim")
        
        for gap in results.gaps:
            severity_color = {
                "CRITICAL": "[red bold]",
                "HIGH": "[red]",
                "MEDIUM": "[yellow]",
                "LOW": "[dim]"
            }.get(gap.severity.name, "")
            
            gap_table.add_row(
                gap.gap_type,
                f"{severity_color}{gap.severity.name}[/]",
                gap.message,
                gap.detail or ""
            )
        
        console.print(gap_table)
    else:
        console.print("\n[bold green]✅ No gaps found! Consumer and Provider contracts are perfectly aligned.[/bold green]")

    # Summary
    console.print(f"\n[bold blue]📊 Summary:[/bold blue]")
    console.print(results.summary())

if __name__ == "__main__":
    asyncio.run(main())
