from pathlib import Path
import shutil
import shutil # duplicate import removal
from importlib.metadata import version

def get_installed_version() -> str:
    """Get the currently installed version of warden-core."""
    try:
        return version("warden-core")
    except Exception:
        return "0.1.0"  # Fallback

def check_node_cli_installed() -> bool:
    """Check if warden-cli (Node.js) is installed and available."""
    # check for global executable
    if shutil.which("warden-cli"):
        return True
    
    # check if we are in dev environment where ../cli might exist
    # (This is a heuristic for local dev)
    # Assuming this file is in src/warden/cli/utils.py
    # So parents[3] is project root if inside src/warden/cli/utils.py
    # src/warden/cli/utils.py -> parents[0]=cli, [1]=warden, [2]=src, [3]=warden-core
    
    # Previous main.py was in src/warden/main.py -> parents[2] = warden-core
    # src/warden/cli/utils.py -> parents[3]
    
    dev_cli_path = Path(__file__).parents[3] / "cli"
    if dev_cli_path.exists() and (dev_cli_path / "package.json").exists():
        return True
        
    return False
