"""End-to-end run: raw workbook in, Excel plan and metrics out."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Config
from .data.loader import build_context, load_orders, load_reference
from .data.preprocessing import CleaningReport, clean_orders, external_orders
from .domain import PlanningContext, Schedule, Task, tasks_from_frame
from .metrics import ScheduleMetrics, evaluate, workload_by_resource
from .reporting import excel, plots
from .scheduling.team import schedule_by_team
from .scheduling.technician import schedule_by_technician

logger = logging.getLogger(__name__)

SCHEDULERS = {
    "technician": schedule_by_technician,
    "team": schedule_by_team,
}


@dataclass
class RunResult:
    schedule: Schedule
    metrics: ScheduleMetrics
    context: PlanningContext
    cleaning: CleaningReport
    tasks: list[Task]
    outputs: dict[str, Path]


def prepare(config: Config) -> tuple[list[Task], PlanningContext, CleaningReport, pd.DataFrame]:
    reference = load_reference(config)
    context = build_context(config, reference)
    raw = load_orders(config)
    cleaned, report = clean_orders(raw, config, context)
    external = external_orders(raw, config, context)
    return tasks_from_frame(cleaned), context, report, external


def run(
    config: Config,
    mode: str = "team",
    make_plots: bool = True,
) -> RunResult:
    if mode not in SCHEDULERS:
        raise ValueError(f"unknown mode {mode!r}, expected one of {sorted(SCHEDULERS)}")

    tasks, context, cleaning, external = prepare(config)
    logger.info(
        "%d schedulable tasks (%d raw rows), %d teams, %d working days",
        len(tasks),
        cleaning.initial_rows,
        len(context.teams),
        len(context.working_days),
    )

    schedule = SCHEDULERS[mode](tasks, context)
    metrics = evaluate(schedule, context)

    out = config.output
    out.directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        "schedule": excel.export_schedule(schedule, context, out.path(out.schedule_file)),
        "unscheduled": excel.export_unscheduled(schedule, out.path(out.unscheduled_file)),
        "external": excel.export_external(external, out.path(out.external_file)),
    }

    metrics_payload = {
        "metrics": metrics.to_dict(),
        "cleaning": {
            "initial_rows": cleaning.initial_rows,
            "final_rows": cleaning.final_rows,
            "removed": dict(cleaning.steps),
        },
        "workload_by_resource": workload_by_resource(schedule).to_dict(orient="records"),
    }
    metrics_path = out.path(out.metrics_file)
    metrics_path.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")
    outputs["metrics"] = metrics_path

    if make_plots and schedule.assignments:
        for path in plots.plot_all(schedule, Path("docs/images")):
            outputs[path.stem] = path

    return RunResult(
        schedule=schedule,
        metrics=metrics,
        context=context,
        cleaning=cleaning,
        tasks=tasks,
        outputs=outputs,
    )


def compare_modes(config: Config) -> pd.DataFrame:
    """Run both policies on the same data and put the metrics side by side."""
    tasks, context, _, _ = prepare(config)
    rows = []
    for mode, scheduler in SCHEDULERS.items():
        schedule = scheduler(tasks, context)
        rows.append(evaluate(schedule, context).to_dict())
    return pd.DataFrame(rows).set_index("mode").T
