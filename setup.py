"""
Warden Core - AI Code Guardian
Setup configuration for installation
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="warden-core",
    use_scm_version=True,
    author="Warden Team",
    author_email="warden@example.com",
    description="Warden - AI Code Guardian for comprehensive code validation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/alperduzgun/warden-core",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.9",
    install_requires=[
        "typer>=0.9.0",
        "rich>=13.0.0",
        "pyyaml>=6.0",
        "httpx>=0.24.0",
        "textual>=0.60.0",  # Modern TUI framework
        "textual-dev>=1.0.0",  # Textual development tools
        # Tree-sitter for multi-language AST parsing
        "tree-sitter>=0.21.0",
        "tree-sitter-javascript>=0.21.0",
        "tree-sitter-typescript>=0.21.0",
        "tree-sitter-go>=0.21.0",
        "pydantic>=2.5.0",
        "psutil>=5.9.0",
        "structlog>=24.1.0",
        "grpcio>=1.59.0",
        "grpcio-tools>=1.59.0", 
        "pydantic-settings>=2.0.0",
        "aiofiles>=23.0.0",
        "openai>=1.0.0",
        # Semantic Search & Local Embeddings
        "chromadb>=0.4.0",
        "sentence-transformers>=2.2.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
        ],
        "cloud": [
            "qdrant-client>=1.7.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "warden=warden.main:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
