"""Per-technician scheduling: every task gets a named owner and a date.

Constraints enforced
--------------------
1. A task may only be executed by a technician of its own technician group
   (the groups map to device families: imaging, dialysis, labs, ...).
2. A technician works only on calendar working days, minus their absences.
3. Per day, a technician has ``daily_hours`` of *planned* maintenance
   capacity; the rest of the shift is reserved for unplanned repairs.
4. A task must not be executed more than ``max_lead_days`` before its legal
   due date, otherwise the maintenance interval drifts from the
   manufacturer's specification.
5. Inside a due-date window, tasks are processed building by building
   (see ``ordering.py``) so that consecutive tasks of one technician tend to
   sit in the same building.

Load balancing
--------------
Round-robin alone leaves technicians with different absence patterns badly
balanced. Instead, among the technicians of the group the one with the
*earliest free slot* receives the task ("least loaded first"). Because the
free slot moves forward as work is added, this converges to an even
distribution of the workload without any global optimisation step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from ..domain import Assignment, PlanningContext, Schedule, Task, group_by_team
from .ordering import batched_order


@dataclass
class TechnicianCalendar:
    """Remaining capacity of one technician, day by day."""

    technician: str
    days: list[pd.Timestamp]
    daily_hours: float
    used: dict[pd.Timestamp, float] = field(default_factory=dict)
    cursor: int = 0  # first day that may still have free capacity
    total_hours: float = 0.0  # everything booked so far, for load balancing

    def remaining(self, day: pd.Timestamp) -> float:
        return self.daily_hours - self.used.get(day, 0.0)

    def first_free_day(self, earliest: pd.Timestamp, hours: float) -> int | None:
        """Index of the first day at or after ``earliest`` that fits ``hours``.

        A task longer than a full day is allowed to occupy a day on its own:
        without that rule a 6-hour acceptance test could never be planned
        against a 4-hour daily capacity.
        """
        for idx in range(self.cursor, len(self.days)):
            day = self.days[idx]
            if day < earliest:
                continue
            free = self.remaining(day)
            if hours <= free:
                return idx
            if hours > self.daily_hours and free == self.daily_hours:
                return idx  # oversized task takes a whole empty day
        return None

    def book(self, idx: int, hours: float) -> pd.Timestamp:
        day = self.days[idx]
        self.used[day] = self.used.get(day, 0.0) + hours
        self.total_hours += hours
        while self.cursor < len(self.days) and self.remaining(self.days[self.cursor]) <= 0:
            self.cursor += 1
        return day

    def next_free_date(self) -> pd.Timestamp:
        idx = min(self.cursor, len(self.days) - 1)
        return self.days[idx]


def _build_calendars(
    context: PlanningContext, team_name: str
) -> dict[str, TechnicianCalendar]:
    team = context.teams[team_name]
    return {
        technician: TechnicianCalendar(
            technician=technician,
            days=context.available_days(technician),
            daily_hours=team.daily_hours,
        )
        for technician in team.technicians
    }


def schedule_by_technician(
    tasks: Sequence[Task], context: PlanningContext
) -> Schedule:
    """Assign every task to a technician and a day."""
    schedule = Schedule(mode="technician")

    for team_name, team_tasks in group_by_team(tasks).items():
        if team_name not in context.teams:
            schedule.unscheduled.extend(team_tasks)
            continue

        calendars = _build_calendars(context, team_name)
        calendars = {k: v for k, v in calendars.items() if v.days}
        if not calendars:
            schedule.unscheduled.extend(team_tasks)
            continue

        for task in batched_order(team_tasks, context.batching_window_days):
            earliest = task.due_date - pd.Timedelta(days=context.max_lead_days)

            # Candidate = every technician who can fit the task at all.
            # Primary criterion: who can start it soonest - that keeps the
            # task as close to its due date as the calendar allows.
            # Tie-break: the technician with the smallest workload so far.
            # Without the second criterion the first technician in the list
            # absorbs every short task until their day is full, which leaves
            # colleagues idle on a sparsely loaded team.
            best: tuple[pd.Timestamp, float, str, int] | None = None
            for name, calendar in calendars.items():
                idx = calendar.first_free_day(earliest, task.duration_hours)
                if idx is None:
                    continue
                candidate = (calendar.days[idx], calendar.total_hours, name, idx)
                if best is None or candidate < best:
                    best = candidate

            if best is None:
                schedule.unscheduled.append(task)
                continue

            _, _, name, idx = best
            day = calendars[name].book(idx, task.duration_hours)
            schedule.assignments.append(Assignment(task=task, day=day, resource=name))

    return schedule
