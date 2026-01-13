#!/usr/bin/env python3
"""
Generate Python gRPC code from warden.proto

Usage:
    python scripts/generate_grpc.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Generate gRPC code from proto file."""
    project_root = Path(__file__).parent.parent
    proto_dir = project_root / "src" / "warden" / "grpc" / "protos"
    output_dir = project_root / "src" / "warden" / "grpc" / "generated"
    proto_file = proto_dir / "warden.proto"

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create __init__.py
    init_file = output_dir / "__init__.py"
    init_file.write_text(
        '"""Generated gRPC code for Warden."""\n\n'
        'from .warden_pb2 import *\n'
        'from .warden_pb2_grpc import *\n'
    )

    print(f"Proto file: {proto_file}")
    print(f"Output dir: {output_dir}")

    # Check if proto file exists
    if not proto_file.exists():
        print(f"Error: Proto file not found: {proto_file}")
        sys.exit(1)

    # Generate Python code using grpcio-tools
    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--python_out={output_dir}",
        f"--grpc_python_out={output_dir}",
        str(proto_file)
    ]

    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error generating gRPC code:")
        print(result.stderr)
        sys.exit(1)

    print("Successfully generated:")
    print(f"  - {output_dir}/warden_pb2.py")
    print(f"  - {output_dir}/warden_pb2_grpc.py")

    # Fix import in generated grpc file
    grpc_file = output_dir / "warden_pb2_grpc.py"
    if grpc_file.exists():
        content = grpc_file.read_text()
        # Fix relative import
        content = content.replace(
            "import warden_pb2 as warden__pb2",
            "from . import warden_pb2 as warden__pb2"
        )
        grpc_file.write_text(content)
        print("  - Fixed imports in warden_pb2_grpc.py")

    print("\nDone! You can now use:")
    print("  from warden.grpc.generated import warden_pb2, warden_pb2_grpc")


if __name__ == "__main__":
    main()
