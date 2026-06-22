"""
Layer-A deterministic intent classifier (#690).

ZERO LLM cost.  Assigns a ``role`` to every symbol from three deterministic
signals — file path patterns, AST decorators and a naming lexicon — extracts a
one-line ``summary`` from the symbol's docstring head, and derives ``public_api``
from edge fan-in (centrality).  Results are written to the ``symbol_intent``
table with ``source = "deterministic"``.

Build-pass order (mandatory): extract → resolve → fan-in → classify.  Centrality
is read from the persisted/resolved edges, so :func:`populate_symbol_intent` must
run *after* the graph has been written through the GraphStore.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from warden.analysis.domain.code_graph import CodeGraph, SymbolIntent, SymbolKind, SymbolNode

if TYPE_CHECKING:
    from warden.analysis.domain.graph_store import GraphStore

logger = structlog.get_logger(__name__)

# A symbol with at least this many incoming edges is treated as public API.
PUBLIC_API_FANIN_THRESHOLD = 5

# ── decorator → role (most specific signal, checked first) ────────────
_DECORATOR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfield_validator\b|\bmodel_validator\b|\bvalidator\b"), "validator"),
    (re.compile(r"\.command\b|^command$|cli\.command|typer"), "cli_command"),
    (re.compile(r"\.(get|post|put|delete|patch|head|options)\b|\.route\b|router\.|api_route|websocket"), "api_endpoint"),
    (re.compile(r"\bfixture\b"), "test_fixture"),
    (re.compile(r"\bcached_property\b|\blru_cache\b|\bcache\b"), "cached"),
    (re.compile(r"\bproperty\b"), "property"),
    (re.compile(r"\babstractmethod\b"), "abstract_method"),
    (re.compile(r"\bstaticmethod\b"), "static_method"),
    (re.compile(r"\bclassmethod\b"), "class_method"),
    (re.compile(r"\bdataclass\b"), "data_model"),
    (re.compile(r"\btask\b|\bshared_task\b|\bcelery\b"), "task"),
    (re.compile(r"\bcontextmanager\b"), "context_manager"),
)

# ── path fragment → role (project-structure signal) ──────────────────
_PATH_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|/)migrations?/"), "migration"),
    (re.compile(r"(^|/)cli/|(^|/)commands?/"), "cli"),
    (re.compile(r"(^|/)(api|routes?|endpoints?|controllers?)/"), "api"),
    (re.compile(r"(^|/)models?/|(^|/)schemas?/|(^|/)models?\.py$|(^|/)schema\.py$"), "data_model"),
    (re.compile(r"(^|/)services?/|service\.py$"), "service"),
    (re.compile(r"(^|/)(config|settings)/|config\.py$|settings\.py$"), "config"),
    (re.compile(r"(^|/)validation/|(^|/)validators?/"), "validator"),
    (re.compile(r"(^|/)repositor(y|ies)/"), "repository"),
)

# ── class-name suffix → role ─────────────────────────────────────────
_CLASS_SUFFIX_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(Model|Schema|DTO|Entity)$"), "data_model"),
    (re.compile(r"(Error|Exception)$"), "exception"),
    (re.compile(r"Service$"), "service"),
    (re.compile(r"Factory$"), "factory"),
    (re.compile(r"Repository$"), "repository"),
    (re.compile(r"Manager$"), "manager"),
    (re.compile(r"Controller$"), "controller"),
    (re.compile(r"(Handler|Listener)$"), "handler"),
    (re.compile(r"Middleware$"), "middleware"),
    (re.compile(r"(Config|Settings)$"), "config"),
    (re.compile(r"(Mixin|Aware)$"), "mixin"),
    (re.compile(r"(Protocol|Interface|ABC|Abstract\w*)$"), "interface"),
)

# ── function/method name prefix → role (naming lexicon) ──────────────
_NAME_PREFIX_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^test_"), "test"),
    (re.compile(r"^(validate|check|verify|ensure|assert)_"), "validator"),
    (re.compile(r"^(get|fetch|load|read|list|find|lookup|query|select)_"), "accessor"),
    (re.compile(r"^(set|save|write|update|create|delete|remove|insert|add|put|store)_"), "mutator"),
    (re.compile(r"^(is|has|can|should|was|are|will)_"), "predicate"),
    (re.compile(r"^(to|from|parse|serialize|deserialize|encode|decode|convert|format|render)_"), "converter"),
    (re.compile(r"^(handle|on|process|dispatch)_"), "handler"),
    (re.compile(r"^(build|make|create|new|construct)_"), "factory_fn"),
    (re.compile(r"^_"), "internal"),
)

# Exact function names that are entry points regardless of file.
_ENTRYPOINT_NAMES = frozenset({"main", "run", "execute", "cli", "app"})

# Naming roles considered "non-public" even at high fan-in.
_PRIVATE_NAME_RE = re.compile(r"^_")


def _node_decorators(node: SymbolNode) -> list[str]:
    decs = node.metadata.get("decorators", []) if node.metadata else []
    # The python-native provider stores Call decorators as object reprs
    # ("<ast.Call object ...>"); drop those — accurate decorators come from the
    # stdlib-ast facts pass instead.
    return [d for d in decs if isinstance(d, str) and not d.startswith("<ast.")]


def classify_role(node: SymbolNode, decorators: list[str] | None = None) -> str:
    """Assign a deterministic role to a symbol.

    Precedence: decorators → class suffix/bases → path → naming lexicon →
    kind fallback.  The kind fallback guarantees every symbol receives a role.

    ``decorators`` overrides the symbol's own metadata when supplied (the build
    flow passes accurate stdlib-ast-unparsed decorators here).
    """
    decs = decorators if decorators is not None else _node_decorators(node)
    dec_blob = " ".join(decs)
    for pattern, role in _DECORATOR_RULES:
        if pattern.search(dec_blob):
            return role

    name = node.name or ""

    # Class-shaped symbols: bases + name suffix carry the strongest signal.
    if node.kind in (SymbolKind.CLASS, SymbolKind.MIXIN, SymbolKind.INTERFACE):
        bases_blob = " ".join(b for b in node.bases if isinstance(b, str))
        if re.search(r"\bBaseModel\b", bases_blob):
            return "data_model"
        if re.search(r"\bEnum\b|\bIntEnum\b|\bStrEnum\b", bases_blob):
            return "enum"
        if re.search(r"Exception\b|Error\b", bases_blob):
            return "exception"
        if re.search(r"\b(ABC|Protocol)\b", bases_blob):
            return "interface"
        for pattern, role in _CLASS_SUFFIX_RULES:
            if pattern.search(name):
                return role
        if node.kind == SymbolKind.MIXIN:
            return "mixin"
        if node.kind == SymbolKind.INTERFACE:
            return "interface"

    # Test files dominate function/method intent.
    if node.is_test and node.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
        return "test"

    # Function / method naming lexicon.
    if node.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
        if name.startswith("__") and name.endswith("__"):
            return "dunder"
        if name in _ENTRYPOINT_NAMES:
            return "entrypoint"
        for pattern, role in _NAME_PREFIX_RULES:
            if pattern.search(name):
                return role

    # Project-structure path signal (weaker than name, stronger than fallback).
    for pattern, role in _PATH_RULES:
        if pattern.search(node.file_path):
            # Don't relabel a class as a bare "cli"/"api" folder role.
            if node.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                return role

    # Kind fallback — always assigns something.
    return {
        SymbolKind.CLASS: "class",
        SymbolKind.FUNCTION: "function",
        SymbolKind.METHOD: "method",
        SymbolKind.MIXIN: "mixin",
        SymbolKind.INTERFACE: "interface",
        SymbolKind.MODULE: "module",
    }.get(node.kind, "symbol")


def _is_public_api(node: SymbolNode, centrality: int, role: str) -> bool:
    """High fan-in (or an inherently exposed role) marks a public-API symbol."""
    if role in ("cli_command", "api_endpoint"):
        return True
    if _PRIVATE_NAME_RE.match(node.name or ""):
        return False
    if node.is_test:
        return False
    return centrality >= PUBLIC_API_FANIN_THRESHOLD


def extract_symbol_facts(sources: dict[str, str], project_root: Path) -> dict[str, dict]:
    """Extract per-symbol ``{summary, decorators}`` facts via stdlib ``ast``.

    ``sources`` is keyed by absolute path.  FQNs are reconstructed in the same
    ``relpath::QualName`` form the CodeGraphBuilder uses, so the result can be
    looked up directly by ``SymbolNode.fqn``.  Decorators are unparsed
    accurately here (the python-native provider mangles ``Call`` decorators).
    """
    facts: dict[str, dict] = {}
    for abs_path, text in sources.items():
        try:
            rel = str(Path(abs_path).relative_to(project_root))
        except ValueError:
            rel = abs_path
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue

        _collect_facts(tree, "", rel, facts)
    return facts


def _collect_facts(node: ast.AST, prefix: str, rel: str, facts: dict[str, dict]) -> None:
    """Recursively record ``{summary, decorators}`` for defs/classes under *node*."""
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        qualname = f"{prefix}.{child.name}" if prefix else child.name
        entry: dict = {}
        doc = ast.get_docstring(child)
        if doc:
            head = doc.strip().splitlines()[0].strip()
            if head:
                entry["summary"] = head[:200]
        decs = [d for d in (_safe_unparse(d) for d in child.decorator_list) if d]
        if decs:
            entry["decorators"] = decs
        if entry:
            facts[f"{rel}::{qualname}"] = entry
        # Recurse one level for methods (Class.method); deeper nesting is
        # uncommon and the builder only models one level.
        if isinstance(child, ast.ClassDef):
            _collect_facts(child, qualname, rel, facts)


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node).strip()
    except Exception:
        return ""


def _symbol_centrality(node: SymbolNode, fan_in: dict[str, int], unique_names: set[str]) -> int:
    """Resolve a symbol's fan-in from the aggregate keyed by FQN + short name.

    FQN-keyed counts (resolved DEFINES edges) always apply.  Short-name counts
    (unresolved CALLS/INHERITS targets) are credited only when the name is unique
    in the graph, so a common method name (e.g. ``run``) does not inflate every
    symbol that shares it.
    """
    centrality = fan_in.get(node.fqn, 0)
    name = node.name or ""
    if name and name != node.fqn and name in unique_names:
        centrality += fan_in.get(name, 0)
    return centrality


def build_intents(
    graph: CodeGraph,
    fan_in: dict[str, int],
    facts: dict[str, dict] | None = None,
) -> list[SymbolIntent]:
    """Classify every symbol in ``graph`` into a deterministic SymbolIntent.

    ``facts`` is the ``{fqn: {summary, decorators}}`` map from
    :func:`extract_symbol_facts`; when present its decorators/summary override
    the (less reliable) provider metadata.
    """
    facts = facts or {}

    # Names that map to exactly one symbol — safe to attribute name-based fan-in.
    name_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        if node.name:
            name_counts[node.name] = name_counts.get(node.name, 0) + 1
    unique_names = {n for n, c in name_counts.items() if c == 1}

    intents: list[SymbolIntent] = []
    for fqn, node in graph.nodes.items():
        fact = facts.get(fqn, {})
        decorators = fact.get("decorators")
        role = classify_role(node, decorators=decorators)
        centrality = _symbol_centrality(node, fan_in, unique_names)
        intents.append(
            SymbolIntent(
                fqn=fqn,
                role=role,
                summary=fact.get("summary", ""),
                centrality=centrality,
                public_api=_is_public_api(node, centrality, role),
                source="deterministic",
                confidence=1.0,
            )
        )
    return intents


def populate_symbol_intent(
    graph: CodeGraph,
    store: GraphStore,
    *,
    project_root: Path | None = None,
    sources: dict[str, str] | None = None,
) -> list[SymbolIntent]:
    """Run the fan-in → classify passes and write intents through the store.

    Must be called AFTER the graph has been persisted (resolve pass) so that
    :meth:`GraphStore.compute_fan_in` reflects resolved edges.

    Returns the intents written (for logging / acceptance metrics).
    """
    fan_in = store.compute_fan_in()
    facts: dict[str, dict] = {}
    if sources:
        facts = extract_symbol_facts(sources, project_root or Path.cwd())

    intents = build_intents(graph, fan_in, facts)
    store.upsert_intents(intents)

    public_api = sum(1 for i in intents if i.public_api)
    logger.info(
        "symbol_intent_populated",
        symbols=len(intents),
        public_api=public_api,
        with_summary=sum(1 for i in intents if i.summary),
        source="deterministic",
    )
    return intents
