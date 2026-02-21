"""
UX constants for the ``warden scan`` live display.

Keeping these out of scan.py prevents data from bloating the command logic.
"""

# ASCII art shield — traced from warden-logo.svg (viewBox 0 0 648 725).
# Outer body: double-line box (heraldic shield proportions).
# Inner panel: single-line panel with the name.
# Bottom: stair-step taper to a downward point.
LOGO_LINES: list[str] = [
    "  ╔══════════════════════════╗  ",
    "  ║ ╭────────────────────╮  ║  ",
    "  ║ │                    │  ║  ",
    "  ║ │    W A R D E N     │  ║  ",
    "  ║ │                    │  ║  ",
    "  ║ ╰────────────────────╯  ║  ",
    "  ╚═╗                    ╔═╝  ",
    "    ╚═╗                ╔═╝    ",
    "      ╚═╗            ╔═╝      ",
    "        ╚═╗        ╔═╝        ",
    "          ╚═╗    ╔═╝          ",
    "            ╚════╝            ",
]

# Rotate every 14 s during a scan.
TIPS: list[str] = [
    "Never store secrets in source code — use environment variables or a vault.",
    "SQL injection is still the #1 cause of data breaches. Parameterise everything.",
    "A dependency update that takes 5 min can prevent a 0-day that costs weeks.",
    "The most dangerous code is the code you think you understand.",
    "Shift left: catching a bug in review costs 6x less than catching it in production.",
    "Input validation is not sanitisation. You need both, in that order.",
    "SSRF lets attackers reach internal services through your own server. Whitelist URLs.",
    "73% of web app breaches involve custom code, not frameworks or libraries.",
    "Least privilege is the closest thing to a security silver bullet that exists.",
    "Rotate secrets after every team member departure. Without exception.",
    "Rate limiting is not optional — it turns brute-force from inevitable to impractical.",
    "Timing attacks are real. Use constant-time comparison for secrets.",
    "Log what happened, not what you expected to happen.",
    "Security reviews without threat modeling are just style guides.",
    "An unhandled exception leaking a stack trace is a free recon gift to attackers.",
    "Always hash passwords with a slow algorithm (bcrypt/argon2). Speed is the enemy here.",
    "A misconfigured CORS policy is an open door, not a locked window.",
    "Supply-chain attacks increased 742% in 2023. Know what you're importing.",
    "Security is not a feature. It is the absence of bugs that matter most.",
    "The best time to fix a vulnerability was before you shipped it. The second best is now.",
]

# One is chosen at random after the scan finishes.
QUOTES: list[tuple[str, str]] = [
    ("Security is a process, not a product.", "Bruce Schneier"),
    ("The only system which is truly secure is one which is switched off.", "Gene Spafford"),
    (
        "There are only two types of companies:\n"
        "those that have been hacked, and those that don't know yet.",
        "John Chambers",
    ),
    ("Make it work, make it right, make it fast — in that order.", "Kent Beck"),
    ("Complexity is the worst enemy of security.", "Bruce Schneier"),
    (
        "Any fool can write code that a computer can understand.\n"
        "Good programmers write code that humans can understand.",
        "Martin Fowler",
    ),
    ("Warden has reviewed your code. The rest is up to you.", "Warden"),
    ("The goal of security is not to eliminate risk. It is to manage it.", "Warden"),
]

# Shown while a phase is loading (no frame rows yet).
PHASE_HINTS: dict[str, str] = {
    "Pre-Analysis":  "Building code graph, running tree-sitter parsing & context extraction",
    "Triage":        "Classifying files with AI to select optimal frames per file",
    "Validation":    "Running security, property and quality frames with LLM verification",
    "Verification":  "Cross-checking findings against baseline and filtering false positives",
    "Reporting":     "Generating SARIF, badge and structured reports",
    "Fortification": "Applying auto-fix patches and updating baseline",
    "Audit":         "Running audit context analysis: imports, dependencies, dead code",
}
