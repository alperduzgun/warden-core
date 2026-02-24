"""Benchmark data collection — tracks phase durations and LLM call attribution.

No pipeline changes required: wraps the existing event stream by observing
``phase_started`` and ``frame_completed`` progress events.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4


@dataclass
class PhaseEntry:
    name: str
    duration_s: float = 0.0
    llm_calls: int = 0


@dataclass
class FrameEntry:
    frame_id: str
    frame_name: str
    phase: str
    duration_s: float
    findings: int
    status: str
    llm_calls: int = 0
    llm_duration_ms: float = 0.0


@dataclass
class BenchmarkReport:
    scan_id: str
    timestamp: str
    provider: str
    model: str
    files_scanned: int
    total_bytes: int
    total_duration_s: float
    phases: list[PhaseEntry]
    frames: list[FrameEntry]
    llm_calls_total: int
    llm_duration_total_ms: float
    findings_total: int

    @property
    def llm_overhead_pct(self) -> float:
        if self.total_duration_s <= 0:
            return 0.0
        return (self.llm_duration_total_ms / 1000) / self.total_duration_s * 100

    def to_dict(self) -> dict:
        return {
            "scan_id": self.scan_id,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "files_scanned": self.files_scanned,
            "total_bytes": self.total_bytes,
            "total_duration_s": round(self.total_duration_s, 3),
            "phases": [
                {"name": p.name, "duration_s": round(p.duration_s, 3), "llm_calls": p.llm_calls} for p in self.phases
            ],
            "frames": [
                {
                    "frame_id": f.frame_id,
                    "frame_name": f.frame_name,
                    "phase": f.phase,
                    "duration_s": round(f.duration_s, 3),
                    "findings": f.findings,
                    "status": f.status,
                    "llm_calls": f.llm_calls,
                    "llm_duration_ms": round(f.llm_duration_ms, 1),
                }
                for f in self.frames
            ],
            "llm_calls_total": self.llm_calls_total,
            "llm_duration_total_ms": round(self.llm_duration_total_ms, 1),
            "findings_total": self.findings_total,
            "llm_overhead_pct": round(self.llm_overhead_pct, 1),
        }


class BenchmarkCollector:
    """Collects benchmark data from pipeline events without modifying the pipeline.

    Usage in scan.py::

        collector = BenchmarkCollector()
        # … inside the event loop …
        if evt in ("phase_started", "frame_completed"):
            collector.on_event(evt, data)
        # … after the loop …
        report = collector.finalize(bridge, files_scanned=total_units)
    """

    def __init__(self) -> None:
        self._scan_start = time.perf_counter()
        self._phase_start: float | None = None
        self._current_phase: str | None = None
        self._phases: list[PhaseEntry] = []
        self._frames: list[FrameEntry] = []

    def on_event(self, event: str, data: dict) -> None:
        """Process a pipeline progress event."""
        if event == "phase_started":
            self._close_current_phase()
            phase = data.get("phase_name", data.get("phase", "unknown"))
            self._current_phase = str(phase)
            self._phase_start = time.perf_counter()
        elif event == "frame_completed":
            self._frames.append(
                FrameEntry(
                    frame_id=data.get("frame_id", ""),
                    frame_name=data.get("frame_name", data.get("frame_id", "")),
                    phase=self._current_phase or "unknown",
                    duration_s=float(data.get("duration", 0.0)),
                    findings=int(data.get("findings", 0)),
                    status=str(data.get("status", "")),
                )
            )

    def _close_current_phase(self) -> None:
        """Finalise timing for the current phase."""
        if self._current_phase is not None and self._phase_start is not None:
            elapsed = time.perf_counter() - self._phase_start
            self._phases.append(PhaseEntry(name=self._current_phase, duration_s=elapsed))
        self._current_phase = None
        self._phase_start = None

    def finalize(self, bridge: object | None = None, files_scanned: int = 0) -> BenchmarkReport:
        """Build the final report, enriching frames with LLM attribution data."""
        self._close_current_phase()
        total_s = time.perf_counter() - self._scan_start

        # Enrich frames with per-frame LLM metrics.
        # FrameMetrics.frame_name == frame.frame_id (set via frame_scope(frame.frame_id))
        from warden.llm.metrics import get_global_metrics_collector

        metrics = get_global_metrics_collector()
        frame_metrics = {fm.frame_name: fm for fm in metrics.get_frame_metrics()}

        for f in self._frames:
            fm = frame_metrics.get(f.frame_id)
            if fm:
                f.llm_calls = fm.llm_calls
                f.llm_duration_ms = float(fm.total_duration_ms)

        # Attribute LLM calls to phases that have frames.
        for p in self._phases:
            phase_frames = [f for f in self._frames if f.phase == p.name]
            if phase_frames:
                p.llm_calls = sum(f.llm_calls for f in phase_frames)

        # Global LLM totals.
        all_requests = list(metrics.requests)
        llm_calls_total = len(all_requests)
        llm_duration_total_ms = float(sum(r.duration_ms for r in all_requests))

        provider, model = self._resolve_provider_model(all_requests, bridge)

        return BenchmarkReport(
            scan_id=str(uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            provider=provider,
            model=model,
            files_scanned=files_scanned,
            total_bytes=0,
            total_duration_s=total_s,
            phases=self._phases,
            frames=self._frames,
            llm_calls_total=llm_calls_total,
            llm_duration_total_ms=llm_duration_total_ms,
            findings_total=sum(f.findings for f in self._frames),
        )

    @staticmethod
    def _resolve_provider_model(requests: list, bridge: object | None) -> tuple[str, str]:
        """Return (provider, model) from available context."""
        if requests:
            last = requests[-1]
            return getattr(last, "provider", "unknown"), getattr(last, "model", "unknown")

        if bridge is not None:
            try:
                llm_cfg = getattr(bridge, "llm_config", None)
                if llm_cfg:
                    provider = str(getattr(llm_cfg, "default_provider", "unknown"))
                    fast = getattr(llm_cfg, "fast_model", None)
                    smart = getattr(llm_cfg, "smart_model", None)
                    model = str(fast or smart or "unknown")
                    return provider, model
            except Exception:
                pass

        return "unknown", "unknown"
