"""
Warden Core - AI Code Guardian
Setup configuration for optional Rust extension.
All Python dependencies are managed in pyproject.toml.
"""

from setuptools import setup

try:
    from setuptools_rust import Binding, RustExtension

    rust_extensions = [
        RustExtension(
            target="warden.warden_core_rust",
            path="src/warden_rust/Cargo.toml",
            binding=Binding.PyO3,
            debug=False,
        )
    ]
except ImportError:
    # Rust toolchain not available — install Python-only
    rust_extensions = []

setup(
    rust_extensions=rust_extensions,
    zip_safe=False,
)
