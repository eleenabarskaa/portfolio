"""Turning 69k raw SAP rows into a clean, schedulable task table.

Roughly two thirds of the export is *not* schedulable work: simulated
future calls, deactivated equipment, calls outside the planning horizon
and orders belonging to an external service provider. Filtering these out
before scheduling is what makes the problem tractable, so every filter is
explicit and counted, and the counts are returned for the data-quality
report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import Config
from ..domain import PlanningContext


@dataclass
class CleaningReport:
    """How many rows each filter removed - printed and stored with the run."""

    steps: list[tuple[str, int]] = field(default_factory=list)
    initial_rows: int = 0
    final_rows: int = 0

    def record(self, label: str, before: int, after: int) -> None:
        self.steps.append((label, before - after))

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.steps, columns=["filter", "rows_removed"])


def split_location(value: object) -> str:
    """Normalise the free-text location into ``BUILDING|FLOOR``.

    The SAP location field is typed by hand and looks like
    ``"B12, 3rd floor"`` or just ``"B12"``. Only the building part is used
    for batching, but the floor is kept in the printed work sheet because
    the technicians navigate by it.
    """
    parts = str(value).split(",")
    if len(parts) >= 2:
        return "|".join(p.strip() for p in parts[:2])
    return parts[0].strip()


def building_of(location: str) -> str:
    return str(location).split("|")[0].strip()


def normalise_duration(value: object, config: Config) -> float:
    """Map the SAP duration column onto usable hours.

    * ``"fremd"`` marks work done by an external provider -> 0 internal hours.
    * missing or zero durations are replaced by the agreed minimum visit
      length, so that a device is never scheduled as "free of effort".
    """
    if isinstance(value, str) and value.strip() in config.planning.external_duration_marker:
        return 0.0
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return config.planning.default_duration_hours
    if pd.isna(hours) or hours == 0:
        return config.planning.default_duration_hours
    return round(hours, 1)


def clean_orders(
    frame: pd.DataFrame,
    config: Config,
    context: PlanningContext,
) -> tuple[pd.DataFrame, CleaningReport]:
    """Filter, type and enrich the raw call list."""
    report = CleaningReport(initial_rows=len(frame))
    plan = config.planning

    before = len(frame)
    frame = frame[frame["status"].isin(plan.keep_statuses)]
    report.record("status not actionable (simulated / deactivated)", before, len(frame))

    before = len(frame)
    frame = frame[~frame["technician_group"].isin(plan.excluded_groups + ["nan", ""])]
    report.record("external provider or unassigned group", before, len(frame))

    frame = frame.copy()
    frame["due_date"] = pd.to_datetime(frame["due_date"], errors="coerce")

    before = len(frame)
    frame = frame.dropna(subset=["due_date"])
    report.record("missing due date", before, len(frame))

    before = len(frame)
    frame = frame[
        (frame["due_date"] >= context.start_date) & (frame["due_date"] <= context.end_date)
    ]
    report.record("outside the planning horizon", before, len(frame))

    frame["duration_hours"] = frame["duration_hours"].apply(
        lambda v: normalise_duration(v, config)
    )
    frame["activity"] = frame["activity_code"].map(context.activity_labels).fillna("")
    frame["location"] = frame["location"].apply(split_location)
    frame["building"] = frame["location"].apply(building_of)

    frame = frame.sort_values("due_date").reset_index(drop=True)
    report.final_rows = len(frame)
    return frame, report


def external_orders(frame: pd.DataFrame, config: Config, context: PlanningContext) -> pd.DataFrame:
    """Work orders handed over to the external service provider.

    They are not scheduled internally but still have to be tracked, so they
    are exported month by month for the provider's contract review.
    """
    external = frame[frame["technician_group"].isin(config.planning.external_groups)].copy()
    external["due_date"] = pd.to_datetime(external["due_date"], errors="coerce")
    external = external.dropna(subset=["due_date"])
    external["activity"] = external["activity_code"].map(context.activity_labels).fillna("")
    external["location"] = external["location"].apply(split_location)
    return external.sort_values("due_date")
