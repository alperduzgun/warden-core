import asyncio
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Add src to python path
sys.path.insert(0, os.path.abspath("src"))

from warden.validation.frames.spec.analyzer import GapAnalyzer, GapAnalyzerConfig
from warden.validation.frames.spec.spec_frame import SpecFrame

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
    flutter_extractor = FlutterExtractor(MOBILE_PATH)
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
    express_extractor = ExpressExtractor(BACKEND_PATH)
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
    r_table = Table(title="SpecFrame Results")
    r_table.add_column("Metric", style="bold")
    r_table.add_column("Value", style="cyan")
    
    r_table.add_row("Coverage Score", f"{results.coverage_score:.1f}%")
    r_table.add_row("Missing Endpoints", str(len(results.missing_endpoints)))
    r_table.add_row("Zombie Endpoints", str(len(results.zombie_endpoints)))
    r_table.add_row("Schema Mismatches", str(len(results.schema_mismatches)))
    
    console.print(r_table)

    if results.missing_endpoints:
        console.print("\n[bold red]❌ Missing Endpoints (Mobile expects, Backend missing):[/bold red]")
        for missing in results.missing_endpoints:
            console.print(f" - {missing.consumer_operation.name} ({missing.consumer_operation.description})")

    if results.zombie_endpoints:
        console.print("\n[bold orange3]🧟 Zombie Endpoints (Backend has, Mobile unused):[/bold orange3]")
        for zombie in results.zombie_endpoints:
            console.print(f" - {zombie.provider_operation.name} ({zombie.provider_operation.description})")

    if results.matches:
        console.print("\n[bold green]✅ Successful Matches:[/bold green]")
        for match in results.matches:
             console.print(f" - {match.consumer_operation.name} <==> {match.provider_operation.name} ({match.match_type})")

if __name__ == "__main__":
    asyncio.run(main())
