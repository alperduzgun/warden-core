"""
Warden Core - AI Code Guardian
Setup configuration for Rust extension only.
All Python dependencies are managed in pyproject.toml.
"""

from setuptools import setup
from setuptools_rust import Binding, RustExtension

setup(
    rust_extensions=[
        RustExtension(
            target="warden.warden_core_rust",
            path="src/warden_rust/Cargo.toml",
            binding=Binding.PyO3,
            debug=False,
        )
    ],
    zip_safe=False,
)
