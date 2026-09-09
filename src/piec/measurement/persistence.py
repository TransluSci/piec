"""
Handle-based CSV writer, reader, and schema/unit metadata serialization.

Fulfills Checkpoint 11a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- One-row metadata, blank separator line, and data table CSV layout (Section 7.1 & 8.1);
- Single open UTF-8 text handle writer with flush and fsync (Section 8.1 Rule 3 & 4);
- Exact JSON unit round-trips via column_units_json (Section 7.1);
- Standard scalar metadata schema verification (Section 7.1);
- Non-ASCII metadata and canonical units preservation.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple, Union

import pandas as pd


STANDARD_SCHEMAS: Dict[str, int] = {
    "iv_sweep": 1,
    "moke": 1,
    "discrete_waveform": 1,
    "hysteresis": 1,
    "three_pulse_pund": 1,
    "amr": 1,
}

REQUIRED_METADATA_FIELDS: Tuple[str, ...] = (
    "measurement_schema",
    "measurement_schema_version",
    "run_id",
    "outcome",
    "partial",
    "save_requested",
    "column_units_json",
)

STANDARD_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "iv_sweep": ("voltage", "current"),
    "moke": (
        "time",
        "cycle",
        "point",
        "direction",
        "source_output",
        "field_calibrated",
        "detector_voltage",
    ),
    "discrete_waveform": ("time", "voltage"),
    "hysteresis": (
        "time",
        "voltage",
        "current",
        "polarization",
        "applied_voltage",
    ),
    "three_pulse_pund": (
        "time",
        "voltage",
        "current",
        "polarization",
        "polarization_p_hat",
        "polarization_p_star",
        "polarization_p_hat_r",
        "polarization_p_star_r",
        "delta_polarization",
        "applied_voltage",
    ),
    "amr": ("angle", "field", "x", "y"),
}


def serialize_column_units(column_units: Mapping[str, Optional[str]]) -> str:
    """
    Serializes a column-to-unit mapping into sorted compact JSON (Section 7.1).

    Values must be canonical unit strings (e.g. 'V', 'A', 's', 'deg') or None
    (serialized as JSON null) for unitless indices or categories.
    """
    cleaned: Dict[str, Optional[str]] = {}
    for col, unit in column_units.items():
        if unit is not None and not isinstance(unit, str):
            raise TypeError(
                f"Unit for column '{col}' must be a string or None, got {type(unit).__name__}: {unit!r}"
            )
        cleaned[str(col)] = str(unit) if unit is not None else None

    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"))


def deserialize_column_units(json_str: str) -> Dict[str, Optional[str]]:
    """
    Deserializes a JSON string back into a dictionary mapping column names to units (or None).
    """
    if not isinstance(json_str, str):
        raise TypeError(f"Expected JSON string, got {type(json_str).__name__}")
    parsed = json.loads(json_str)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return {str(k): (str(v) if v is not None else None) for k, v in parsed.items()}


def validate_column_units(
    data_columns: Sequence[str],
    column_units: Mapping[str, Optional[str]],
) -> Dict[str, Optional[str]]:
    """
    Validates that column_units contains an entry for every saved data column (Section 7.1).

    Raises:
        ValueError: If any column is missing a declared unit.
    """
    data_cols_set = set(data_columns)
    unit_cols_set = set(column_units.keys())

    missing = data_cols_set - unit_cols_set
    if missing:
        raise ValueError(
            f"Missing unit specification for data column(s): {sorted(missing)}"
        )

    # Return mapped dict strictly for the saved data columns in original order
    return {col: column_units.get(col) for col in data_columns}


def validate_metadata(
    metadata: Union[Mapping[str, Any], pd.DataFrame],
    *,
    strict_schema: bool = False,
) -> Dict[str, Any]:
    """
    Validates that metadata contains all REQUIRED_METADATA_FIELDS (Section 7.1).

    If strict_schema is True, also verifies that measurement_schema is one of STANDARD_SCHEMAS
    and measurement_schema_version matches the expected version.

    Returns:
        Dictionary of validated metadata fields.
    """
    if isinstance(metadata, pd.DataFrame):
        if len(metadata) == 0:
            raise ValueError("Metadata DataFrame is empty")
        meta_dict = metadata.iloc[0].to_dict()
    elif isinstance(metadata, Mapping):
        meta_dict = dict(metadata)
    else:
        raise TypeError(f"metadata must be a Mapping or DataFrame, got {type(metadata).__name__}")

    missing = [f for f in REQUIRED_METADATA_FIELDS if f not in meta_dict or pd.isna(meta_dict[f])]
    if missing:
        raise ValueError(f"Missing required metadata field(s): {missing}")

    if strict_schema:
        schema = meta_dict.get("measurement_schema")
        if schema not in STANDARD_SCHEMAS:
            raise ValueError(
                f"Unknown measurement_schema '{schema}'. Must be one of {sorted(STANDARD_SCHEMAS.keys())}"
            )
        expected_version = STANDARD_SCHEMAS[schema]
        version = meta_dict.get("measurement_schema_version")
        if version != expected_version:
            raise ValueError(
                f"Invalid measurement_schema_version {version} for schema '{schema}'. Expected {expected_version}."
            )

    return meta_dict


def write_measurement_handle(
    handle: TextIO,
    metadata: Union[Mapping[str, Any], pd.DataFrame],
    data: pd.DataFrame,
    *,
    column_units: Optional[Mapping[str, Optional[str]]] = None,
    sync: bool = True,
) -> None:
    """
    Writes metadata, blank separator line, and data table through a single UTF-8 text handle (Section 8.1 Rule 3 & 4).

    Flushes and fsyncs the handle to disk before return.

    Parameters:
        handle: An open writable text file handle (e.g. opened with encoding='utf-8', newline='').
        metadata: Scalar metadata dictionary or 1xN DataFrame.
        data: Measurement DataFrame to write below metadata.
        column_units: Optional mapping of column names to units. If provided, ensures
                      `column_units_json` is serialized and present in metadata.
        sync: If True, calls os.fsync on handle.fileno() if supported.
    """
    if not hasattr(handle, "write"):
        raise TypeError(f"handle must be a writable text stream, got {type(handle).__name__}")

    # Prepare metadata DataFrame
    if isinstance(metadata, pd.DataFrame):
        if len(metadata) != 1:
            raise ValueError(f"Metadata DataFrame must have exactly 1 row, got {len(metadata)}")
        meta_df = metadata.copy()
        if column_units is not None:
            validated_units = validate_column_units(data.columns, column_units)
            units_json = serialize_column_units(validated_units)
            if "column_units_json" in meta_df.columns:
                existing_units_json = meta_df.iloc[0]["column_units_json"]
                if pd.notna(existing_units_json):
                    existing_map = deserialize_column_units(str(existing_units_json))
                    if existing_map != validated_units:
                        raise ValueError(
                            f"Conflicting column_units provided: argument specifies {validated_units}, "
                            f"but metadata already contains {existing_map}"
                        )
            else:
                meta_df["column_units_json"] = units_json
    elif isinstance(metadata, Mapping):
        meta_dict = dict(metadata)
        if column_units is not None:
            validated_units = validate_column_units(data.columns, column_units)
            units_json = serialize_column_units(validated_units)
            if "column_units_json" in meta_dict:
                existing_units_json = meta_dict["column_units_json"]
                if pd.notna(existing_units_json):
                    existing_map = deserialize_column_units(str(existing_units_json))
                    if existing_map != validated_units:
                        raise ValueError(
                            f"Conflicting column_units provided: argument specifies {validated_units}, "
                            f"but metadata already contains {existing_map}"
                        )
            else:
                meta_dict["column_units_json"] = units_json
        # Convert any dict/list values to JSON strings
        for k, v in list(meta_dict.items()):
            if isinstance(v, (dict, list)):
                meta_dict[k] = json.dumps(v, sort_keys=True)
        meta_df = pd.DataFrame([meta_dict])
    else:
        raise TypeError(
            f"metadata must be a Mapping or DataFrame, got {type(metadata).__name__}"
        )

    # Validate column units if column_units_json is present
    if "column_units_json" in meta_df.columns:
        raw_units_json = meta_df.iloc[0]["column_units_json"]
        if pd.notna(raw_units_json):
            units_map = deserialize_column_units(str(raw_units_json))
            # Validate every data column has an entry
            missing = set(data.columns) - set(units_map.keys())
            if missing:
                raise ValueError(
                    f"column_units_json is missing entries for columns: {sorted(missing)}"
                )
            extra = set(units_map.keys()) - set(data.columns)
            if extra and len(data.columns) > 0:
                raise ValueError(
                    f"column_units_json contains extraneous columns not in data: {sorted(extra)}"
                )

    # 1. Write metadata (1 row with header)
    meta_df.to_csv(handle, index=False, header=True, lineterminator="\n")

    # 2. Write blank line separator (Section 7.1)
    handle.write("\n")

    # 3. Write data table
    data.to_csv(handle, index=False, header=True, lineterminator="\n")

    # 4. Flush handle
    handle.flush()

    # 5. fsync handle to disk if requested and supported
    if sync:
        try:
            fileno = handle.fileno()
            os.fsync(fileno)
        except (AttributeError, io.UnsupportedOperation, OSError):
            pass


def write_measurement_csv(
    path: Union[str, Path],
    metadata: Union[Mapping[str, Any], pd.DataFrame],
    data: pd.DataFrame,
    *,
    column_units: Optional[Mapping[str, Optional[str]]] = None,
    sync: bool = True,
    encoding: str = "utf-8",
) -> Path:
    """
    Convenience function writing a measurement CSV file through a single text handle (Section 8.1).

    Opens the file once, writes metadata, blank line, and data, flushes and fsyncs, then closes.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding=encoding, newline="") as handle:
        write_measurement_handle(
            handle,
            metadata,
            data,
            column_units=column_units,
            sync=sync,
        )
    return target


