"""Typed access to the YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


@dataclass(frozen=True)
class DataConfig:
    workbook: Path
    orders_sheet: str
    reference_sheet: str
    columns: dict[str, str]


@dataclass(frozen=True)
class PlanningConfig:
    keep_statuses: list[str]
    excluded_groups: list[str]
    external_groups: list[str]
    default_duration_hours: float
    external_duration_marker: list[str]
    max_lead_days: int
    batching_window_days: int
    default_daily_hours: float


@dataclass(frozen=True)
class OutputConfig:
    directory: Path
    schedule_file: str
    unscheduled_file: str
    external_file: str
    metrics_file: str

    def path(self, name: str) -> Path:
        return self.directory / name


@dataclass(frozen=True)
class Config:
    data: DataConfig
    planning: PlanningConfig
    output: OutputConfig
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        data = raw["data"]
        output = raw["output"]
        return cls(
            data=DataConfig(
                workbook=Path(data["workbook"]),
                orders_sheet=data["orders_sheet"],
                reference_sheet=data["reference_sheet"],
                columns=data["columns"],
            ),
            planning=PlanningConfig(**raw["planning"]),
            output=OutputConfig(
                directory=Path(output["directory"]),
                schedule_file=output["schedule_file"],
                unscheduled_file=output["unscheduled_file"],
                external_file=output["external_file"],
                metrics_file=output["metrics_file"],
            ),
            raw=raw,
        )
