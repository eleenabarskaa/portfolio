"""Excel deliverables.

The plan is consumed on paper and in Excel by people who do not use Python,
so the export is part of the product, not an afterthought:

* one sheet per resource (technician or team), chronological;
* German column headers, because the sheet is printed and signed in a
  German hospital;
* the deadline column colour-coded, so an overdue line is visible without
  reading a date;
* metrological controls (PMK) highlighted, because they are the ones the
  regulator checks first.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..domain import PlanningContext, Schedule

GERMAN_HEADERS = {
    "date": "Datum",
    "equipment": "Equipment",
    "maintenance_plan": "Wartungsplan",
    "duration_hours": "Dauer (h)",
    "technician_group": "Technikergruppe",
    "activity": "ILA",
    "plan_description": "WPlan-Beschreibung",
    "location": "Standort",
    "due_date": "Stichtag",
    "on_time": "Rechtzeitige Wartung",
    "days_before_due": "Differenz (Tage)",
}

SHEET_COLUMNS = list(GERMAN_HEADERS)


def _highlight_deadline(value: str) -> str:
    return "background-color: #c6efce" if value == "Ja" else "background-color: #ffc7ce"


def _highlight_metrological(value: str) -> str:
    return "background-color: #ffeb9c" if value == "Messtechnische Kontrolle" else ""


def _sheet_frame(block: pd.DataFrame) -> pd.DataFrame:
    sheet = block[SHEET_COLUMNS].copy()
    sheet["on_time"] = sheet["on_time"].map({True: "Ja", False: "Nein"})
    sheet["date"] = pd.to_datetime(sheet["date"]).dt.strftime("%d.%m.%Y")
    sheet["due_date"] = pd.to_datetime(sheet["due_date"]).dt.strftime("%d.%m.%Y")
    return sheet.rename(columns=GERMAN_HEADERS)


def _safe_sheet_name(name: str) -> str:
    cleaned = "".join(c for c in str(name) if c not in "[]:*?/\\")
    return cleaned[:31] or "Sheet"


def styling_available() -> bool:
    """Cell colouring goes through pandas' Styler, which needs jinja2.

    jinja2 is a declared dependency, so this is normally true. The check exists
    because the alternative failure mode is bad: the Styler raises while the
    ExcelWriter is open, no sheet is ever written, and the user sees
    "At least one sheet must be visible" from deep inside openpyxl — an error
    that says nothing about the actual cause. Better to lose the colours and
    still hand over a usable plan.
    """
    try:
        import jinja2  # noqa: F401
    except ImportError:
        return False
    return True


def _write_sheet(frame: pd.DataFrame, writer, sheet_name: str, highlights) -> None:
    """Write one sheet, styled when possible, plain when not."""
    if styling_available():
        styled = frame.style
        for func, columns in highlights:
            styled = styled.map(func, subset=columns)
        styled.to_excel(writer, sheet_name=sheet_name, index=False)
    else:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)


def export_schedule(
    schedule: Schedule, context: PlanningContext, path: str | Path
) -> Path:
    """One workbook, one sheet per resource."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = schedule.to_frame()

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if frame.empty:
            pd.DataFrame(columns=list(GERMAN_HEADERS.values())).to_excel(
                writer, sheet_name="leer", index=False
            )
            return path

        for resource, block in frame.groupby("resource"):
            sheet = _sheet_frame(block.sort_values("date"))
            if schedule.mode == "technician":
                team = context.team_of(resource) or ""
                name = _safe_sheet_name(f"{team} ({resource})")
            else:
                name = _safe_sheet_name(resource)
            _write_sheet(
                sheet,
                writer,
                name,
                [
                    (_highlight_deadline, ["Rechtzeitige Wartung"]),
                    (_highlight_metrological, ["ILA"]),
                ],
            )
    return path


def export_unscheduled(schedule: Schedule, path: str | Path) -> Path:
    """Tasks that did not fit - the capacity gap, handed back to management."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = schedule.unscheduled_frame()
    if not frame.empty:
        frame = frame.copy()
        frame["due_date"] = pd.to_datetime(frame["due_date"]).dt.strftime("%d.%m.%Y")
        frame = frame.rename(
            columns={
                "equipment": "Equipment",
                "maintenance_plan": "Wartungsplan",
                "plan_description": "WPlan-Beschreibung",
                "activity": "ILA",
                "technician_group": "Team",
                "location": "Standort",
                "due_date": "Stichtag",
                "duration_hours": "Dauer (h)",
            }
        )
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            _write_sheet(
                frame, writer, "Nicht erledigt", [(_highlight_metrological, ["ILA"])]
            )
    else:
        pd.DataFrame(columns=["Equipment"]).to_excel(
            path, sheet_name="Nicht erledigt", index=False
        )
    return path


def export_external(frame: pd.DataFrame, path: str | Path) -> Path:
    """External-provider orders, one sheet per month for the contract review."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "due_date",
        "equipment",
        "maintenance_plan",
        "activity",
        "plan_description",
        "technician_group",
        "location",
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if frame.empty:
            pd.DataFrame(columns=columns).to_excel(writer, sheet_name="leer", index=False)
            return path
        block = frame[columns].copy()
        block["month"] = pd.to_datetime(block["due_date"]).dt.to_period("M")
        for month, month_block in block.groupby("month"):
            sheet = month_block.drop(columns=["month"]).copy()
            sheet["due_date"] = pd.to_datetime(sheet["due_date"]).dt.strftime("%d.%m.%Y")
            _write_sheet(
                sheet, writer, str(month), [(_highlight_metrological, ["activity"])]
            )
    return path
