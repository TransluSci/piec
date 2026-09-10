# Measurement standardization handoff

Continue on `measuremnt-standarization`. Checkpoints 11c and 12 review fixes are
complete. The next task is **checkpoint 13 only: the IV vertical slice**, including
IV GUI, analysis, notebook and test consumers. Follow the plan's IV-specific
configuration, cancellable ramp/read, and paced safing requirements. The guide's
small example illustrates the engine API; it is not the completed production IV
migration. Commit checkpoint 13 separately before starting checkpoint 14.

## Checkpoint 12 corrections

- `compliance_current` is validated before reservation/I/O and applied through
  `configure_voltage_source`; its default in the example is 0.01 A.
- Acquisition preserves completed samples in `self._raw_data` in `finally`, including
  read and callback failures. Hardware cleanup belongs to the engine-invoked
  `_safe_shutdown`, keeping acquisition errors primary if shutdown also fails.
- Display snapshots are bounded, callbacks receive snapshots, and the command-line
  queue consumer handles `queue.Empty`. GUI consumers still use UI timer polling.
- The safing example records command success without inventing readback support.
  A driver's optional no-op must never be converted into successful verification.
- Documentation now describes actual Windows publication and close gating. There
  is no unsafe-close acknowledgment override. Stop-before-start skips hardware
  safing, and partial filenames depend on save policy and successful publication.
- `tests/test_measurement_developer_guide.py` executes the published code blocks,
  covering successful workflows, invalid/applied compliance, read/callback partial
  recovery in runs and sessions, queue timeout, and simultaneous acquisition and
  shutdown errors. All 16 tests passed.
- Full repository verification: **1163 passed, 1 skipped, 2 xfailed**. Real SMB and
  physical hardware remain unverified. Production measurement files were unchanged
  in the checkpoint 12 correction.

## Corrections already implemented

- Bundle publication keeps original side-artifact staging files until the completed
  CSV succeeds. A failed CSV publication leaves recoverable raw data. Rollback
  checks the published file identity before deletion and reports cleanup failures.
- Reservations contain full run IDs and unique claim IDs. Release verifies the
  claim; an old reservation cannot delete a replacement owner's marker.
- Publication, reservation reuse, and cleanup use exclusive guard files. An
  abandoned `.res.lock` blocks that candidate; do not automatically delete it.
  Inspect and explicitly remove such locks only after confirming no writer is active.
- `stale_age_seconds` only permits reuse of the explicitly named run's marker.
  Age alone never authorizes taking a foreign run's reservation. Cleanup requires
  `owner_uuid`; omission does nothing. Partial cleanup also validates the CSV's
  run ID and partial flag. Unknown or foreign files are retained.
- Cross-volume fallback reuses the bundle's existing reservation. The POSIX
  fallback still fails safely if no no-replace primitive is available.
- Partial metadata is validated before allocating staging. Replacing a checkpoint
  requires matching ownership metadata. Replacement failures retain/report the
  new staging file and preserve the previous checkpoint.

## Shared engine persistence API reference

`BaseMeasurement` accepts keyword arguments `output_dir`, `measurement_schema`,
`column_units`, optional `raw_column_units`, and optional `metadata`.
No persistence configuration is needed for `save=False`. Saving requires explicit
configuration; the engine no longer reports a virtual path as a successful save.

For example, a subclass for IV data can initialize the shared engine with:

```python
super().__init__(
    output_dir=output_dir,
    measurement_schema="iv_sweep",
    column_units={"voltage": "V", "current": "A"},
    metadata={"sample": sample_name},
)
```

The engine generates required lifecycle metadata and uses plain column names with
JSON unit metadata. `raw_column_units` describes partial data when its columns
differ from analyzed results. Full runs and sessions both use real filesystem
publication. Aborted/failed partials record their actual outcome; they never set
`filename`. Completed filenames are assigned only after successful publication.

Families producing plots override `_stage_side_artifacts(data, request,
reservation)` to return `(staging_path, target_path)` pairs. Targets must be in the
reserved destination and begin with `reservation.candidate_basename + "_"`.
Use run-owned hidden staging names; preserve raw data in memory. If staging itself
fails, attach any recovery paths to the exception. Do not override the shared
publication mechanism just to implement plots.

Save errors preserve in-memory raw data and expose `recoverable_staging_paths`
on the exception and measurement, and in `RunRecord.metadata`. The standalone
`write_partial_csv` helper supports intentional updates to an owned checkpoint.
Do not describe automatic periodic checkpoint scheduling as implemented.

## Verification and boundaries

Checkpoint 11c verification passed: **1147 passed, 1 skipped, 2 xfailed**.
The newer checkpoint 12 result is recorded above.
Sixteen new recovery/engine regressions cover the reviewed failures, actual
completed and partial CSVs for runs and sessions, and failed-save recovery.
The opt-in real SMB test remains skipped; cross-volume behavior was fault-injected.
No physical hardware or SMB deployment validation is claimed.

Measurement-family migrations remain in their planned checkpoints. Preserve the
user's decisions: plain columns, units in metadata, standardized APIs throughout,
and no legacy argument adapters or compatibility shims.
