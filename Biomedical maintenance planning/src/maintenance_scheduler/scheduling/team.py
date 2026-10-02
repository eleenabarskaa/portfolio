"""Per-team scheduling: capacity is pooled, the team lead dispatches.

This is the variant the department actually preferred. The per-technician
plan (``technician.py``) is precise but brittle: one sick day invalidates a
named plan for weeks, and the team leads want to keep the freedom to swap
people on the day. So the second scheduler plans at team level - for each
working day it computes

    capacity(day) = technicians present that day x daily maintenance hours

and fills that capacity with the same window/building ordering. The output
is one sheet per team: "these devices, this day", with the assignment of
people left to the team lead.

Keeping both schedulers behind the same interface made it possible to
compare the two policies on the same data instead of arguing about them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from ..domain import Assignment, PlanningContext, Schedule, Task, group_by_team
from .ordering import batched_order


@dataclass
class TeamCalendar:
    team: str
    days: list[pd.Timestamp]
    capacity: dict[pd.Timestamp, float]
    used: dict[pd.Timestamp, float] = field(default_factory=dict)
    cursor: int = 0

    def remaining(self, day: pd.Timestamp) -> float:
        return self.capacity[day] - self.used.get(day, 0.0)

    def first_free_day(self, earliest: pd.Timestamp, hours: float) -> int | None:
        for idx in range(self.cursor, len(self.days)):
            day = self.days[idx]
            if day < earliest:
                continue
            free = self.remaining(day)
            if hours <= free:
                return idx
            if hours > self.capacity[day] and free == self.capacity[day]:
                return idx
        return None

    def book(self, idx: int, hours: float) -> pd.Timestamp:
        day = self.days[idx]
        self.used[day] = self.used.get(day, 0.0) + hours
        while self.cursor < len(self.days) and self.remaining(self.days[self.cursor]) <= 0:
            self.cursor += 1
        return day


def build_team_calendar(context: PlanningContext, team_name: str) -> TeamCalendar:
    """Daily capacity = present technicians x the team's daily hours."""
    team = context.teams[team_name]
    capacity: dict[pd.Timestamp, float] = {}
    days: list[pd.Timestamp] = []
    for day in context.working_days:
        present = context.headcount(team_name, day)
        if present == 0:
            continue  # whole team absent - no capacity at all
        capacity[day] = present * team.daily_hours
        days.append(day)
    return TeamCalendar(team=team_name, days=days, capacity=capacity)


def schedule_by_team(tasks: Sequence[Task], context: PlanningContext) -> Schedule:
    schedule = Schedule(mode="team")

    for team_name, team_tasks in group_by_team(tasks).items():
        if team_name not in context.teams:
            schedule.unscheduled.extend(team_tasks)
            continue

        calendar = build_team_calendar(context, team_name)
        if not calendar.days:
            schedule.unscheduled.extend(team_tasks)
            continue

        for task in batched_order(team_tasks, context.batching_window_days):
            earliest = task.due_date - pd.Timedelta(days=context.max_lead_days)
            idx = calendar.first_free_day(earliest, task.duration_hours)
            if idx is None:
                schedule.unscheduled.append(task)
                continue
            day = calendar.book(idx, task.duration_hours)
            schedule.assignments.append(
                Assignment(task=task, day=day, resource=team_name)
            )

    return schedule
