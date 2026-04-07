"""
Safe subprocess/command patterns that command-injection scanners wrongly flag.

corpus_labels:
  command-injection: 0
  sql-injection: 0
"""

import subprocess
from pathlib import Path


# ── subprocess.run with list form — safe, no shell expansion ─────────────────

def convert_image(input_path: Path, output_path: Path) -> None:
    """subprocess list form — NOT command injection (no shell=True)."""
    subprocess.run(
        ["convert", str(input_path), str(output_path)],
        check=True,
    )


def ping_host(host: str) -> subprocess.CompletedProcess:
    """subprocess list form with validated input — NOT command injection."""
    # host is validated by caller (DNS name or IP only)
    return subprocess.run(
        ["ping", "-c", "1", "-W", "2", host],
        capture_output=True,
        text=True,
        timeout=5,
    )


def run_linter(filepath: Path) -> str:
    """subprocess with list — NOT command injection."""
    result = subprocess.run(
        ["ruff", "check", str(filepath), "--format", "json"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def check_output_safe(path: Path) -> bytes:
    """subprocess.check_output with list — NOT command injection."""
    return subprocess.check_output(["sha256sum", str(path)])


# ── Hardcoded commands — no user input ───────────────────────────────────────

def get_git_hash() -> str:
    """No user input, hardcoded args — NOT command injection."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_system_info() -> dict:
    """No user input, fixed commands — NOT command injection."""
    uname = subprocess.run(["uname", "-s"], capture_output=True, text=True)
    arch = subprocess.run(["uname", "-m"], capture_output=True, text=True)
    return {"os": uname.stdout.strip(), "arch": arch.stdout.strip()}


# ── Comment lines mentioning shell commands — NOT command injection ───────────

# BAD: os.system(f"ping {host}")  ← command injection via f-string + shell
# BAD: subprocess.run(f"convert {file}", shell=True)  ← shell=True is dangerous
# GOOD: subprocess.run(["convert", file])  ← list form, no shell expansion

# DANGEROUS_PATTERNS definition — NOT actual command injection usage

DANGEROUS_PATTERNS = [
    (r"os\.system\s*\(", "os.system() command injection"),
    (r"subprocess\.(run|call)\s*\(.*shell\s*=\s*True", "subprocess shell=True"),
]
