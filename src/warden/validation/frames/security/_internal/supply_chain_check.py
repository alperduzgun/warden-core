"""
Supply Chain Security Check - Typosquatting / Slopsquatting Detection.

Detects potentially malicious packages that mimic popular ones:
- Levenshtein distance-based similarity detection
- Heuristic checks for common typosquatting patterns
- Flags packages within edit distance <= 2 of a popular package

References:
- https://blog.phylum.io/typosquatting-in-the-software-supply-chain
- CWE-829: Inclusion of Functionality from Untrusted Control Sphere
"""

from __future__ import annotations

from typing import Any

from warden.build_context.models import BuildContext, BuildSystem, Dependency
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# Top-200 popular packages by ecosystem
# ============================================================================

POPULAR_PYTHON_PACKAGES: set[str] = {
    # Web frameworks
    "django",
    "flask",
    "fastapi",
    "tornado",
    "bottle",
    "pyramid",
    "starlette",
    "sanic",
    "falcon",
    "quart",
    "aiohttp",
    "uvicorn",
    "gunicorn",
    "hypercorn",
    # Data science / ML
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "scikit-learn",
    "sklearn",
    "tensorflow",
    "torch",
    "keras",
    "xgboost",
    "lightgbm",
    "catboost",
    "seaborn",
    "plotly",
    "bokeh",
    "statsmodels",
    "nltk",
    "spacy",
    "transformers",
    "datasets",
    "tokenizers",
    "accelerate",
    "diffusers",
    "opencv-python",
    "pillow",
    "imageio",
    # HTTP / Networking
    "requests",
    "httpx",
    "urllib3",
    "httplib2",
    "httpcore",
    "websockets",
    "grpcio",
    "paramiko",
    # Database
    "sqlalchemy",
    "psycopg2",
    "pymongo",
    "redis",
    "celery",
    "alembic",
    "pymysql",
    "asyncpg",
    "motor",
    "peewee",
    "tortoise-orm",
    "databases",
    # Cloud / DevOps
    "boto3",
    "botocore",
    "google-cloud-storage",
    "azure-storage-blob",
    "docker",
    "kubernetes",
    "ansible",
    "fabric",
    # CLI / Utils
    "click",
    "typer",
    "rich",
    "tqdm",
    "colorama",
    "pyyaml",
    "toml",
    "python-dotenv",
    "pydantic",
    "attrs",
    "dataclasses-json",
    "marshmallow",
    "cerberus",
    # Testing
    "pytest",
    "unittest2",
    "coverage",
    "tox",
    "nox",
    "hypothesis",
    "factory-boy",
    "faker",
    "responses",
    "httpretty",
    "vcrpy",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-mock",
    # Security / Crypto
    "cryptography",
    "pyjwt",
    "bcrypt",
    "passlib",
    "certifi",
    "pyopenssl",
    # Serialization / Parsing
    "lxml",
    "beautifulsoup4",
    "html5lib",
    "feedparser",
    "xmltodict",
    "orjson",
    "ujson",
    "msgpack",
    "protobuf",
    # Async
    "asyncio",
    "trio",
    "anyio",
    "twisted",
    # Linting / Formatting
    "black",
    "ruff",
    "flake8",
    "pylint",
    "mypy",
    "isort",
    "autopep8",
    "bandit",
    "pyright",
    # Misc popular
    "jinja2",
    "markupsafe",
    "werkzeug",
    "itsdangerous",
    "six",
    "setuptools",
    "pip",
    "wheel",
    "twine",
    "build",
    "packaging",
    "importlib-metadata",
    "typing-extensions",
    "python-dateutil",
    "arrow",
    "pendulum",
    "pytz",
    "chardet",
    "charset-normalizer",
    "idna",
    "filelock",
    "watchdog",
    "schedule",
    "apscheduler",
}

