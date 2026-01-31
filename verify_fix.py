
import sys
import os
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

def verify_safety_fix():
    print("Verifying Path Safety Fix...")
    try:
        from warden.mcp.infrastructure.mcp_config_paths import is_safe_to_create_dir
    except ImportError as e:
        print(f"FAILED to import: {e}")
        return False

    # Test Cases
    home = Path.home()
    
    # Valid case: The parent of a known config (e.g. Claude Code CLI)
    # path: ~/.config/claude-code (derived from get_mcp_config_paths)
    valid_path = home / ".config" / "claude-code"
    
    cases = [
        (valid_path, True, "Valid known config dir"),
        (home / ".config", True, "Valid parent of config dir"),
        (home / ".config" / "myapp_random", False, "Unknown app dir (Strict check)"),
        (Path("/tmp/malicious/AppData/payload"), False, "Malicious partial match"),
        (Path("/Users/user/Downloads/Fake.config/malware"), False, "Malicious substring"),
        (Path("../../AppData"), False, "Traversal"),
    ]

    all_passed = True
    for path, expected, desc in cases:
        result = is_safe_to_create_dir(path)
        if result != expected:
            print(f"  [FAIL] {desc}: Path='{path}' Expected={expected} Actual={result}")
            all_passed = False
        else:
             print(f"  [PASS] {desc}")
    
    return all_passed

def verify_registration_service():
    print("\nVerifying Registration Service Structure...")
    try:
        from warden.mcp.domain.services.mcp_registration_service import MCPRegistrationService
        print("  [PASS] Service class exists and is importable")
        return True
    except ImportError as e:
        print(f"  [FAIL] Could not import service: {e}")
        return False

if __name__ == "__main__":
    safety_ok = verify_safety_fix()
    service_ok = verify_registration_service()
    
    if safety_ok and service_ok:
        print("\n✅ ALL CRITICAL FIXES VERIFIED")
        sys.exit(0)
    else:
        print("\n❌ VERIFICATION FAILED")
        sys.exit(1)