def read_measurement_csv(
    source: Union[str, Path, TextIO],
    *,
    encoding: str = "utf-8",
) -> Tuple[Dict[str, Any], pd.DataFrame, Dict[str, Optional[str]]]:
    """
    Reads a standard PIEC measurement CSV file (Section 7.1).

    Parses the 1-row metadata, skips the blank separator line, parses the data table,
    and unpacks `column_units_json` into a dictionary.

    Returns:
        (metadata_dict, data_df, column_units_dict)
    """
    if isinstance(source, (str, Path)):
        with open(source, "r", encoding=encoding) as f:
            content = f.read()
    elif hasattr(source, "read"):
        content = source.read()
    else:
        raise TypeError(f"source must be a path or text stream, got {type(source).__name__}")

    lines = content.splitlines()
    if len(lines) < 3:
        raise ValueError(
            f"Measurement CSV must contain at least metadata row and data header (got {len(lines)} lines)"
        )

    # Line 2 must be blank separator
    if lines[2].strip() != "":
        raise ValueError(
            f"Line 3 (index 2) of measurement CSV must be a blank separator line, got: {lines[2]!r}"
        )

    # Read metadata using StringIO for the first two lines (header + 1 row)
    meta_text = "\n".join(lines[:2])
    meta_df = pd.read_csv(io.StringIO(meta_text))
    metadata: Dict[str, Any] = meta_df.iloc[0].to_dict()

    # Locate data table start (after blank line)
    data_start = 2
    while data_start < len(lines) and not lines[data_start].strip():
        data_start += 1

    if data_start < len(lines):
        data_text = "\n".join(lines[data_start:])
        data_df = pd.read_csv(io.StringIO(data_text))
    else:
        data_df = pd.DataFrame()

    # Extract column units if present
    column_units: Dict[str, Optional[str]] = {}
    if "column_units_json" in metadata and pd.notna(metadata["column_units_json"]):
        column_units = deserialize_column_units(str(metadata["column_units_json"]))

    return metadata, data_df, column_units
