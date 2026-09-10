"""
Reusable characterization and compatibility test harness utilities for PIEC measurements.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

MANIFEST_PATH = Path(__file__).parent / "manifest.json"


def load_manifest() -> dict[str, Any]:
    """Load the machine-readable compatibility manifest."""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_manifest_family(family_name: str) -> dict[str, Any]:
    """Retrieve specifications for a single measurement family from the manifest."""
    manifest = load_manifest()
    families = manifest.get("families", {})
    if family_name not in families:
        raise KeyError(f"Family {family_name!r} not found in manifest. Available: {list(families.keys())}")
    return families[family_name]


def get_family_reference_observations(family_name: str) -> dict[str, Any]:
    """Retrieve reference observations for a family from the manifest."""
    spec = get_manifest_family(family_name)
    return spec.get("reference_observations", spec)


def get_family_target_contract(family_name: str) -> dict[str, Any]:
    """Retrieve target contract specifications for a family from the manifest."""
    spec = get_manifest_family(family_name)
    if "target_contract" not in spec:
        raise KeyError(f"Family {family_name!r} does not have a target_contract in manifest")
    return spec["target_contract"]


def get_old_to_new_column_mapping(family_name: str) -> dict[str, str]:
    """Retrieve the explicit old-to-new column mapping for a family."""
    spec = get_manifest_family(family_name)
    return spec.get("old_to_new_column_mapping", {})


def get_migrated_families() -> list[str]:
    """Retrieve the list of families that have completed their vertical slice migration."""
    manifest = load_manifest()
    return manifest.get("migrated_families", [])


def is_family_migrated(family_name: str) -> bool:
    """Return True if the specified family has completed vertical slice migration."""
    return family_name in get_migrated_families()


def _assert_parameters_match(
    target: str,
    actual_params: Sequence[inspect.Parameter],
    expected_parameters: Sequence[dict[str, Any]],
    allowed_keyword_only: dict[str, Any] | None = None,
) -> None:
    """Preserve the legacy prefix; permit only explicitly approved optional keywords."""
    expected_names = [p["name"] for p in expected_parameters]
    legacy_params = actual_params[:len(expected_parameters)]
    assert [p.name for p in legacy_params] == expected_names, (
        f"Parameter order/names mismatch for {target}: "
        f"{[p.name for p in legacy_params]} != {expected_names}"
    )
    for actual, expected in zip(legacy_params, expected_parameters):
        assert actual.kind.name == expected["kind"], (
            f"Parameter {actual.name} kind mismatch on {target}"
        )
        expected_default = expected["default"]
        if expected_default == "__NO_DEFAULT__":
            assert actual.default is inspect.Parameter.empty, (
                f"Parameter {actual.name} on {target} must remain required"
            )
        else:
            assert actual.default == expected_default, (
                f"Parameter {actual.name} default mismatch on {target}: "
                f"{actual.default!r} != {expected_default!r}"
            )

    allowed = allowed_keyword_only or {}
    for extra in actual_params[len(expected_parameters):]:
        assert extra.name in allowed, f"Unapproved parameter {extra.name} on {target}"
        assert extra.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"New parameter {extra.name} on {target} must be keyword-only"
        )
        assert extra.default is not inspect.Parameter.empty, (
            f"New parameter {extra.name} on {target} must be optional"
        )
        assert extra.default == allowed[extra.name], (
            f"New parameter {extra.name} default mismatch on {target}"
        )


def assert_constructor_signature_matches(
    cls: type,
    expected_parameters: Sequence[dict[str, Any]],
    *,
    allowed_keyword_only: dict[str, Any] | None = None,
) -> None:
    """Check legacy constructor parameters and explicitly approved additions."""
    actual = [p for p in inspect.signature(cls.__init__).parameters.values() if p.name != "self"]
    _assert_parameters_match(
        f"{cls.__name__}.__init__", actual, expected_parameters, allowed_keyword_only,
    )


def assert_public_methods_match(
    cls: type,
    expected_methods: dict[str, dict[str, Any]],
    *,
    allowed_keyword_only: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Check legacy methods; allow only per-method approved optional keywords."""
    for method_name, method_spec in expected_methods.items():
        method = getattr(cls, method_name, None)
        assert callable(method), f"Class {cls.__name__} missing method {method_name!r}"
        actual = [p for p in inspect.signature(method).parameters.values() if p.name != "self"]
        _assert_parameters_match(
            f"{cls.__name__}.{method_name}", actual, method_spec.get("parameters", []),
            (allowed_keyword_only or {}).get(method_name),
        )


