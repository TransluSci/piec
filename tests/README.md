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

- `measurement/test_measurement.py` checks the common contract across concrete
  measurements: data columns and units, acquisition, cancellation, saving, and
  safe shutdown.
- `measurement/test_measurement_engine.py` checks shared lifecycle and session
  rules, thread ownership, and failure handling with a small fake measurement.
- `measurement/test_measurement_runner.py` checks background execution,
  cancellation, snapshots, and delivery of completion or failure to the caller.
  These worker behaviors are not exercised by synchronous measurement tests.
- `measurement/test_persistence.py` checks the shared storage implementation,
  including atomic writes, filename collisions, metadata, and recovery from
  incomplete bundles.
- `measurement/test_measurement_contracts.py` dynamically inspects discovered
  concrete measurement classes, constructor signatures, lifecycle hooks, and
  verifies returned DataFrame formats and PIEC CSV layouts.

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
by this helper, so it is not validated by these runtime cases.

Discovery supplies the test parameters even when a case is missing. Declaration
checks still run, while the behavioral test fails with the driver's name and
instructions to add its fixture. It is never silently omitted or skipped.
Expected commands and response scaling must be independent of the driver's code.
The factory must return the concrete class being tested;
constructing a physical model with `"VIRTUAL"` does not test its physical driver.

These cases establish a minimum representative behavior per implementation.
Keep the category modules' additional command, validation, and model-specific
checks; one successful read is not proof that every device feature works.
Add shared operations as category requirements grow. The Rigol DG1000 runtime
trigger case uses the DG1000Z profile; legacy-profile restrictions remain in the
AWG command tests. Scope impedance simulation remains deferred.

Use scripted transports or replace the vendor boundary for physical devices.
New scripted runtime cases use strict query matching so an unexpected query
cannot silently receive a plausible zero. Expected data must not be generated
from the production parser or command mapping being tested.

## Measurements

Add a `MeasurementCase` in `support/measurement_cases.py`, with its factory branch,
independent columns/units, invalid options, acquisition sensor, and observable
shutdown expectations. Install spies before constructing the measurement.

The common suite checks constructor/pre-start I/O, successful data, saved values
and units, cancellation after real acquisition, callback errors, and direct
sensor failures. Streaming sensor failures must retain an acquired row;
single-shot read failures need not manufacture a partial frame. The fake engine
suite separately covers lifecycle, session, ownership, and shutdown error paths.

Keep scientific references in `fixtures/measurement_compatibility` and unique
protocol assertions in `measurement/test_measurement_protocols.py`. Instrument shutdown
checks observe state and actions, not only the reported safety enum. Fixtures
own connections; measurements must not close them.

## Verification

Follow the existing CI workflow for Python 3.9/3.13 and its headless Matplotlib
setup. For local runs where GUI tests might initialize a plotting backend, use:

```python
import piec.measurement.gui_utils
import matplotlib
matplotlib.use("Agg")
import pytest
raise SystemExit(pytest.main(["tests/", "-q", "-p", "no:cacheprovider"]))
```

The review's controlled defects should remain detectable: constructor hardware
I/O, swallowed session shutdown failures, a scope returning `None`, and a new
module that fails to import. The setup-reset test permits legitimate hook
notifications for reset outputs/position but preserves the setup clock and
material memory.
