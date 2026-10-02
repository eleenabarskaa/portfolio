"""Evaluation of a produced schedule.

There is no ground-truth "optimal" plan to compare against, so the plan is
evaluated on the four quantities the department is actually judged on:

``compliance``  - share of tasks executed on or before the legal due date,
                  and the same figure for the regulator-critical
                  metrological controls (PMK) alone. This is the number an
                  audit looks at.
``coverage``    - share of tasks that could be placed at all inside the
                  horizon. Whatever is left over is the real capacity gap
                  and is exported as its own list.
``utilisation`` - booked hours / available hours, per resource. Too low
                  means idle capacity, ~100% means the plan has no room for
                  unplanned repairs.
``travel``      - number of building changes per resource-day. A proxy for
                  walking time inside a hospital campus; the metric the
                  building-batching was introduced to improve.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .domain import PlanningContext, Schedule


@dataclass
class ScheduleMetrics:
    mode: str
    tasks_total: int
    tasks_scheduled: int
    tasks_unscheduled: int
    coverage_rate: float
    on_time_rate: float
    on_time_rate_metrological: float
    mean_days_before_due: float
    scheduled_hours: float
    available_hours: float
    utilisation_rate: float
    working_days_used: int
    building_switches_per_day: float
    tasks_per_resource_day: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _available_hours(schedule: Schedule, context: PlanningContext) -> float:
    if schedule.mode == "technician":
        total = 0.0
        for team in context.teams.values():
            for technician in team.technicians:
                total += len(context.available_days(technician)) * team.daily_hours
        return total

    total = 0.0
    for team_name, team in context.teams.items():
        for day in context.working_days:
            total += context.headcount(team_name, day) * team.daily_hours
    return total


def building_switches(frame: pd.DataFrame) -> float:
    """Average number of building changes within one resource-day."""
    if frame.empty:
        return 0.0
    switches, days = 0, 0
    for _, block in frame.sort_values(["resource", "date"]).groupby(["resource", "date"]):
        buildings = block["building"].tolist()
        switches += sum(1 for a, b in zip(buildings, buildings[1:]) if a != b)
        days += 1
    return switches / days if days else 0.0


def evaluate(schedule: Schedule, context: PlanningContext) -> ScheduleMetrics:
    frame = schedule.to_frame()
    total = len(schedule.assignments) + len(schedule.unscheduled)

    if frame.empty:
        return ScheduleMetrics(
            mode=schedule.mode,
            tasks_total=total,
            tasks_scheduled=0,
            tasks_unscheduled=len(schedule.unscheduled),
            coverage_rate=0.0,
            on_time_rate=0.0,
            on_time_rate_metrological=0.0,
            mean_days_before_due=0.0,
            scheduled_hours=0.0,
            available_hours=_available_hours(schedule, context),
            utilisation_rate=0.0,
            working_days_used=0,
            building_switches_per_day=0.0,
            tasks_per_resource_day=0.0,
        )

    metrological = frame[frame["activity"] == "Messtechnische Kontrolle"]
    available = _available_hours(schedule, context)
    scheduled_hours = float(frame["duration_hours"].sum())
    resource_days = frame.groupby(["resource", "date"]).ngroups

    return ScheduleMetrics(
        mode=schedule.mode,
        tasks_total=total,
        tasks_scheduled=len(frame),
        tasks_unscheduled=len(schedule.unscheduled),
        coverage_rate=round(len(frame) / total, 4) if total else 0.0,
        on_time_rate=round(float(frame["on_time"].mean()), 4),
        on_time_rate_metrological=(
            round(float(metrological["on_time"].mean()), 4) if len(metrological) else float("nan")
        ),
        mean_days_before_due=round(float(frame["days_before_due"].mean()), 2),
        scheduled_hours=round(scheduled_hours, 1),
        available_hours=round(available, 1),
        utilisation_rate=round(scheduled_hours / available, 4) if available else 0.0,
        working_days_used=int(frame["date"].nunique()),
        building_switches_per_day=round(building_switches(frame), 3),
        tasks_per_resource_day=round(len(frame) / resource_days, 2) if resource_days else 0.0,
    )


def workload_by_resource(schedule: Schedule) -> pd.DataFrame:
    """Hours and tasks per resource - the fairness view."""
    frame = schedule.to_frame()
    if frame.empty:
        return frame
    return (
        frame.groupby("resource")
        .agg(
            tasks=("equipment", "size"),
            hours=("duration_hours", "sum"),
            days_used=("date", "nunique"),
            on_time_rate=("on_time", "mean"),
        )
        .round(3)
        .sort_values("hours", ascending=False)
        .reset_index()
    )


def monthly_load(schedule: Schedule) -> pd.DataFrame:
    frame = schedule.to_frame()
    if frame.empty:
        return frame
    monthly = frame.copy()
    monthly["month"] = monthly["date"].dt.to_period("M").astype(str)
    return (
        monthly.groupby("month")
        .agg(tasks=("equipment", "size"), hours=("duration_hours", "sum"))
        .reset_index()
    )
