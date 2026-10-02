"""Task ordering: due-date windows first, buildings inside a window.

Why not a single global sort?

* Sorting strictly by due date produces a plan in which a technician walks
  across the whole hospital several times a day - the dominant hidden cost
  of the manual plan.
* Sorting strictly by building breaks the legal deadlines, because a
  building may contain devices due eleven months apart.

The compromise implemented here is a rolling window: inside a window of
``batching_window_days`` the deadlines are considered equivalent, so tasks
are re-ordered by building (busiest building first, to fill whole days);
across windows the due-date order is preserved. The window length is a
configuration value, which lets the planner trade deadline slack against
walking time without touching the code.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Iterator, Sequence

import pandas as pd

from ..domain import Task


def due_date_windows(
    tasks: Sequence[Task], window_days: int
) -> Iterator[tuple[pd.Timestamp, list[Task]]]:
    """Yield ``(window_start, tasks)`` for consecutive due-date windows."""
    if not tasks:
        return

    ordered = sorted(tasks, key=lambda t: t.due_date)
    window_start = ordered[0].due_date
    last_due = ordered[-1].due_date
    cursor = 0

    while window_start <= last_due:
        window_end = window_start + timedelta(days=window_days)
        bucket: list[Task] = []
        while cursor < len(ordered) and ordered[cursor].due_date <= window_end:
            bucket.append(ordered[cursor])
            cursor += 1
        if bucket:
            yield window_start, bucket
        window_start = window_end


def order_by_building(tasks: Sequence[Task]) -> list[Task]:
    """Group tasks by building, busiest building first, deadline order inside."""
    counts = Counter(task.building for task in tasks)
    return sorted(
        tasks,
        key=lambda t: (-counts[t.building], t.building, t.due_date),
    )


def batched_order(tasks: Sequence[Task], window_days: int) -> list[Task]:
    """Full ordering used by both schedulers."""
    result: list[Task] = []
    for _, bucket in due_date_windows(tasks, window_days):
        result.extend(order_by_building(bucket))
    return result
