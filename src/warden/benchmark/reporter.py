"""Benchmark report display (Rich terminal) and persistence (.warden/benchmarks/)."""

import json
from datetime import datetime
from pathlib import Path

from rich.box import SIMPLE_HEAVY
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .collector import BenchmarkReport, FrameEntry, PhaseEntry

_MAX_BENCHMARKS = 10


class BenchmarkReporter:
    @staticmethod
    def display(
        report: BenchmarkReport,
        console: Console | None = None,
        prev: BenchmarkReport | None = None,
    ) -> None:
        """Print a benchmark table to the console."""
        if console is None:
            console = Console()

        table = Table(
            box=SIMPLE_HEAVY,
            show_header=True,
            header_style="bold dim",
            title=(
                f"Scan Benchmark · "
                f"{report.files_scanned} file{'s' if report.files_scanned != 1 else ''}"
                f" · {report.provider} / {report.model}"
            ),
            title_style="bold",
        )
        table.add_column("Phase / Frame", style="", no_wrap=True, min_width=26)
        table.add_column("Duration", justify="right", style="cyan", min_width=10)
        table.add_column("LLM Calls", justify="right", style="dim", min_width=12)

        # Group frames by phase for indented display.
        frames_by_phase: dict[str, list[FrameEntry]] = {}
        for f in report.frames:
            frames_by_phase.setdefault(f.phase, []).append(f)

        for p in report.phases:
            phase_frames = frames_by_phase.get(p.name, [])
            call_str = f"{p.llm_calls} call{'s' if p.llm_calls != 1 else ''}" if p.llm_calls else "—"
            table.add_row(
                Text(p.name.upper(), style="bold white"),
                f"{p.duration_s:.1f}s",
                call_str,
            )

            for idx, frame in enumerate(phase_frames):
                is_last = idx == len(phase_frames) - 1
                prefix = "  └─ " if is_last else "  ├─ "
                f_calls = f"{frame.llm_calls} call{'s' if frame.llm_calls != 1 else ''}" if frame.llm_calls else "—"
                table.add_row(
                    Text(prefix + frame.frame_name, style="dim"),
                    f"{frame.duration_s:.1f}s",
                    f_calls,
                )

        table.add_section()

        # Totals row.
        pipeline_s = max(0.0, report.total_duration_s - (report.llm_duration_total_ms / 1000))
        llm_s = report.llm_duration_total_ms / 1000
        llm_pct = report.llm_overhead_pct
        pipeline_pct = max(0.0, 100 - llm_pct)

        table.add_row(
            Text("TOTAL", style="bold white"),
            f"{report.total_duration_s:.1f}s",
            f"{report.llm_calls_total} call{'s' if report.llm_calls_total != 1 else ''}",
        )
        table.add_row(
            Text("LLM overhead", style="dim"),
            f"{llm_s:.1f}s",
            f"{llm_pct:.0f}%",
        )
        table.add_row(
            Text("Pipeline overhead", style="dim"),
            f"{pipeline_s:.1f}s",
            f"{pipeline_pct:.0f}%",
        )

        console.print()
        console.print(table)

        # Comparison with previous run.
        if prev is not None:
            delta_s = report.total_duration_s - prev.total_duration_s
            delta_pct = (delta_s / prev.total_duration_s * 100) if prev.total_duration_s > 0 else 0.0

            try:
                prev_dt = datetime.fromisoformat(prev.timestamp)
                curr_dt = datetime.fromisoformat(report.timestamp)
                age_days = (curr_dt - prev_dt).days
                age_str = f"{age_days} day{'s' if age_days != 1 else ''} ago" if age_days > 0 else "just now"
            except Exception:
                age_str = "previous run"

            sign = "+" if delta_s >= 0 else ""
            color = "red" if delta_s > 2 else "green"
            provider_note = ""
            if prev.provider and prev.provider != report.provider:
                provider_note = f"  [dim](was: {prev.provider})[/dim]"

            console.print(
                f"  [dim]vs. last run ({age_str}): "
                f"[{color}]{sign}{delta_s:.1f}s ({sign}{delta_pct:.0f}%)[/{color}]{provider_note}[/dim]"
            )

        console.print()

    @staticmethod
    def save(report: BenchmarkReport, warden_dir: Path) -> Path:
        """Save report JSON to .warden/benchmarks/, keeping the last 10."""
        bench_dir = warden_dir / "benchmarks"
        bench_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = bench_dir / f"bench-{ts}.json"
        out_path.write_text(json.dumps(report.to_dict(), indent=2))

        # Prune oldest files to maintain cap.
        files = sorted(bench_dir.glob("bench-*.json"))
        while len(files) > _MAX_BENCHMARKS:
            files[0].unlink(missing_ok=True)
            files = files[1:]

        return out_path

    @staticmethod
    def load_previous(warden_dir: Path) -> BenchmarkReport | None:
        """Load the most recent benchmark from .warden/benchmarks/."""
        bench_dir = warden_dir / "benchmarks"
        if not bench_dir.exists():
            return None

        files = sorted(bench_dir.glob("bench-*.json"), reverse=True)
        for f in files:
            try:
                data = json.loads(f.read_text())
                return BenchmarkReport(
                    scan_id=data.get("scan_id", ""),
                    timestamp=data.get("timestamp", ""),
                    provider=data.get("provider", ""),
                    model=data.get("model", ""),
                    files_scanned=data.get("files_scanned", 0),
                    total_bytes=data.get("total_bytes", 0),
                    total_duration_s=data.get("total_duration_s", 0.0),
                    phases=[
                        PhaseEntry(
                            name=p["name"],
                            duration_s=p.get("duration_s", 0.0),
                            llm_calls=p.get("llm_calls", 0),
                        )
                        for p in data.get("phases", [])
                    ],
                    frames=[
                        FrameEntry(
                            frame_id=f_d.get("frame_id", ""),
                            frame_name=f_d.get("frame_name", ""),
                            phase=f_d.get("phase", "unknown"),
                            duration_s=f_d.get("duration_s", 0.0),
                            findings=f_d.get("findings", 0),
                            status=f_d.get("status", ""),
                            llm_calls=f_d.get("llm_calls", 0),
                            llm_duration_ms=f_d.get("llm_duration_ms", 0.0),
                        )
                        for f_d in data.get("frames", [])
                    ],
                    llm_calls_total=data.get("llm_calls_total", 0),
                    llm_duration_total_ms=data.get("llm_duration_total_ms", 0.0),
                    findings_total=data.get("findings_total", 0),
                )
            except Exception:
                continue

        return None
