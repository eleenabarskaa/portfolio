"""Generate a synthetic workbook with the same schema as the real SAP export.

The original project runs on a hospital's SAP PM export, which cannot be
published. This script produces a statistically similar *fake* workbook so
that the repository is fully reproducible: same two sheets, same column
names, same status/group mix, same messy value ranges (missing durations,
"fremd" markers, free-text locations, simulated calls), invented devices,
buildings and staff.

    python scripts/generate_synthetic_data.py --rows 60000 --seed 42

Nothing here is taken from the real data set.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RAW_COLUMNS = [
    "Wartungsplan",
    "Bezeichnung technisches Objekt",
    "Abrufstatus",
    "Equipment",
    "Status neu",
    "Technikergruppe",
    "Standort",
    "Art",
    "ILA",
    "WPlan-Beschreibung",
    "Plandatum",
    "Bautyp",
    "Durchschnittsdauer neu",
    "Standort.1",
]

TEAMS = {
    "M-0100": 2,   # laboratory equipment
    "M-0200": 2,   # dialysis
    "M-0300": 5,   # imaging
    "M-0400": 2,   # endoscopy
    "M-0500": 5,   # ward equipment (largest device population)
    "M-0600": 2,   # operating theatre
    "M-0700": 3,   # intensive care
    "M-1000": 1,   # research devices
}
# Share of the workload per team - mirrors the real, very uneven device mix.
TEAM_WEIGHTS = np.array([0.12, 0.09, 0.21, 0.13, 0.25, 0.10, 0.08, 0.02])

EXTERNAL_GROUPS = ["MEDT-FRE", "M-ISM", "M-IM"]

ACTIVITY_CODES = {
    "DGV": "DGUV V3",
    "INP": "Inspektion",
    "KAL": "Kalibrierung",
    "PEI": "Eichung",
    "PKO": "Konstanzprüfung",
    "PMK": "Messtechnische Kontrolle",
    "PSK": "Sicherheitstechnische Kontrolle",
    "PSS": "Strahlenschutzprüfung",
    "VAL": "Validierung",
    "WAR": "Wartung",
    "CTD": "CTDI Messung",
    "MON": "Garantieabnahme",
    "PSR": "Prüfung gemäß StrSchV (Röntgen)",
    "INS": "Inspektion",
}
ACTIVITY_WEIGHTS = np.array(
    [0.10, 0.08, 0.05, 0.02, 0.06, 0.14, 0.16, 0.03, 0.03, 0.22, 0.02, 0.02, 0.04, 0.03]
)

DEVICE_TYPES = [
    "Infusionspumpe", "Spritzenpumpe", "Beatmungsgerät", "Defibrillator",
    "Patientenmonitor", "EKG-Gerät", "Ultraschallgerät", "Röntgenanlage",
    "CT-Scanner", "MRT-Anlage", "Dialysegerät", "Endoskop-Turm",
    "OP-Tisch", "OP-Leuchte", "Narkosegerät", "Blutgasanalysator",
    "Zentrifuge, Labor", "Spülmaschine, Labor", "Autoklav", "Inkubator",
    "Absaugpumpe", "Blutdruckmessgerät", "Wärmetherapiegerät", "Perfusor",
]

STATUSES = ["EEGB", "EHEQ", "EEGB INAK", "EFRE INAK", "EHEQ INAK", "EFRE"]
STATUS_WEIGHTS = np.array([0.58, 0.06, 0.09, 0.12, 0.02, 0.01])
STATUS_WEIGHTS = STATUS_WEIGHTS / STATUS_WEIGHTS.sum()

CALL_STATUSES = ["Terminierung", "Zusatztermine (Simulation)", "Abgerufen"]

BUILDINGS = [f"B{n:02d}" for n in range(1, 19)]
FLOOR_LABELS = ["EG", "1. OG", "2. OG", "3. OG", "UG", "4. OG"]


def working_days(start: date, end: date) -> list[pd.Timestamp]:
    """Mon-Fri minus a plausible set of German public holidays."""
    days = pd.bdate_range(start, end)
    holidays = set()
    for year in range(start.year, end.year + 1):
        holidays.update(
            pd.Timestamp(d)
            for d in [
                f"{year}-01-01", f"{year}-05-01", f"{year}-10-03",
                f"{year}-12-24", f"{year}-12-25", f"{year}-12-26", f"{year}-12-31",
            ]
        )
    return [d for d in days if d not in holidays]


def make_raw_sheet(rng: np.random.Generator, rows: int, start: date, end: date) -> pd.DataFrame:
    n_devices = max(400, rows // 3)
    device_ids = rng.integers(1_000_000, 1_999_999, size=n_devices)
    device_team = rng.choice(list(TEAMS), size=n_devices, p=TEAM_WEIGHTS / TEAM_WEIGHTS.sum())
    device_type = rng.choice(DEVICE_TYPES, size=n_devices)
    device_building = rng.choice(BUILDINGS, size=n_devices)
    device_floor = rng.choice(FLOOR_LABELS, size=n_devices)
    # A device's nominal service time is a property of the device, not of the call.
    device_duration = np.round(rng.gamma(shape=1.4, scale=0.30, size=n_devices) + 0.2, 1)

    idx = rng.integers(0, n_devices, size=rows)
    horizon_days = (end - start).days

    # Some calls belong to the external service provider.
    group = device_team[idx].astype(object)
    external_mask = rng.random(rows) < 0.14
    group[external_mask] = rng.choice(EXTERNAL_GROUPS, size=external_mask.sum())

    activity = rng.choice(list(ACTIVITY_CODES), size=rows, p=ACTIVITY_WEIGHTS / ACTIVITY_WEIGHTS.sum())
    duration = device_duration[idx].astype(object)

    # Real-world messiness reproduced on purpose:
    missing = rng.random(rows) < 0.18            # duration never maintained in SAP
    zero = rng.random(rows) < 0.04               # maintained as 0
    fremd = external_mask & (rng.random(rows) < 0.5)  # marked as external work
    duration[missing] = np.nan
    duration[zero] = 0
    duration[fremd] = "fremd"

    # Location free text: two thirds carry a floor, one third only a building.
    building = device_building[idx]
    floor = device_floor[idx]
    with_floor = rng.random(rows) < 0.66
    location = np.where(with_floor, [f"{b}, {f}" for b, f in zip(building, floor)], building)

    due = [
        pd.Timestamp(start) + pd.Timedelta(days=int(d))
        for d in rng.integers(0, horizon_days, size=rows)
    ]

    equipment = device_ids[idx]
    frame = pd.DataFrame(
        {
            "Wartungsplan": 40000 + (idx % 9000),
            "Bezeichnung technisches Objekt": device_type[idx],
            "Abrufstatus": rng.choice(CALL_STATUSES, size=rows, p=[0.55, 0.35, 0.10]),
            "Equipment": equipment,
            "Status neu": rng.choice(STATUSES, size=rows, p=STATUS_WEIGHTS),
            "Technikergruppe": group,
            "Standort": building,
            "Art": rng.choice(["ZM01", "ZM02", "ZM03"], size=rows),
            "ILA": activity,
            "WPlan-Beschreibung": [f"{e} - {ACTIVITY_CODES[a]}" for e, a in zip(equipment, activity)],
            "Plandatum": due,
            "Bautyp": rng.choice(["A", "B", "C", None], size=rows),
            "Durchschnittsdauer neu": duration,
            "Standort.1": location,
        }
    )
    # A few rows without a group at all - exactly as in the real export.
    frame.loc[rng.random(rows) < 0.03, "Technikergruppe"] = np.nan
    return frame[RAW_COLUMNS]


def make_reference_sheet(rng: np.random.Generator, start: date, end: date) -> pd.DataFrame:
    technicians, team_of = [], []
    counter = 1
    for team, size in TEAMS.items():
        for _ in range(size):
            technicians.append(f"User{counter}")
            team_of.append(team)
            counter += 1

    # Two-week absences, roughly three per technician over the horizon.
    absence_rows = []
    for technician in technicians:
        for _ in range(rng.integers(2, 5)):
            offset = int(rng.integers(0, max(1, (end - start).days - 20)))
            begin = pd.Timestamp(start) + pd.Timedelta(days=offset)
            absence_rows.append((technician, begin, begin + pd.Timedelta(days=14)))

    days = working_days(start, end)
    weekday_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]

    blocks = {
        "Team": list(TEAMS),
        "Anzahl Mitarbeiter": list(TEAMS.values()),
        "Team.1": team_of,
        "Mitarbeiter": technicians,
        "Urlaub / Langzeitausfall": [r[0] for r in absence_rows],
        "Von": [r[1] for r in absence_rows],
        "Bis": [r[2] for r in absence_rows],
        "Datum": days,
        "Wochentag": [weekday_names[d.weekday()] for d in days],
        "Gruppe": list(TEAMS),
        "Wartungszeiten": [4.0] * len(TEAMS),
        "Vorsprung": [30],
        "Abkürzungen": list(ACTIVITY_CODES),
        "Erklärung": list(ACTIVITY_CODES.values()),
        "Start": [pd.Timestamp(start)],
        "Ende": [pd.Timestamp(end)],
    }
    height = max(len(v) for v in blocks.values())
    padded = {k: list(v) + [None] * (height - len(v)) for k, v in blocks.items()}
    return pd.DataFrame(padded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=45000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-12-31")
    parser.add_argument("--output", default="data/raw/maintenance_export.xlsx")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    raw = make_raw_sheet(rng, args.rows, start, end)
    reference = make_reference_sheet(rng, start, end)

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        raw.to_excel(writer, sheet_name="Rohdaten", index=False)
        reference.to_excel(writer, sheet_name="Zusatdaten", index=False)

    print(f"wrote {len(raw):,} maintenance calls to {path}")


if __name__ == "__main__":
    main()
