"""
Handle-based CSV writer, reader, and schema/unit metadata serialization.

Fulfills Checkpoint 11a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- One-row metadata, blank separator line, and data table CSV layout (Section 7.1 & 8.1);
- Single open UTF-8 text handle writer with flush and fsync (Section 8.1 Rule 3 & 4);
- Exact JSON unit round-trips via column_units_json (Section 7.1);
- Standard scalar metadata schema verification (Section 7.1);
- Non-ASCII metadata and canonical units preservation.

Fulfills Checkpoint 11b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Atomic no-replace publication primitive (atomic_publish_no_replace) (Section 8.1 Rule 6 & 7);
- Rejection of pre-existing targets with FileExistsError without silent overwrite;
- Safe staging in destination directory via tempfile.mkstemp() (Section 8.1 Rule 2);
- Atomic write and publish helper (atomic_publish_measurement_csv);
- Preservation of staging files on collision/save failure for data recovery (Section 8.3);
- Strict mode failing clearly when atomic no-replace is unsupported, with opt-in collision-resistant fallback;
- NTFS atomic rename verified; opt-in SMB share support.
"""

from __future__ import annotations

import csv
import errno
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple, Union
import uuid

import pandas as pd


class AtomicPublishError(OSError):
    """Base exception for atomic publication failures."""


class UnsupportedFilesystemError(AtomicPublishError):
    """Raised when strict atomic no-replace publication is unsupported by the filesystem."""


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
    # Reject malformed units rather than quietly turning numbers/objects into labels.
    serialize_column_units(parsed)
    return parsed


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
        if len(metadata) != 1:
            raise ValueError("Metadata DataFrame must have exactly 1 row")
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


def _prepare_metadata(metadata, data, column_units):
    """Validate the complete CSV contract without touching a stream or path."""
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

    # Validate before the first write, including when no explicit units were supplied.
    validate_metadata(meta_df, strict_schema=True)
    if not data.columns.is_unique:
        raise ValueError("Data columns must be unique")

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
            if extra:
                raise ValueError(
                    f"column_units_json contains extraneous columns not in data: {sorted(extra)}"
                )

    return meta_df


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

    meta_df = _prepare_metadata(metadata, data, column_units)

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
        except (AttributeError, io.UnsupportedOperation):
            pass
        else:
            os.fsync(fileno)


def create_staging_file(
    destination_dir: Union[str, Path],
    *,
    prefix: str = ".staging-",
    suffix: str = ".tmp",
) -> Tuple[int, Path]:
    """
    Creates a temporary staging file in the destination directory (Section 8.1 Rule 2).

    Uses tempfile.mkstemp() to ensure exclusive creation in the destination directory,
    preventing cross-volume moves and handle-locking across renames on Windows.

    Returns:
        (file_descriptor, staging_path)
    """
    dest = Path(destination_dir)
    dest.mkdir(parents=True, exist_ok=True)
    fd, abs_path_str = tempfile.mkstemp(dir=dest, prefix=prefix, suffix=suffix)
    return fd, Path(abs_path_str)


