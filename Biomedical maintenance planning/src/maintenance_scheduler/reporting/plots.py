"""Charts used to review a plan before it is handed to the teams.

Three questions, three charts - nothing decorative:

1. Is the load spread evenly over the year, or does the plan build a peak
   that the team cannot absorb?
2. Is the load spread evenly over the people?
3. How much deadline slack does the plan leave? A plan that executes
   everything on the last legal day is technically compliant and
   operationally fragile.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..domain import Schedule  # noqa: E402
from ..metrics import monthly_load, workload_by_resource  # noqa: E402

# Validated categorical slots 1-3 (light surface); single-series charts use slot 1.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e4e3df"


def _style(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, color=INK, fontsize=12, pad=12, loc="left")
    ax.set_xlabel(xlabel, color=INK_MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=INK_MUTED, fontsize=9)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.patch.set_facecolor(SURFACE)
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def plot_monthly_load(schedule: Schedule, path: str | Path) -> Path:
    data = monthly_load(schedule)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.set_facecolor(SURFACE)
    ax.bar(data["month"], data["hours"], color=SERIES[0], width=0.7)
    _style(ax, "Planned maintenance hours per month", ylabel="Hours")
    ax.set_xticks(range(len(data)))
    ax.set_xticklabels(data["month"], rotation=45, ha="right")
    return _save(fig, Path(path))


def plot_workload_by_resource(schedule: Schedule, path: str | Path) -> Path:
    data = workload_by_resource(schedule).sort_values("hours")
    fig, ax = plt.subplots(figsize=(7, max(3.0, 0.32 * len(data))))
    ax.set_facecolor(SURFACE)
    ax.barh(data["resource"], data["hours"], color=SERIES[0], height=0.65)
    _style(ax, "Planned hours per resource", xlabel="Hours")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    return _save(fig, Path(path))


def plot_deadline_slack(schedule: Schedule, path: str | Path) -> Path:
    frame = schedule.to_frame()
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.set_facecolor(SURFACE)
    ax.hist(frame["days_before_due"], bins=32, color=SERIES[0])
    ax.axvline(0, color=INK_MUTED, linewidth=1.5, linestyle="--")
    _style(
        ax,
        "Deadline slack (days between execution and legal due date)",
        xlabel="Days before due date  -  negative = overdue",
        ylabel="Tasks",
    )
    return _save(fig, Path(path))


def plot_all(schedule: Schedule, directory: str | Path) -> list[Path]:
    directory = Path(directory)
    return [
        plot_monthly_load(schedule, directory / "monthly_load.png"),
        plot_workload_by_resource(schedule, directory / "workload_by_resource.png"),
        plot_deadline_slack(schedule, directory / "deadline_slack.png"),
    ]