POPULAR_JS_PACKAGES: set[str] = {
    # Frameworks
    "react",
    "vue",
    "angular",
    "svelte",
    "next",
    "nuxt",
    "gatsby",
    "remix",
    "astro",
    "solid-js",
    "preact",
    "lit",
    # Runtime / Build
    "typescript",
    "webpack",
    "vite",
    "esbuild",
    "rollup",
    "parcel",
    "babel",
    "swc",
    "turbo",
    "nx",
    # Server
    "express",
    "fastify",
    "koa",
    "hapi",
    "nestjs",
    "hono",
    # State management
    "redux",
    "mobx",
    "zustand",
    "jotai",
    "recoil",
    "pinia",
    "vuex",
    # Testing
    "jest",
    "mocha",
    "chai",
    "vitest",
    "cypress",
    "playwright",
    "puppeteer",
    "testing-library",
    "sinon",
    "nyc",
    # HTTP / Networking
    "axios",
    "node-fetch",
    "got",
    "superagent",
    "undici",
    "socket.io",
    "ws",
    # Database / ORM
    "mongoose",
    "sequelize",
    "knex",
    "prisma",
    "typeorm",
    "drizzle-orm",
    "pg",
    "mysql2",
    "redis",
    "ioredis",
    # UI Libraries
    "tailwindcss",
    "bootstrap",
    "material-ui",
    "antd",
    "chakra-ui",
    "styled-components",
    "emotion",
    # Utils
    "lodash",
    "underscore",
    "ramda",
    "date-fns",
    "moment",
    "dayjs",
    "uuid",
    "nanoid",
    "chalk",
    "debug",
    "dotenv",
    "commander",
    "yargs",
    "inquirer",
    "ora",
    "glob",
    "fs-extra",
    "rimraf",
    "mkdirp",
    "cross-env",
    "semver",
    "minimist",
    "yaml",
    # Validation / Schema
    "zod",
    "yup",
    "joi",
    "ajv",
    "class-validator",
    # Auth
    "jsonwebtoken",
    "passport",
    "bcrypt",
    "argon2",
    # Linting / Formatting
    "eslint",
    "prettier",
    "stylelint",
    # Misc popular
    "rxjs",
    "graphql",
    "apollo-server",
    "cors",
    "body-parser",
    "cookie-parser",
    "multer",
    "morgan",
    "helmet",
    "compression",
    "serve-static",
    "concurrently",
    "nodemon",
    "pm2",
    "ts-node",
    "tsup",
    "tsconfig-paths",
}


def _levenshtein_distance(s1: str, s2: str) -> int:
    """
    Compute the Levenshtein (edit) distance between two strings.

    Uses the classic dynamic programming approach with O(min(m,n)) space.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Integer edit distance.
    """
    if s1 == s2:
        return 0

    len1, len2 = len(s1), len(s2)

    # Optimize: make s1 the shorter string for space efficiency
    if len1 > len2:
        s1, s2 = s2, s1
        len1, len2 = len2, len1

    # Single-row DP approach
    previous_row = list(range(len1 + 1))

    for j in range(1, len2 + 1):
        current_row = [j] + [0] * len1
        for i in range(1, len1 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            current_row[i] = min(
                current_row[i - 1] + 1,  # insertion
                previous_row[i] + 1,  # deletion
                previous_row[i - 1] + cost,  # substitution
            )
        previous_row = current_row

    return previous_row[len1]


def _normalize_package_name(name: str) -> str:
    """
    Normalize a package name for comparison.

    Handles common variations:
    - Lowercase
    - Replace underscores with hyphens (Python convention)
    - Strip @scope/ prefix for scoped npm packages

    Args:
        name: Raw package name.

    Returns:
        Normalized package name string.
    """
    normalized = name.lower().strip()
    # Strip npm scope prefix (e.g. @types/node -> node)
    if normalized.startswith("@") and "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    # Python: underscores and hyphens are interchangeable
    normalized = normalized.replace("_", "-")
    return normalized


def _get_ecosystem_packages(build_system: BuildSystem) -> set[str]:
    """
    Return the popular packages set for the given build system.

    Args:
        build_system: The detected build system.

    Returns:
        Set of popular package names for the ecosystem.
    """
    python_systems = {BuildSystem.PIP, BuildSystem.POETRY, BuildSystem.PIPENV, BuildSystem.CONDA}
    js_systems = {BuildSystem.NPM, BuildSystem.YARN, BuildSystem.PNPM}

    if build_system in python_systems:
        return POPULAR_PYTHON_PACKAGES
    elif build_system in js_systems:
        return POPULAR_JS_PACKAGES
    else:
        # Unknown ecosystem: check against both sets
        return POPULAR_PYTHON_PACKAGES | POPULAR_JS_PACKAGES


def _is_common_prefix_suffix_swap(dep_name: str, popular_name: str) -> bool:
    """
    Check for common typosquatting patterns beyond edit distance:
    - python-<name> vs <name>
    - <name>-python vs <name>
    - <name>2 vs <name>
    - <name>-js vs <name>

    Args:
        dep_name: The dependency package name (normalized).
        popular_name: The popular package name (normalized).

    Returns:
        True if the dependency looks like a prefix/suffix variant of the popular package.
    """
    prefixes = ["python-", "py-", "node-", "js-"]
    suffixes = ["-python", "-py", "-node", "-js", "-dev", "2", "3"]

    for prefix in prefixes:
        if dep_name == prefix + popular_name:
            return True
        if popular_name == prefix + dep_name:
            return True

    for suffix in suffixes:
        if dep_name == popular_name + suffix:
            return True
        if popular_name == dep_name + suffix:
            return True

    return False


# ============================================================================
# Public API
# ============================================================================


class TyposquatFinding:
    """A single typosquatting/slopsquatting finding."""

    def __init__(
        self,
        dependency_name: str,
        similar_to: str,
        distance: int,
        reason: str,
        severity: str = "high",
    ) -> None:
        self.dependency_name = dependency_name
        self.similar_to = similar_to
        self.distance = distance
        self.reason = reason
        self.severity = severity

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "dependency": self.dependency_name,
            "similarTo": self.similar_to,
            "distance": self.distance,
            "reason": self.reason,
            "severity": self.severity,
        }


