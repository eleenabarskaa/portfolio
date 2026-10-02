"""Domain objects shared by the loaders, the schedulers and the reports.

The whole planning problem is expressed with four concepts only:

* ``Task``      - one legally required maintenance call on one device.
* ``Technician`` - a person, belonging to exactly one technician group.
* ``Team``      - a technician group with its own daily capacity.
* ``PlanningContext`` - the calendar, the absences and the code tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class Task:
    """One maintenance call that must be executed before ``due_date``."""

    task_id: int
    equipment: str
    maintenance_plan: str
    plan_description: str
    activity: str
    technician_group: str
    location: str
    building: str
    due_date: pd.Timestamp
    duration_hours: float

    @property
    def is_metrological(self) -> bool:
        """Metrological control (PMK) is the regulator-critical subset."""
        return self.activity == "Messtechnische Kontrolle"


@dataclass(frozen=True)
class Absence:
    technician: str
    start: pd.Timestamp
    end: pd.Timestamp

    def covers(self, day: pd.Timestamp) -> bool:
        return self.start <= day <= self.end


@dataclass
class Team:
    name: str
    technicians: list[str]
    daily_hours: float


@dataclass
class PlanningContext:
    """Everything that constrains the plan but is not a task."""

    working_days: list[pd.Timestamp]
    teams: dict[str, Team]
    absences: list[Absence]
    activity_labels: dict[str, str]
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    max_lead_days: int
    batching_window_days: int

    _absence_index: dict[str, list[Absence]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for absence in self.absences:
            self._absence_index.setdefault(absence.technician, []).append(absence)

    def is_available(self, technician: str, day: pd.Timestamp) -> bool:
        """A technician is available on a working day outside every absence."""
        return not any(a.covers(day) for a in self._absence_index.get(technician, ()))

    def available_days(self, technician: str) -> list[pd.Timestamp]:
        return [d for d in self.working_days if self.is_available(technician, d)]

    def headcount(self, team: str, day: pd.Timestamp) -> int:
        """Technicians of ``team`` actually present on ``day``."""
        return sum(
            1 for t in self.teams[team].technicians if self.is_available(t, day)
        )

    def team_of(self, technician: str) -> str | None:
        for name, team in self.teams.items():
            if technician in team.technicians:
                return name
        return None


@dataclass
class Assignment:
    """A task placed on a concrete day, for a technician or for a team."""

    task: Task
    day: pd.Timestamp
    resource: str  # technician id, or team name in team mode

    @property
    def on_time(self) -> bool:
        return self.day <= self.task.due_date

    @property
    def days_before_due(self) -> int:
        return (self.task.due_date - self.day).days


@dataclass
class Schedule:
    """Result of a scheduling run."""

    mode: str  # "technician" or "team"
    assignments: list[Assignment] = field(default_factory=list)
    unscheduled: list[Task] = field(default_factory=list)

    def to_frame(self) -> pd.DataFrame:
        rows = [
            {
                "resource": a.resource,
                "date": a.day,
                "equipment": a.task.equipment,
                "maintenance_plan": a.task.maintenance_plan,
                "plan_description": a.task.plan_description,
                "activity": a.task.activity,
                "technician_group": a.task.technician_group,
                "location": a.task.location,
                "building": a.task.building,
                "duration_hours": a.task.duration_hours,
                "due_date": a.task.due_date,
                "on_time": a.on_time,
                "days_before_due": a.days_before_due,
            }
            for a in self.assignments
        ]
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values(["resource", "date"]).reset_index(drop=True)
        return frame

    def unscheduled_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "equipment": t.equipment,
                    "maintenance_plan": t.maintenance_plan,
                    "plan_description": t.plan_description,
                    "activity": t.activity,
                    "technician_group": t.technician_group,
                    "location": t.location,
                    "due_date": t.due_date,
                    "duration_hours": t.duration_hours,
                }
                for t in self.unscheduled
            ]
        )


def tasks_from_frame(frame: pd.DataFrame) -> list[Task]:
    """Build immutable ``Task`` objects from the cleaned order table."""
    return [
        Task(
            task_id=int(idx),
            equipment=str(row.equipment),
            maintenance_plan=str(row.maintenance_plan),
            plan_description=str(row.plan_description),
            activity=str(row.activity),
            technician_group=str(row.technician_group),
            location=str(row.location),
            building=str(row.building),
            due_date=row.due_date,
            duration_hours=float(row.duration_hours),
        )
        for idx, row in frame.iterrows()
    ]


def group_by_team(tasks: Iterable[Task]) -> dict[str, list[Task]]:
    grouped: dict[str, list[Task]] = {}
    for task in tasks:
        grouped.setdefault(task.technician_group, []).append(task)
    for team_tasks in grouped.values():
        team_tasks.sort(key=lambda t: t.due_date)
    return grouped


def as_date(value: pd.Timestamp) -> date:
    return pd.Timestamp(value).date()