def assert_public_properties_match(
    cls: type,
    expected_properties: Sequence[str],
) -> None:
    """Verify that expected properties exist on the class."""
    for prop in expected_properties:
        assert hasattr(cls, prop), f"Class {cls.__name__} missing property {prop!r}"
        attr = getattr(cls, prop)
        assert isinstance(attr, property), f"Attribute {prop!r} on {cls.__name__} is not a property"


def assert_piec_csv_layout(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Verify that a CSV file strictly obeys PIEC's one-row metadata / blank line / data table layout.

    Returns (metadata_df, data_df).
    """
    file_path = Path(path)
    assert file_path.is_file(), f"File {file_path} does not exist"

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) >= 3, f"CSV file {file_path} too short to be valid PIEC standard (has {len(lines)} lines)"
    assert lines[2].strip() == "", f"Line 3 (index 2) of {file_path} must be a blank separator line, got: {lines[2]!r}"

    # Verify standard reader parses without error
    from piec.analysis.utilities import standard_csv_to_metadata_and_data
    metadata, data = standard_csv_to_metadata_and_data(str(file_path))

    assert isinstance(metadata, pd.DataFrame), "Metadata must be a DataFrame"
    assert len(metadata) == 1, f"Metadata must have exactly 1 row, got {len(metadata)}"
    assert isinstance(data, pd.DataFrame), "Data must be a DataFrame"

    return metadata, data


def assert_data_columns_match(
    df: pd.DataFrame,
    expected_columns: Sequence[str],
    exact_order: bool = True,
) -> None:
    """Verify DataFrame column names and ordering."""
    actual = list(df.columns)
    if exact_order:
        assert actual == list(expected_columns), (
            f"DataFrame columns/order mismatch:\n"
            f"  Actual:   {actual}\n"
            f"  Expected: {list(expected_columns)}"
        )
    else:
        missing = set(expected_columns) - set(actual)
        assert not missing, f"Missing required columns: {missing}"


def normalize_metadata_for_comparison(
    metadata_df: pd.DataFrame,
    volatile_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Extract a normalized dict of metadata parameters, excluding volatile runtime facts
    like timestamps, file paths, run IDs, and hardware identification strings.
    """
    default_volatile = {
        "timestamp", "run_id", "filename", "sourcemeter", "dmm",
        "lockin", "arduino", "calibrator", "osc", "awg",
    }
    exclude = default_volatile | set(volatile_keys or [])

    row = metadata_df.iloc[0].to_dict()
    return {k: v for k, v in row.items() if k not in exclude}


def assert_golden_csv_matches(
    actual_path: str | Path,
    golden_path: str | Path,
    *,
    volatile_metadata_keys: Sequence[str] | None = None,
    time_columns: Sequence[str] = (),
    float_tolerance: float = 1e-5,
    time_tolerance: float = 1e-12,
) -> None:
    """
    Assert that an actual measurement CSV file matches a reference golden CSV.

    Verifies:
    1. Both files strictly follow PIEC 1-row metadata, blank separator, data table format.
    2. Non-volatile metadata parameters match exactly (or parse equivalent JSON where applicable).
    3. Data columns and ordering match exactly.
    4. Data values, including waveform time, match within numerical tolerance.
    5. Explicitly opted-in elapsed-clock columns are finite, non-negative and monotonic.
    """
    import numpy as np

    act_meta, act_data = assert_piec_csv_layout(actual_path)
    gold_meta, gold_data = assert_piec_csv_layout(golden_path)

    # 1. Compare normalized metadata
    default_volatile = {
        "timestamp", "run_id", "filename", "save_dir", "sourcemeter", "dmm",
        "lockin", "arduino", "calibrator", "osc", "awg",
    }
    volatile = default_volatile | set(volatile_metadata_keys or [])

    act_norm = {k: v for k, v in act_meta.iloc[0].to_dict().items() if k not in volatile}
    gold_norm = {k: v for k, v in gold_meta.iloc[0].to_dict().items() if k not in volatile}

    assert set(act_norm.keys()) == set(gold_norm.keys()), (
        f"Metadata keys mismatch:\n"
        f"  Actual:   {sorted(act_norm.keys())}\n"
        f"  Golden:   {sorted(gold_norm.keys())}"
    )

    for k in gold_norm:
        act_v = act_norm[k]
        gold_v = gold_norm[k]
        if pd.isna(act_v) and pd.isna(gold_v):
            continue
        # Check if string is JSON
        if isinstance(gold_v, str) and (gold_v.startswith("{") or gold_v.startswith("[")):
            try:
                assert json.loads(act_v) == json.loads(gold_v), f"Metadata JSON mismatch on {k}: {act_v} != {gold_v}"
                continue
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(gold_v, float):
            assert abs(float(act_v) - float(gold_v)) <= float_tolerance, (
                f"Metadata float mismatch on {k}: {act_v} != {gold_v}"
            )
        else:
            assert str(act_v) == str(gold_v), f"Metadata value mismatch on {k}: {act_v!r} != {gold_v!r}"

    # 2. Compare data columns and ordering
    assert_data_columns_match(act_data, list(gold_data.columns), exact_order=True)
    assert len(act_data) == len(gold_data), f"Data row count mismatch: {len(act_data)} != {len(gold_data)}"

    # 3. Compare data values
    for col in gold_data.columns:
        if col in time_columns:
            times = act_data[col].to_numpy(dtype=float)
            assert np.all(np.isfinite(times)), f"Non-finite values found in {col}"
            assert np.all(times >= 0.0), f"Negative values found in {col}"
            if len(times) > 1:
                assert np.all(np.diff(times) >= -1e-9), f"Time values in {col} must be monotonically non-decreasing"
        else:
            act_vals = act_data[col].to_numpy()
            gold_vals = gold_data[col].to_numpy()
            if np.issubdtype(gold_vals.dtype, np.number):
                atol = time_tolerance if col in ("time", "time (s)", "field_time", "field_time (s)") else float_tolerance
                assert np.allclose(act_vals.astype(float), gold_vals.astype(float), atol=atol, rtol=1e-7), (
                    f"Data mismatch in column {col!r}:\n"
                    f"  Actual: {act_vals}\n"
                    f"  Golden: {gold_vals}"
                )
            else:
                assert (act_vals == gold_vals).all(), f"Data mismatch in column {col!r}: {act_vals} != {gold_vals}"


def assert_numerical_data_matches_reference(
    actual_data: pd.DataFrame,
    reference_data: pd.DataFrame,
    family_name: str,
    *,
    float_tolerance: float = 1e-5,
    relative_tolerance: float = 1e-7,
    view: str = "processed",
    time_tolerance: float = 1e-12,
) -> None:
    """Compare every required column, resolving reference/target names explicitly.

    Raw FE views must select view='raw'. Optional columns must appear on both
    sides or neither. Only manifest-declared elapsed clocks may vary; waveform
    times are compared numerically, including valid negative pre-trigger times.
    """
    import re
    import numpy as np

    assert actual_data.columns.is_unique and reference_data.columns.is_unique, "Duplicate columns"
    assert len(actual_data) == len(reference_data), "Row count mismatch"
    assert view in ("raw", "processed"), "Unknown comparison view"
    spec = get_manifest_family(family_name)
    target = spec["target_contract"]
    required = target.get("raw_columns", target["ordered_columns"]) if view == "raw" else target["ordered_columns"]
    optional = target.get("optional_columns", [])
    mapping = spec["old_to_new_column_mapping"]
    elapsed = set(spec.get("reference_time_policy", {}).get("elapsed_columns", []))

    def resolve(frame, column):
        patterns = [column] + [old for old, new in mapping.items() if new == column]
        matches = set()
        for pattern in patterns:
            # Unit placeholders match a single explicit header, never silently
            # choose between two differently-unit-labelled columns.
            regex = re.escape(pattern)
            regex = re.sub(r"\\\{[a-z_]+\\\}", r"[^()]+", regex)
            matches.update(c for c in frame.columns if re.fullmatch(regex, c))
        assert len(matches) <= 1, f"Ambiguous columns for {column}: {matches}"
        return next(iter(matches), None)

    for column in list(required) + list(optional):
        act_col = resolve(actual_data, column)
        ref_col = resolve(reference_data, column)
        if column in optional and act_col is None and ref_col is None:
            continue
        assert act_col is not None, f"Missing actual column: {column}"
        assert ref_col is not None, f"Missing reference column: {column}"
        actual = actual_data[act_col].to_numpy()
        reference = reference_data[ref_col].to_numpy()
        if column in elapsed:
            for values in (actual, reference):
                clock = values.astype(float)
                assert np.isfinite(clock).all(), f"Non-finite elapsed time: {column}"
                assert (clock >= 0).all(), f"Negative elapsed time: {column}"
                assert (np.diff(clock) >= 0).all(), f"Non-monotonic elapsed time: {column}"
        elif pd.api.types.is_numeric_dtype(actual.dtype) or pd.api.types.is_numeric_dtype(reference.dtype):
            atol = time_tolerance if column in ("time", "field_time") else float_tolerance
            assert np.allclose(actual.astype(float), reference.astype(float),
                               atol=atol, rtol=relative_tolerance), (
                f"Numerical mismatch in {family_name}: {ref_col} -> {act_col}"
            )
        else:
            assert (actual == reference).all(), f"Value mismatch in {column}"


def assert_family_interface(cls: type, family_name: str) -> None:
    """Select baseline observations or the new interface using migration status.

    This checks structural API obligations only. A migrated family's own tests
    must also execute fake-instrument runs to check DataFrame returns, schemas,
    constructor I/O and lifecycle safety.
    """
    if not is_family_migrated(family_name):
        ref = get_family_reference_observations(family_name)
        assert_constructor_signature_matches(cls, ref["constructor"]["parameters"])
        assert_public_methods_match(cls, ref["public_methods"], allowed_keyword_only={
            "run_experiment": {"on_update": None, "save": True, "save_partial": None},
        })
        assert_public_properties_match(cls, ref.get("properties", []))
        return

    target = get_family_target_contract(family_name)
    if target.get("contract_name") == "snapshot":
        fields = set(getattr(cls, "__dataclass_fields__", {}))
        fields.update(getattr(cls, "__annotations__", {}))
        for name in target["common_fields"]:
            assert name in fields or hasattr(cls, name), f"Missing snapshot field: {name}"
        return

    assert_public_methods_match(
        cls,
        target["method_signatures"],
        allowed_keyword_only={"run_experiment": {"token": None}},
    )
    dependencies = set(target["positional_dependencies"])
    for param in inspect.signature(cls.__init__).parameters.values():
        if param.name == "self":
            continue
        assert param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD), (
            "Target constructors must expose explicit parameters"
        )
        assert param.name not in ("arduino", "voltage_callibration"), "Obsolete constructor spelling"
        assert param.kind is inspect.Parameter.KEYWORD_ONLY or param.name in dependencies, (
            f"Measurement setting must be keyword-only: {param.name}"
        )
