"""Constraint tests.

The schedulers are heuristics, so there is no expected output to compare
against. What *can* be asserted is that no plan ever violates a hard
constraint - capacity, absences, the maximum lead time, team membership -
and that every task is either scheduled exactly once or reported as
unscheduled. These are the properties a planner would otherwise have to
check by hand on a 27k-row spreadsheet.
"""

from __future__ import annotations

import pandas as pd
import pytest

from maintenance_scheduler.domain import Absence, PlanningContext, Task, Team
from maintenance_scheduler.scheduling.ordering import batched_order, due_date_windows
from maintenance_scheduler.scheduling.team import schedule_by_team
from maintenance_scheduler.scheduling.technician import schedule_by_technician

SCHEDULERS = [schedule_by_technician, schedule_by_team]


@pytest.fixture
def context() -> PlanningContext:
    days = list(pd.bdate_range("2026-01-05", "2026-04-30"))
    return PlanningContext(
        working_days=days,
        teams={
            "T1": Team("T1", ["alice", "bob"], daily_hours=4.0),
            "T2": Team("T2", ["carol"], daily_hours=4.0),
        },
        absences=[Absence("alice", pd.Timestamp("2026-02-02"), pd.Timestamp("2026-02-13"))],
        activity_labels={},
        start_date=pd.Timestamp("2026-01-05"),
        end_date=pd.Timestamp("2026-04-30"),
        max_lead_days=30,
        batching_window_days=30,
    )


def make_task(task_id: int, team: str, due: str, hours: float, building: str = "B01") -> Task:
    return Task(
        task_id=task_id,
        equipment=f"EQ{task_id}",
        maintenance_plan="WP",
        plan_description="desc",
        activity="Wartung",
        technician_group=team,
        location=f"{building}|EG",
        building=building,
        due_date=pd.Timestamp(due),
        duration_hours=hours,
    )


@pytest.fixture
def tasks() -> list[Task]:
    out = []
    for i in range(40):
        team = "T1" if i % 3 else "T2"
        building = f"B{i % 4:02d}"
        due = pd.Timestamp("2026-02-01") + pd.Timedelta(days=2 * i)
        out.append(make_task(i, team, str(due.date()), 0.5 + (i % 3) * 0.5, building))
    return out


@pytest.mark.parametrize("scheduler", SCHEDULERS)
def test_every_task_is_accounted_for(scheduler, tasks, context):
    schedule = scheduler(tasks, context)
    seen = [a.task.task_id for a in schedule.assignments] + [
        t.task_id for t in schedule.unscheduled
    ]
    assert sorted(seen) == sorted(t.task_id for t in tasks)


@pytest.mark.parametrize("scheduler", SCHEDULERS)
def test_daily_capacity_is_never_exceeded(scheduler, tasks, context):
    schedule = scheduler(tasks, context)
    frame = schedule.to_frame()
    load = frame.groupby(["resource", "date"])["duration_hours"].sum()
    for (resource, day), hours in load.items():
        if schedule.mode == "technician":
            capacity = context.teams[context.team_of(resource)].daily_hours
        else:
            capacity = context.headcount(resource, day) * context.teams[resource].daily_hours
        # A single oversized task is allowed to occupy a whole day on its own.
        single = len(frame[(frame.resource == resource) & (frame.date == day)]) == 1
        assert hours <= capacity or single


@pytest.mark.parametrize("scheduler", SCHEDULERS)
def test_max_lead_time_is_respected(scheduler, tasks, context):
    schedule = scheduler(tasks, context)
    for assignment in schedule.assignments:
        assert assignment.days_before_due <= context.max_lead_days


@pytest.mark.parametrize("scheduler", SCHEDULERS)
def test_only_working_days_are_used(scheduler, tasks, context):
    schedule = scheduler(tasks, context)
    working = set(context.working_days)
    assert all(a.day in working for a in schedule.assignments)


def test_absences_are_respected(tasks, context):
    schedule = schedule_by_technician(tasks, context)
    for assignment in schedule.assignments:
        assert context.is_available(assignment.resource, assignment.day)


def test_technician_only_works_for_own_team(tasks, context):
    schedule = schedule_by_technician(tasks, context)
    for assignment in schedule.assignments:
        assert assignment.resource in context.teams[assignment.task.technician_group].technicians


def test_unknown_team_is_reported_not_dropped(context):
    orphan = [make_task(999, "T-UNKNOWN", "2026-03-01", 1.0)]
    for scheduler in SCHEDULERS:
        schedule = scheduler(orphan, context)
        assert not schedule.assignments
        assert [t.task_id for t in schedule.unscheduled] == [999]


def test_workload_is_balanced_between_technicians(tasks, context):
    """Least-loaded-first must not leave one technician idle."""
    schedule = schedule_by_technician(tasks, context)
    frame = schedule.to_frame()
    hours = frame[frame["technician_group"] == "T1"].groupby("resource")["duration_hours"].sum()
    assert len(hours) == 2
    # alice is absent for two weeks, so an exact split is impossible;
    # a 2:1 imbalance would mean the balancing is broken.
    assert hours.max() / hours.min() < 2.0


def test_windows_cover_all_tasks(tasks):
    windowed = [t for _, bucket in due_date_windows(tasks, 30) for t in bucket]
    assert sorted(t.task_id for t in windowed) == sorted(t.task_id for t in tasks)


def test_building_batching_reduces_switches(tasks):
    """Ordering by building must group a building's tasks together."""
    ordered = batched_order(tasks, 30)
    switches = sum(1 for a, b in zip(ordered, ordered[1:]) if a.building != b.building)
    naive = sorted(tasks, key=lambda t: t.due_date)
    naive_switches = sum(1 for a, b in zip(naive, naive[1:]) if a.building != b.building)
    assert switches < naive_switches
