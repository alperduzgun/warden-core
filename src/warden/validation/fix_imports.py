import os
from pathlib import Path
import re

def fix_imports():
    frames_dir = Path(".warden/frames")
    
    if not frames_dir.exists():
        print(f"Error: {frames_dir} does not exist.")
        return

    print(f"Fixing imports in {frames_dir}...")
    
    for frame_path in frames_dir.iterdir():
        if not frame_path.is_dir():
            continue
            
        frame_name = frame_path.name
        
        # Walk through all python files in this frame dir
        for root, dirs, files in os.walk(frame_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                    
                file_path = Path(root) / file
                
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Regex to find imports from this frame's original package
                # from warden.validation.frames.<frame_name> import ...
                # should become: from . import ...
                
                # Case 1: Import submodule
                # from warden.validation.frames.security._internal.sql... import ...
                # -> from ._internal.sql... import ...
                
                # Careful: 'from .' works if we are importing from a sibling or child.
                # If we are in 'frame.py', 'from ._internal' is correct.
                
                pattern = f"from warden\\.validation\\.frames\\.{frame_name}"
                
                if re.search(pattern, content):
                    print(f"  Fixing {file_path}")
                    new_content = re.sub(pattern, "from .", content)
                    
                    # Fix double dots if happened (unlikely with this regex but be safe)
                    # from .._internal -> from ._internal (if regex matched trailing dot)
                    
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_content)

    print("Import fix complete.")

if __name__ == "__main__":
    fix_imports()