def check_typosquatting(
    dependencies: list[Dependency],
    build_system: BuildSystem,
    max_distance: int = 2,
) -> list[TyposquatFinding]:
    """
    Check a list of dependencies for potential typosquatting.

    For each dependency, compute Levenshtein distance against the popular
    packages list for the given ecosystem. Flag any package that is within
    ``max_distance`` edits of a popular package but is NOT the popular package
    itself.

    Args:
        dependencies: List of project dependencies.
        build_system: Detected build system (determines ecosystem).
        max_distance: Maximum Levenshtein distance to flag (default 2).

    Returns:
        List of TyposquatFinding objects for flagged packages.
    """
    popular_packages = _get_ecosystem_packages(build_system)
    # Pre-normalize popular names for comparison
    popular_normalized: dict[str, str] = {_normalize_package_name(pkg): pkg for pkg in popular_packages}

    findings: list[TyposquatFinding] = []

    for dep in dependencies:
        dep_normalized = _normalize_package_name(dep.name)

        # Skip if the dependency IS the popular package
        if dep_normalized in popular_normalized:
            continue

        # Check Levenshtein distance against each popular package
        for pop_norm, pop_original in popular_normalized.items():
            # Quick length filter: if names differ by more than max_distance in
            # length, edit distance is guaranteed > max_distance.
            if abs(len(dep_normalized) - len(pop_norm)) > max_distance:
                continue

            distance = _levenshtein_distance(dep_normalized, pop_norm)

            if distance <= max_distance:
                severity = "critical" if distance == 1 else "high"
                findings.append(
                    TyposquatFinding(
                        dependency_name=dep.name,
                        similar_to=pop_original,
                        distance=distance,
                        reason=(
                            f"Package '{dep.name}' is {distance} edit(s) away from "
                            f"popular package '{pop_original}'. This could be a "
                            f"typosquatting / slopsquatting attempt."
                        ),
                        severity=severity,
                    )
                )
                # Report only the closest match per dependency
                break

        # Also check prefix/suffix manipulation patterns
        else:
            # Only runs if the inner loop did NOT break (no close match found)
            for pop_norm, pop_original in popular_normalized.items():
                if _is_common_prefix_suffix_swap(dep_normalized, pop_norm):
                    findings.append(
                        TyposquatFinding(
                            dependency_name=dep.name,
                            similar_to=pop_original,
                            distance=-1,  # Not a simple edit distance
                            reason=(
                                f"Package '{dep.name}' looks like a prefix/suffix "
                                f"variant of popular package '{pop_original}'. "
                                f"Verify this is the intended package."
                            ),
                            severity="medium",
                        )
                    )
                    break

    logger.info(
        "typosquatting_check_complete",
        total_deps=len(dependencies),
        flagged=len(findings),
    )

    return findings


def run_supply_chain_check(
    build_context: BuildContext,
    max_distance: int = 2,
) -> dict[str, Any]:
    """
    Run the full supply chain typosquatting check on a build context.

    This is the top-level entry point used by the SecurityFrame or CLI.

    Args:
        build_context: Parsed build context with dependencies.
        max_distance: Maximum Levenshtein distance to flag.

    Returns:
        Dictionary with check results:
        {
            "passed": bool,
            "findings": list[dict],
            "total_checked": int,
            "flagged": int,
            "ecosystem": str,
        }
    """
    all_deps = build_context.get_all_dependencies()

    if not all_deps:
        logger.info("supply_chain_check_skipped", reason="no_dependencies")
        return {
            "passed": True,
            "findings": [],
            "total_checked": 0,
            "flagged": 0,
            "ecosystem": build_context.build_system.name,
        }

    findings = check_typosquatting(
        dependencies=all_deps,
        build_system=build_context.build_system,
        max_distance=max_distance,
    )

    return {
        "passed": len(findings) == 0,
        "findings": [f.to_dict() for f in findings],
        "total_checked": len(all_deps),
        "flagged": len(findings),
        "ecosystem": build_context.build_system.name,
    }
