from __future__ import annotations

import pandas as pd
import pytest

from maintenance_scheduler.config import Config
from maintenance_scheduler.data.preprocessing import (
    building_of,
    normalise_duration,
    split_location,
)


@pytest.fixture(scope="module")
def config() -> Config:
    return Config.load("config/config.yaml")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("B12, 3. OG", "B12|3. OG"),
        ("B12", "B12"),
        ("  B07 ,  EG ", "B07|EG"),
        ("B03, EG, Raum 2", "B03|EG"),
    ],
)
def test_split_location(raw, expected):
    assert split_location(raw) == expected


def test_building_of():
    assert building_of("B12|3. OG") == "B12"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2.5, 2.5),
        (0, 0.5),          # zero means "not maintained", not "free"
        (None, 0.5),       # missing means "not maintained"
        (float("nan"), 0.5),
        ("fremd", 0.0),    # external provider consumes no internal capacity
        ("Fremd", 0.0),
        ("unparsable", 0.5),
    ],
)
def test_normalise_duration(raw, expected, config):
    assert normalise_duration(raw, config) == expected
