"""
Unit and regression tests for FieldCalibration.

Verifies:
- Direct-output calibration without extra gain factors.
- Monotonicity checks, nonlinear and reversed calibration support.
- Rejection of invalid, out-of-bounds, ambiguous, or NaN points.
- Extrapolation prevention.
- Immutability of calibration points array accessor.
- CSV serialization, round-trip loading, overwrite protection, and unit validation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration


def test_calibration_uses_direct_output_without_another_gain():
    curve = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (1.0, 100.0), (5.0, 500.0)], name="example")
    assert curve.field_at_output(5.0) == 500.0
    assert curve.field_at_output(0.5) == 50.0
    assert curve.output_at_field(500.0) == 5.0
    assert curve.output_at_field([-250.0, 100.0]) == pytest.approx([-2.5, 1.0])


def test_nonlinear_and_reversed_calibration():
    curve = FieldCalibration([(5.0, -600.0), (0.0, 0.0), (1.0, -80.0)])
    assert curve.field_at_output(3.0) == -340.0
    assert curve.output_at_field(-340.0) == 3.0


@pytest.mark.parametrize(
    "points",
    [[], [(1.0, 100.0)], [(1.0, 100.0), (1.0, 110.0)], [(0.0, 0.0), (1.0, np.nan)]],
)
def test_invalid_calibration_points_are_rejected(points):
    with pytest.raises(ValueError):
        FieldCalibration(points)


def test_no_extrapolation_and_no_ambiguous_inverse():
    curve_mono = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)])
    with pytest.raises(ValueError, match="outside"):
        curve_mono.field_at_output(5.01)
    with pytest.raises(ValueError, match="outside"):
        curve_mono.output_at_field(501.0)

    curve_non_monotonic = FieldCalibration([(0.0, 0.0), (1.0, 2.0), (2.0, 1.0)])
    assert curve_non_monotonic.field_at_output(1.5) == 1.5
    with pytest.raises(ValueError, match="monotonic"):
        curve_non_monotonic.output_at_field(1.0)


def test_calibration_csv_round_trip_and_no_overwrite(tmp_path):
    path = tmp_path / "calibration.csv"
    curve = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)], name="test_cal")
    curve.save_csv(path)
    loaded = FieldCalibration.load_csv(path)
    assert loaded.to_dict() == curve.to_dict()
    with pytest.raises(FileExistsError):
        curve.save_csv(path)


def test_calibration_points_are_not_mutable_through_accessor():
    curve = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)])
    points = curve.points
    points[:, 1] = 999.0
    assert curve.field_at_output(5.0) == 500.0


def test_csv_loader_accepts_manual_table_without_name(tmp_path):
    path = tmp_path / "manual.csv"
    pd.DataFrame({
        "source_output": [0.0, 1.0, 5.0],
        "field": [0.0, 98.0, 505.0],
        "output_unit": ["V"] * 3,
        "field_unit": ["Oe"] * 3,
    }).to_csv(path, index=False)
    curve = FieldCalibration.load_csv(path)
    assert curve.field_at_output(1.0) == 98.0
    assert curve.name == ""


def test_csv_loader_rejects_mixed_units(tmp_path):
    path = tmp_path / "mixed.csv"
    pd.DataFrame({
        "source_output": [0.0, 1.0],
        "field": [0.0, 100.0],
        "output_unit": ["V", "A"],
        "field_unit": ["Oe", "Oe"],
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="consistent output_unit"):
        FieldCalibration.load_csv(path)
