"""
Extract contracts from OhMyLove project using UniversalExtractor.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

sys.path.insert(0, str(Path(__file__).parent / "src"))

from warden.validation.frames.spec.extractors.universal_extractor import UniversalContractExtractor
from warden.validation.frames.spec.models import PlatformRole
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()


async def extract_contracts():
    """Extract contracts from OhMyLove."""
    
    console.print("\n[bold cyan]🔍 OhMyLove Contract Extraction[/bold cyan]\n")
    
    # Paths
    flutter_path = Path("/Users/alper/Documents/Development/Personal/OhMyLove/lib")
    backend_path = Path("/Users/alper/Documents/Development/Personal/OhMyLove/functions")
    
    # Initialize LLM Service (Qwen via Ollama)
    try:
        from warden.llm.providers.ollama import OllamaClient
        from warden.llm.config import ProviderConfig
        
        config = ProviderConfig(
            endpoint="http://localhost:11434",
            default_model="qwen2.5-coder:0.5b"  # Use installed model
        )
        llm_service = OllamaClient(config)
        console.print("[green]✓ LLM Service initialized (Qwen 0.5b via Ollama)[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠ LLM Service initialization failed: {e}[/yellow]")
        llm_service = None

    # Extract Flutter (Consumer)
    console.print(Panel("[bold]Flutter Consumer (Mobile App)[/bold]", style="blue"))
    console.print("📱 Extracting contract from Flutter app...")
    
    flutter_extractor = UniversalContractExtractor(
        project_root=flutter_path,
        role=PlatformRole.CONSUMER,
        llm_service=llm_service,
        semantic_search_service=None,
    )
    
    flutter_contract = await flutter_extractor.extract()
    
    console.print(f"\n[green]✓ Flutter Contract[/green]")
    console.print(f"  • Operations: [bold]{len(flutter_contract.operations)}[/bold]")
    console.print(f"  • Models: {len(flutter_contract.models)}")
    console.print(f"  • Enums: {len(flutter_contract.enums)}")
    
    if flutter_contract.operations:
        console.print("\n[bold cyan]Operations Found:[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", width=30)
        table.add_column("Type", style="yellow", width=12)
        table.add_column("File", style="green", width=40)
        table.add_column("Line", justify="right", width=6)
        
        for op in flutter_contract.operations[:20]:  # Show first 20
            file_name = Path(op.source_file).name if op.source_file else "?"
            table.add_row(
                op.name[:30],
                op.operation_type.value,
                file_name[:40],
                str(op.source_line) if op.source_line else "?"
            )
        
        console.print(table)
        
        if len(flutter_contract.operations) > 20:
            console.print(f"\n[dim]... and {len(flutter_contract.operations) - 20} more operations[/dim]")
    else:
        console.print("\n[yellow]⚠ No operations found[/yellow]")
    
    # Extract Express (Provider)
    console.print(f"\n{Panel('[bold]Express Provider (Backend)[/bold]', style='blue')}")
    console.print("🔧 Extracting contract from Express backend...")
    
    express_extractor = UniversalContractExtractor(
        project_root=backend_path,
        role=PlatformRole.PROVIDER,
        llm_service=None,
        semantic_search_service=None,
    )
    
    express_contract = await express_extractor.extract()
    
    console.print(f"\n[green]✓ Express Contract[/green]")
    console.print(f"  • Operations: [bold]{len(express_contract.operations)}[/bold]")
    console.print(f"  • Models: {len(express_contract.models)}")
    console.print(f"  • Enums: {len(express_contract.enums)}")
    
    if express_contract.operations:
        console.print("\n[bold cyan]Operations Found:[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", width=30)
        table.add_column("Type", style="yellow", width=12)
        table.add_column("File", style="green", width=40)
        table.add_column("Line", justify="right", width=6)
        
        for op in express_contract.operations:
            file_name = Path(op.source_file).name if op.source_file else "?"
            table.add_row(
                op.name[:30],
                op.operation_type.value,
                file_name[:40],
                str(op.source_line) if op.source_line else "?"
            )
        
        console.print(table)
    else:
        console.print("\n[yellow]⚠ No operations found[/yellow]")
    
    # Summary
    console.print(f"\n{Panel('[bold]Extraction Summary[/bold]', style='green')}")
    
    total_ops = len(flutter_contract.operations) + len(express_contract.operations)
    console.print(f"[bold]Total Operations:[/bold] {total_ops}")
    console.print(f"  • Consumer (Flutter): {len(flutter_contract.operations)}")
    console.print(f"  • Provider (Express): {len(express_contract.operations)}")
    
    console.print(f"\n[bold]Statistics:[/bold]")
    console.print(f"  Flutter: {flutter_extractor.stats}")
    console.print(f"  Express: {express_extractor.stats}")
    
    # Save to disk
    import yaml
    output_file = Path("ohmylove.warden.yaml")
    
    def format_op(op):
        meta = op.metadata or {}
        method = meta.get('http_method', '')
        endpoint = meta.get('endpoint', '')
        
        # Construct "endpoint" field: "METHOD /path"
        if method and endpoint:
            # Ensure METHOD is uppercase and path starts with /
            method = method.upper()
            if not endpoint.startswith('/'):
                endpoint = '/' + endpoint
            ep_str = f"{method} {endpoint}".strip()
        elif endpoint:
            ep_str = endpoint
        else:
            # Fallback uses name
            ep_str = op.name
            
        return {
            "endpoint": ep_str,
            "request": meta.get('request_fields', []),
            "response": meta.get('response_fields', [])
        }

    consumer_ops = [format_op(op) for op in flutter_contract.operations]
    provider_ops = [format_op(op) for op in express_contract.operations]
    
    combined_data = {
        "name": "OhMyLove",
        "version": "1.0.0",
        "consumer": consumer_ops,
        "provider": provider_ops,
        "stats": {
            "flutter": flutter_extractor.stats,
            "express": express_extractor.stats
        }
    }
    
    with open(output_file, "w") as f:
        yaml.dump(combined_data, f, sort_keys=False, indent=2)
        
    console.print(f"\n[bold green]💾 Contract saved to: {output_file.absolute()}[/bold green]")
    

if __name__ == "__main__":
    asyncio.run(extract_contracts())
