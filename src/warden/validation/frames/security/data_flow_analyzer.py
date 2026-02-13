"""
Data Flow Analyzer Module

LSP-based data flow analysis for taint tracking.
"""

import asyncio
from typing import Any

try:
    from warden.shared.infrastructure.logging import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


async def analyze_data_flow(code_file: Any, findings: list[Any]) -> dict[str, Any]:
    """
    Analyze data flow using LSP for taint tracking.

    For each finding:
    - Track callers (who uses the vulnerable code - blast radius)
    - Track callees (where does untrusted data come from - data sources)

    Returns:
        Dict with data flow context for each finding
    """
    data_flow_context: dict[str, Any] = {"tainted_paths": [], "blast_radius": [], "data_sources": []}

    try:
        from warden.lsp import get_semantic_analyzer

        analyzer = get_semantic_analyzer()
    except ImportError:
        logger.debug("lsp_not_available_for_data_flow")
        return data_flow_context
    except Exception as e:
        logger.debug("lsp_init_failed", error=str(e))
        return data_flow_context

    # Extract function names and lines from findings
    sensitive_locations = _extract_sensitive_locations(code_file, findings)

    for location in sensitive_locations[:5]:  # Limit to 5 locations
        try:
            # Get callers (blast radius - who uses this vulnerable code)
            callers = await asyncio.wait_for(
                analyzer.get_callers_async(
                    code_file.path, location["line"], location.get("column", 0), content=code_file.content
                ),
                timeout=5.0,
            )
            if callers:
                data_flow_context["blast_radius"].extend(
                    [
                        {
                            "vulnerable_at": f"{code_file.path}:{location['line']}",
                            "called_from": c.name,
                            "caller_file": c.location,
                            "finding_type": location.get("type", "unknown"),
                        }
                        for c in callers[:3]
                    ]
                )

            # Get callees (data sources - where does data come from)
            callees = await asyncio.wait_for(
                analyzer.get_callees_async(
                    code_file.path, location["line"], location.get("column", 0), content=code_file.content
                ),
                timeout=5.0,
            )
            if callees:
                data_flow_context["data_sources"].extend(
                    [
                        {
                            "vulnerable_at": f"{code_file.path}:{location['line']}",
                            "data_from": c.name,
                            "source_file": c.location,
                            "finding_type": location.get("type", "unknown"),
                        }
                        for c in callees[:3]
                    ]
                )

        except asyncio.TimeoutError:
            logger.debug("lsp_data_flow_timeout", location=location)
        except Exception as e:
            logger.debug("lsp_data_flow_error", location=location, error=str(e))

    # Identify tainted paths (data flow from untrusted source to sink)
    if data_flow_context["data_sources"]:
        for source in data_flow_context["data_sources"]:
            # Check if source is from untrusted origin (request, user input, etc.)
            source_name = source.get("data_from", "").lower()
            if any(
                keyword in source_name
                for keyword in [
                    "request",
                    "input",
                    "param",
                    "query",
                    "body",
                    "form",
                    "user",
                    "args",
                    "kwargs",
                    "data",
                    "payload",
                ]
            ):
                data_flow_context["tainted_paths"].append(
                    {
                        "source": source["data_from"],
                        "sink": source["vulnerable_at"],
                        "risk": "high" if "sql" in source.get("finding_type", "").lower() else "medium",
                    }
                )

    logger.debug(
        "data_flow_analysis_complete",
        blast_radius=len(data_flow_context["blast_radius"]),
        data_sources=len(data_flow_context["data_sources"]),
        tainted_paths=len(data_flow_context["tainted_paths"]),
    )

    return data_flow_context


def _extract_sensitive_locations(code_file: Any, check_results: list[Any]) -> list[dict[str, Any]]:
    """Extract line numbers and types from check findings for LSP analysis."""
    locations = []

    for result in check_results:
        for finding in result.findings:
            # Parse location string (format: "path:line" or "path:line:col")
            loc_str = finding.location
            if ":" in loc_str:
                parts = loc_str.split(":")
                try:
                    line = int(parts[-1]) if len(parts) >= 2 else 1
                    column = int(parts[-1]) if len(parts) >= 3 else 0
                    locations.append(
                        {"line": line, "column": column, "type": finding.check_id, "message": finding.message}
                    )
                except ValueError:
                    continue

    return locations


def format_data_flow_context(data_flow: dict[str, Any]) -> str:
    """Format data flow context for LLM prompt."""
    lines = []

    if data_flow.get("tainted_paths"):
        lines.append("[Tainted Data Paths (HIGH RISK)]:")
        for path in data_flow["tainted_paths"][:3]:
            lines.append(f"  - {path['source']} -> {path['sink']} (risk: {path['risk']})")

    if data_flow.get("blast_radius"):
        lines.append("\n[Blast Radius - Code affected by vulnerabilities]:")
        for br in data_flow["blast_radius"][:3]:
            lines.append(f"  - {br['called_from']} in {br['caller_file']}")

    if data_flow.get("data_sources"):
        lines.append("\n[Data Sources - Where vulnerable data originates]:")
        for ds in data_flow["data_sources"][:3]:
            lines.append(f"  - {ds['data_from']} from {ds['source_file']}")

    return "\n".join(lines) if lines else ""
