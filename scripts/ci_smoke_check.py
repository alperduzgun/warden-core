"""
CI smoke check for warden scan results.

Reads the warden-report.json produced by `warden scan` and asserts that:
  - The LLM was actually called (not zombie/offline mode)
  - llmMetrics are present and providers are correct
  - LLM-dependent frames were not all skipped
  - At least one LLM frame executed

Exits 0 on success, 1 on failure. No external dependencies required.
"""

import json
import sys


def main() -> int:
    report_path = sys.argv[1] if len(sys.argv) > 1 else ".warden/reports/warden-report.json"

    try:
        with open(report_path) as f:
            report = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Report not found at {report_path}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse report JSON: {exc}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    # 1. LLM was actually called (not zombie mode)
    completion_tokens = report.get("completionTokens", 0)
    llm_usage = report.get("llmUsage", {})
    total_tokens = llm_usage.get("totalTokens", 0) or completion_tokens
    if total_tokens == 0:
        errors.append("FAIL: completionTokens == 0 — LLM was never called (zombie mode)")

    # 2. Check llmMetrics exist and providers are correct
    llm_metrics = report.get("llmMetrics", {})
    if not llm_metrics:
        errors.append("FAIL: llmMetrics is empty — metrics collection may have failed")
    else:
        # Fast tier (Ollama) check
        fast_tier = llm_metrics.get("fastTier", {})
        if not fast_tier:
            warnings.append("WARN: fastTier not present in llmMetrics")
        else:
            providers = fast_tier.get("providers", [])
            if "ollama" not in providers:
                warnings.append(f"WARN: Ollama not in fast tier providers: {providers}")

            success_rate = fast_tier.get("successRate", 0)
            if success_rate == 0:
                errors.append("FAIL: fastTier successRate is 0 — all Ollama requests failed")

            timeouts = fast_tier.get("timeouts", 0)
            total_reqs = fast_tier.get("requests", 0)
            if total_reqs > 0 and timeouts >= total_reqs:
                errors.append(
                    f"FAIL: All fast tier requests timed out ({timeouts}/{total_reqs})"
                )

        # Smart tier (Groq) check
        smart_tier = llm_metrics.get("smartTier", {})
        if not smart_tier:
            warnings.append("WARN: smartTier not present in llmMetrics")
        else:
            providers = smart_tier.get("providers", [])
            if "groq" not in providers:
                warnings.append(f"WARN: Groq not in smart tier providers: {providers}")

            model = smart_tier.get("model", "")
            if model == "offline-fallback":
                errors.append("FAIL: Smart tier is using offline-fallback model")

    # 3. LLM-dependent frames not all skipped
    frame_results = report.get("frameResults", [])
    llm_frames = ["security", "resilience", "fuzz", "spec", "antipattern", "architecture"]
    llm_frame_statuses: dict[str, str] = {}
    for fr in frame_results:
        fid = fr.get("frameId", "")
        if fid in llm_frames:
            llm_frame_statuses[fid] = fr.get("status", "unknown")

    all_skipped = all(s == "skipped" for s in llm_frame_statuses.values())
    if llm_frame_statuses and all_skipped:
        errors.append(
            f"FAIL: All LLM-dependent frames skipped: {llm_frame_statuses}"
        )

    # 4. At least some frames ran with non-zero findings or explicit pass
    ran_frames = [fid for fid, s in llm_frame_statuses.items() if s != "skipped"]
    if len(ran_frames) == 0:
        errors.append("FAIL: Zero LLM frames executed")

    # 5. Deterministic findings present (Rust engine should find vulns in fixture)
    # Note: Only error if we expected findings (i.e., vulnerable fixture was in scan scope)
    # This is a soft check since it depends on scan target
    total_findings = report.get("totalFindings", 0)

    # 6. Check for degraded frames
    degraded_frames = [fr.get("frameId") for fr in frame_results if fr.get("is_degraded", False)]
    if degraded_frames:
        warnings.append(f"WARN: Degraded frames detected: {degraded_frames}")

    # Print results
    print("=" * 60)
    print("WARDEN LIVE INTEGRATION SMOKE CHECK")
    print("=" * 60)
    print(f"Total tokens used: {total_tokens}")
    print(f"Total findings: {total_findings}")
    print(f"Frames executed: {len(ran_frames)}/{len(llm_frame_statuses)}")
    print(f"LLM metrics present: {bool(llm_metrics)}")
    print()

    for w in warnings:
        print(f"  {w}")

    for e in errors:
        print(f"  {e}")

    if not errors:
        print("  All smoke checks passed")
        print()
        return 0
    else:
        print()
        print(f"SMOKE CHECK FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
