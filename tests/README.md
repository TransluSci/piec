# Maintaining the consolidated tests

Keep shared assertions in the category modules and add small, independent case
fixtures when introducing an implementation. Discovery fails on import errors
and missing registrations; do not solve either by adding a skip.

## Layout and responsibilities

```text
tests/
  driver/        Instrument category contracts, discovery, and virtual behavior
  measurement/   Measurement contracts, lifecycle engine, runner, storage, and GUIs
  simulation/    Material models, simulation contracts, and plant wiring
  support/       Shared discovery helpers, case registries, and fake transports
  fixtures/      Shared fixtures and materials
  test_examples.py
```

The measurement and simulation modules test distinct responsibilities:

- `measurement/test_measurement.py` dynamically inspects discovered
  concrete measurement classes, constructor signatures for instrument dependencies,
  and lifecycle contracts.
- `measurement/test_measurement_engine.py` checks shared lifecycle and session
  rules, thread ownership, and failure handling with a small fake measurement.
- `measurement/test_measurement_runner.py` checks background execution,
  cancellation, snapshots, and delivery of completion or failure to the caller.
  These worker behaviors are not exercised by synchronous measurement tests.
- `measurement/test_persistence.py` checks the shared storage implementation,
  including atomic writes, filename collisions, metadata, and recovery from
  incomplete bundles.

GUI and waveform reader tests live with measurements because they exercise
measurement-facing integration. Documentation example tests remain at the root.
Simulation tests live together under `simulation/`. This organization preserves existing coverage;
Pytest discovers the subfolders automatically. To run a single layer, replace
`tests/` in the verification command below with `tests/driver/`,
`tests/measurement/`, or `tests/simulation/`.

## Simulation and future sample layers

`simulation/test_simulation.py` currently covers physical units and response
contracts, numerical model behavior, deterministic time and randomness, and
virtual bench wiring, reset, and isolation. Virtual instruments are dependencies
of the bench integration tests, which check how models and instruments interact.
The current model cases are explicit; adding a new material does not yet
automatically exercise it through a shared discovery-based contract suite.

When the three-level sample API is implemented, split these responsibilities
inside this folder around the real interfaces:

- Level 1: shared sample input/output, units, lifecycle, reset, and isolation.
- Level 2: material-family contracts (e.g. FE/FM), required properties and response
  formats. Use shared assertions with small fixtures for concrete implementations.
- Level 3: model-specific numerical references, limiting cases, and convergence
  checks where appropriate. Correct schemas alone do not establish correct physics.
- Material dictionaries/JSON: required fields, units, invalid values, independent
  instances, and save/load round trips when serialization exists.
- Bench integration: instrument-to-sample routing, timing, and end-to-end response.

Add discovery against the actual sample base classes when those interfaces exist;
do not invent placeholder classes or require every model to obey one model's
equations. Keep shared material fixtures in one place and reuse family contracts
across different material parameter sets.

## Instruments

Each category module discovers its inventory by inheritance from the production
category base class, including adapters. Adding a driver under its category
folder automatically adds it to the shared declaration and behavioral tests.
No central list of concrete driver imports is maintained.

Declaration checks need no per-driver fixture. Every non-`None` public data
attribute in the category parent is a requirement: the child cannot set it to
`None`. Parent enumeration entries must remain present; children may add entries.
Thus `[1, 2, 3, 4, 5, 6]` passes for AWG channels, while `[2, 3, 4, 5]` fails
because channel `1` is required. Mixed types, duplicates, booleans, and fractional
channels also fail. DAQ resource lists allow zero and may be empty when their
parent declaration is empty.

Mappings preserve required keys recursively. Tuples with concrete bounds preserve
their shape and those bounds must remain specified, though device limits may
differ. `(None, None)` is an open capability requirement: drivers may supply a
range, discrete choices, or a dependent mapping, but cannot supply `None`.
Nested placeholders such as `[(None, None)]` do not require an unbounded physical
range. A parent attribute
that is itself `None` imposes no requirement. Inherited declarations count; a
child need not repeat an unchanged value. Checks run on classes and fixture-created
instances, so an instance override cannot remove a parent requirement.

Callable checks remain separate and do not prove an inherited method contains an
implementation. Behavioral cases provide independent checks of actual operations.
Drivers that narrow parent enumerations or replace required attributes with `None`
fail this contract. Do not advertise unsupported hardware features just to satisfy
a test.

For adapter-dependent behavior, exercise both settings of `check_params` and
verify rejection on channels without the adapter. TDS6604 keeps its native
impedance declaration and validates adapter-dependent requests in its setter;
the general parameter checker continues to validate other arguments.

For scopes, add a `ScopeCase` in `driver/test_scope.py`. Supply a fake transport's
responses, native column names, and independently calculated time/voltage values.
Every registered scope runs the same waveform assertions through its real
`get_data()` implementation, including adapters and virtual instruments.

For other categories, put a `DriverCase` in `CASES` beside that category's tests
(for example, `driver/test_awg.py`). Supply a factory, an observable category
operation, and its independent expected result. Shared helpers live in
`support/driver_contracts.py` and import no concrete drivers. The common `physical`
factory attaches a strict fake transport; custom factories handle virtual hooks
and vendor-specific setup. Physical constructor/hardware initialization is bypassed

For scopes, add a `ScopeCase` in `driver/test_scope.py`. Supply a fake transport's
responses, native column names, and independently calculated time/voltage values.
Every registered scope runs the same waveform assertions through its real
`get_data()` implementation, including adapters and virtual instruments.

For other categories, put a `DriverCase` in `CASES` beside that category's tests
(for example, `driver/test_awg.py`). Supply a factory, an observable category
operation, and its independent expected result. Shared helpers live in
`support/driver_contracts.py` and import no concrete drivers. The common `physical`
factory attaches a strict fake transport; custom factories handle virtual hooks
and vendor-specific setup. Physical constructor/hardware initialization is bypassed
by this helper, so it is not validated by these runtime cases.

Discovery supplies the test parameters even when a case is missing. Declaration
checks still run, while the behavioral test fails with the driver's name and
instructions to add its fixture. It is never silently omitted or skipped.
Expected commands and response scaling must be independent of the driver's code.
The factory must return the concrete class being tested;
constructing a physical model with `"VIRTUAL"` does not test its physical driver.

## Measurements

Measurement testing focuses on dynamic inspection and lifecycle contracts:
- Dynamically discovers all concrete subclasses of `BaseMeasurement`.
- Verifies constructor signatures declare instrument dependencies (`sourcemeter`, `awg`, `osc`, `dmm`, `lockin`, `stepper`, etc.).
- Verifies required lifecycle hooks (`_configure_instruments`, `_capture_data`, `_safe_shutdown`) and public controls (`run_experiment`, `request_stop`).
- The engine and runner suites separately cover lifecycle, session, ownership, multi-threading, and shutdown error paths.

## Verification

Run all active measurement and simulation test suites with:
```powershell
pytest tests/measurement/ tests/simulation/
```

The review's controlled defects should remain detectable: constructor hardware
I/O, swallowed session shutdown failures, a scope returning `None`, and a new
module that fails to import. The setup-reset test permits legitimate hook
notifications for reset outputs/position but preserves the setup clock and
material memory.
