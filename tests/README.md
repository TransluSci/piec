# Maintaining the consolidated tests

Keep shared assertions in the category modules and add small, independent case
fixtures when introducing an implementation. Discovery fails on import errors
and missing registrations; do not solve either by adding a skip.

## Instruments

For scopes, add a `ScopeCase` in `support/scope_cases.py`. Supply a fake transport's
responses, native column names, and independently calculated time/voltage values.
Every registered scope runs the same waveform assertions through its real
`get_data()` implementation, including adapters and virtual instruments.

For the other categories, add a `DriverCase` to the corresponding entry in
`support/driver_cases.py`. Supply a factory, an observable category operation,
and its independent expected result. The category's registry is derived from
these executable cases. The factory must return the concrete class being tested;
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
protocol assertions in `test_measurement_protocols.py`. Instrument shutdown
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