def _collision_resistant_publish(staging: Path, target: Path) -> Path:
    """
    Opt-in non-strict fallback. Labeled collision-resistant, never collision-proof (Section 8.1 Rule 7).

    Redesigned around a hidden reservation marker and destination-local staging
    without exposing an incomplete or empty final CSV (Section 8.1 Rule 5 & 7).
    """
    if target.exists():
        raise FileExistsError(f"Target file already exists: {target}")

    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)

    # Deterministic hidden reservation marker derived from candidate target name (Section 8.1 Rule 5)
    marker = target_parent / f".{target.name}.res"

    # Claim candidate with exclusively created hidden marker
    try:
        with open(marker, "xb") as f:
            f.write(f"pid={os.getpid()}\n".encode("utf-8"))
    except FileExistsError as exc:
        raise FileExistsError(
            f"Target file is currently reserved or already exists: {target}"
        ) from exc

    dest_staging: Optional[Path] = None
    try:
        # Re-verify target existence after claiming reservation
        if target.exists():
            raise FileExistsError(f"Target file already exists: {target}")

        same_dir = False
        try:
            same_dir = staging.resolve().parent == target_parent.resolve()
        except (OSError, RuntimeError):
            pass

        if same_dir:
            file_to_publish = staging
        else:
            # Cross-volume / cross-directory: stage into a hidden temporary file in target_parent
            # so the final publication step is intra-volume.
            # Never write directly into target.csv before publication.
            fd, dest_staging = create_staging_file(
                target_parent, prefix=f".{target.name}-staging-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "wb") as dst, open(staging, "rb") as src:
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                    os.fsync(dst.fileno())
            except Exception:
                try:
                    dest_staging.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            file_to_publish = dest_staging

        # Intra-volume publish to target
        if os.name == "nt":
            # On Windows, os.rename fails with FileExistsError if target exists
            os.rename(str(file_to_publish), str(target))
        else:
            try:
                os.link(str(file_to_publish), str(target))
                try:
                    file_to_publish.unlink(missing_ok=True)
                except OSError:
                    pass
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise FileExistsError(f"Target file already exists: {target}") from exc
                if target.exists():
                    raise FileExistsError(f"Target file already exists: {target}")
                os.rename(str(file_to_publish), str(target))

        # When destination staging was used, clean up original staging since publication succeeded
        if dest_staging is not None:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass
    except Exception:
        # Preserve original staging intact for recovery; remove partial destination staging if created
        if dest_staging is not None:
            try:
                dest_staging.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        # Always release the hidden reservation marker
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass

    return target


def atomic_publish_no_replace(
    staging_path: Union[str, Path],
    target_path: Union[str, Path],
    *,
    strict: bool = True,
) -> Path:
    """
    Atomically publishes a staged file to target_path without replacing an existing file (Section 8.1 Rule 6).

    Rejects pre-existing targets with FileExistsError and never silently overwrites.
    Leaves the staging file intact on failure for recovery.

    Parameters:
        staging_path: Path to the existing, closed staging file.
        target_path: Path to the destination file.
        strict: If True, requires true atomic no-replace filesystem primitives.
                If the filesystem cannot provide atomic no-replace, raises UnsupportedFilesystemError.
                If False, allows fallback to collision-resistant (never collision-proof) mode.

    Returns:
        Path to the published target file.

    Raises:
        FileNotFoundError: If staging_path does not exist.
        FileExistsError: If target_path already exists.
        ValueError: If staging_path and target_path resolve to the same path.
        UnsupportedFilesystemError: If strict is True and the filesystem does not support atomic no-replace.
        AtomicPublishError: If an error occurs during publication.
    """
    staging = Path(staging_path)
    target = Path(target_path)

    if not staging.is_file():
        raise FileNotFoundError(f"Staging file does not exist: {staging}")

    try:
        if staging.resolve() == target.resolve():
            raise ValueError(f"Staging path and target path cannot be the same: {staging}")
    except (OSError, RuntimeError):
        pass

    if target.exists():
        raise FileExistsError(f"Target file already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        # On Windows, os.rename uses MoveFileW without MOVEFILE_REPLACE_EXISTING.
        # If target exists, it fails atomically with FileExistsError (WinError 183).
        try:
            os.rename(str(staging), str(target))
        except FileExistsError as exc:
            raise FileExistsError(f"Target file already exists: {target}") from exc
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            if winerror == 183:  # ERROR_ALREADY_EXISTS
                raise FileExistsError(f"Target file already exists: {target}") from exc
            if winerror == 17:   # ERROR_NOT_SAME_DEVICE (cross-drive rename)
                if strict:
                    raise UnsupportedFilesystemError(
                        f"Cannot atomically publish across drives/volumes ({staging} -> {target}). "
                        f"Staging files must be created in the destination directory."
                    ) from exc
                return _collision_resistant_publish(staging, target)
            raise AtomicPublishError(
                f"Failed to publish {staging} to {target}: {exc}"
            ) from exc
    else:
        # POSIX (Linux, macOS, BSD)
        published = False
        # Try Linux renameat2 syscall with RENAME_NOREPLACE if on Linux
        if sys.platform.startswith("linux"):
            try:
                import ctypes
                libc = ctypes.CDLL(None, use_errno=True)
                if hasattr(libc, "renameat2"):
                    AT_FDCWD = -100
                    RENAME_NOREPLACE = 1
                    ret = libc.renameat2(
                        AT_FDCWD,
                        os.fsencode(str(staging)),
                        AT_FDCWD,
                        os.fsencode(str(target)),
                        ctypes.c_uint(RENAME_NOREPLACE),
                    )
                    if ret == 0:
                        published = True
                    else:
                        err = ctypes.get_errno()
                        if err == errno.EEXIST:
                            raise FileExistsError(f"Target file already exists: {target}")
                        elif err not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                            raise OSError(err, os.strerror(err), str(target))
            except (AttributeError, OSError) as exc:
                if isinstance(exc, FileExistsError):
                    raise

        if not published:
            # Fallback for POSIX: os.link + os.unlink
            # os.link fails with FileExistsError (EEXIST) if target exists.
            try:
                os.link(str(staging), str(target))
                try:
                    os.unlink(str(staging))
                except OSError:
                    pass
                published = True
            except FileExistsError as exc:
                raise FileExistsError(f"Target file already exists: {target}") from exc
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise FileExistsError(f"Target file already exists: {target}") from exc
                if strict:
                    raise UnsupportedFilesystemError(
                        f"Filesystem does not support atomic no-replace publication ({exc.strerror}): {target}"
                    ) from exc
                return _collision_resistant_publish(staging, target)

    return target


def atomic_publish_measurement_csv(
    path: Union[str, Path],
    metadata: Union[Mapping[str, Any], pd.DataFrame],
    data: pd.DataFrame,
    *,
    column_units: Optional[Mapping[str, Optional[str]]] = None,
    sync: bool = True,
    encoding: str = "utf-8",
    strict: bool = True,
) -> Path:
    """
    Atomically writes and publishes a measurement CSV file without replacing an existing target (Section 8.1).

    1. Validates metadata, schema/version, and column units before touching disk.
    2. Fails immediately if target already exists.
    3. Creates a staging file in target's directory with tempfile.mkstemp().
    4. Writes metadata, blank line, and data via a single UTF-8 text handle with flush and fsync.
    5. Closes handle.
    6. Atomically publishes staging file to target path via atomic_publish_no_replace.
    7. If target already exists at publish time, raises FileExistsError and leaves staging file intact for recovery.
    """
    meta_df = _prepare_metadata(metadata, data, column_units)
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"Target file already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staging_path = create_staging_file(
        target.parent,
        prefix=f".staging-{target.stem}-",
        suffix=".tmp",
    )

    write_ok = False
    try:
        with io.open(fd, "w", encoding=encoding, newline="") as handle:
            write_measurement_handle(handle, meta_df, data, sync=sync)
        write_ok = True
    finally:
        if not write_ok:
            try:
                staging_path.unlink(missing_ok=True)
            except OSError:
                pass

    return atomic_publish_no_replace(staging_path, target, strict=strict)


def write_measurement_csv(
    path: Union[str, Path],
    metadata: Union[Mapping[str, Any], pd.DataFrame],
    data: pd.DataFrame,
    *,
    column_units: Optional[Mapping[str, Optional[str]]] = None,
    sync: bool = True,
    encoding: str = "utf-8",
    atomic: bool = False,
    strict: bool = True,
) -> Path:
    """
    Convenience function writing a measurement CSV file through a single text handle (Section 8.1).

    Opens the file once, writes metadata, blank line, and data, flushes and fsyncs, then closes.
    If atomic=True, stages to a temporary file in the destination directory and publishes
    atomically without replacement via atomic_publish_no_replace.
    """
    if atomic:
        return atomic_publish_measurement_csv(
            path,
            metadata,
            data,
            column_units=column_units,
            sync=sync,
            encoding=encoding,
            strict=strict,
        )
    meta_df = _prepare_metadata(metadata, data, column_units)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding=encoding, newline="") as handle:
        write_measurement_handle(
            handle,
            meta_df,
            data,
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

    Parses CSV records, including quoted newlines, followed by the blank separator
    and data table. Free-form metadata stays text; only the schema version and
    schema Boolean fields are decoded. Unit JSON is returned separately.

    Returns:
        (metadata_dict, data_df, column_units_dict)
    """
    if isinstance(source, (str, Path)):
        with open(source, "r", encoding=encoding, newline="") as f:
            content = f.read()
    elif hasattr(source, "read"):
        content = source.read()
    else:
        raise TypeError(f"source must be a path or text stream, got {type(source).__name__}")

    stream = io.StringIO(content, newline="")
    records = csv.reader(stream, strict=True)
    try:
        header = next(records)
        values = next(records)
        separator = next(records)
    except StopIteration as exc:
        raise ValueError("Measurement CSV must contain metadata and a blank separator line") from exc
    if separator:
        raise ValueError("Metadata must be followed by a blank separator line")
    if not header or len(header) != len(values) or len(set(header)) != len(header):
        raise ValueError("Metadata must have unique headers and one matching values record")
    metadata: Dict[str, Any] = dict(zip(header, values))
    # CSV has no type tags: preserve all free-form scientific/text metadata as
    # text. Decode only fields whose types are defined by the schema contract.
    if "measurement_schema_version" in metadata:
        metadata["measurement_schema_version"] = int(metadata["measurement_schema_version"])
    for field in ("partial", "save_requested"):
        if field in metadata:
            value = metadata[field].lower()
            if value not in ("true", "false"):
                raise ValueError(f"{field} must be True or False")
            metadata[field] = value == "true"
    validate_metadata(metadata, strict_schema=True)
    data_df = pd.read_csv(stream)

    # Extract column units if present
    column_units: Dict[str, Optional[str]] = {}
    if "column_units_json" in metadata and pd.notna(metadata["column_units_json"]):
        column_units = deserialize_column_units(str(metadata["column_units_json"]))

    validate_column_units(data_df.columns, column_units)
    if set(column_units) != set(data_df.columns):
        raise ValueError("column_units_json must match saved data columns exactly")

    return metadata, data_df, column_units
