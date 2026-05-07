#!/usr/bin/env python3
"""
Metrics calculator — TSR and MTTR.

Task Success Rate (TSR):
  TSR = (successful_tasks / total_tasks) × 100

Mean Time To Resolution (MTTR):
  MTTR = average duration_s across all tasks (successful + failed)
  MTTR_success = average duration_s for successful tasks only
  MTTR_failure = average duration_s for failed tasks only

Usage:
  python calculate.py                    # aggregate metrics
  python calculate.py --by-type          # break down per task_type
  python calculate.py --format json      # machine-readable output

Output example:
  === CIM-AI Agentic System Metrics ===
  Total tasks: 8
  TSR (overall): 87.5%
  MTTR (all):    77.6 s
  MTTR (success):60.3 s
  MTTR (failure): 202.0 s
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schema import TaskEvent, load_events


def compute_metrics(events: list[TaskEvent]) -> dict:
    if not events:
        return {
            "total": 0, "successful": 0, "failed": 0,
            "tsr_pct": None, "mttr_all_s": None,
            "mttr_success_s": None, "mttr_failure_s": None,
        }

    successful = [e for e in events if e.success]
    failed = [e for e in events if not e.success]

    def avg(lst: list[TaskEvent]) -> float | None:
        if not lst:
            return None
        return round(sum(e.duration_s for e in lst) / len(lst), 1)

    return {
        "total": len(events),
        "successful": len(successful),
        "failed": len(failed),
        "tsr_pct": round(len(successful) / len(events) * 100, 1),
        "mttr_all_s": avg(events),
        "mttr_success_s": avg(successful),
        "mttr_failure_s": avg(failed),
    }


def compute_by_type(events: list[TaskEvent]) -> dict[str, dict]:
    by_type: dict[str, list[TaskEvent]] = {}
    for e in events:
        by_type.setdefault(e.task_type, []).append(e)
    return {t: compute_metrics(evts) for t, evts in sorted(by_type.items())}


def format_human(overall: dict, by_type: dict[str, dict] | None = None) -> str:
    lines = ["=== CIM-AI Agentic System Metrics ===", ""]

    def fmt_metric(m: dict, indent: str = "") -> list[str]:
        out = []
        out.append(f"{indent}Total tasks  : {m['total']}")
        out.append(f"{indent}Successful   : {m['successful']}")
        out.append(f"{indent}Failed       : {m['failed']}")
        if m["tsr_pct"] is not None:
            out.append(f"{indent}TSR          : {m['tsr_pct']}%")
        if m["mttr_all_s"] is not None:
            out.append(f"{indent}MTTR (all)   : {m['mttr_all_s']} s")
        if m["mttr_success_s"] is not None:
            out.append(f"{indent}MTTR (ok)    : {m['mttr_success_s']} s")
        if m["mttr_failure_s"] is not None:
            out.append(f"{indent}MTTR (fail)  : {m['mttr_failure_s']} s")
        return out

    lines += fmt_metric(overall)

    if by_type:
        lines += ["", "--- Per task type ---"]
        for task_type, m in by_type.items():
            if m["total"] == 0:
                continue
            lines.append(f"\n[{task_type}]")
            lines += fmt_metric(m, indent="  ")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute TSR / MTTR from events.json")
    parser.add_argument(
        "--events", type=Path,
        default=Path(__file__).parent / "events.json",
        help="Path to events.json",
    )
    parser.add_argument("--by-type", action="store_true", help="Break down metrics per task type")
    parser.add_argument(
        "--format", choices=["human", "json"], default="human",
        help="Output format",
    )
    args = parser.parse_args()

    events = load_events(args.events)
    if not events:
        print("No events found. Add entries to events.json to track tasks.", file=sys.stderr)
        sys.exit(0)

    overall = compute_metrics(events)
    by_type = compute_by_type(events) if args.by_type else None

    if args.format == "json":
        output = {"overall": overall}
        if by_type:
            output["by_type"] = by_type
        print(json.dumps(output, indent=2))
    else:
        print(format_human(overall, by_type))


if __name__ == "__main__":
    main()
