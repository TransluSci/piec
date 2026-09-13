Changelog
=========

Unreleased: measurement standardization
------------------------------------------

IV, MOKE, hysteresis, three-pulse PUND and AMR now use the shared measurement
lifecycle, runner and persistence layer. Their GUIs coordinate worker completion,
cancellation, safing and connection ownership. Acquisition and analysis can run
in memory; saving is a separate policy rather than a prerequisite for analysis.

Formats and API changes
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Measurement CSV columns use plain names (for example ``voltage``, ``current``,
  ``delta_polarization`` and ``detector_voltage``). Read units from
  ``column_units_json`` metadata instead of parsing units from column names.
* Metadata includes ``measurement_schema`` and ``measurement_schema_version``.
  Use those identifiers when selecting files; a results folder can contain
  multiple measurement types.
* Update scripts to current constructors and session/runner APIs. Replaced
  methods and old column names have no new compatibility shim or automatic
  converter. The standardization does not rewrite existing user files.
* Sourcemeter calls use the channel-first contract. Explicit keywords such as
  ``set_source_voltage(channel=1, voltage=1.0)`` avoid positional ambiguity.
* Atomic CSV publication avoids replacing an existing result and preserves staged
  recovery data when publication cannot complete. Partial-save policy is explicit.

Simulation and setup ownership
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``VirtualBench`` owns independent instruments, models, routes, deterministic
  clocks and random streams. Reset attempts all components and reports failures.
* Electrical simulations solve both terminal quantities under compliance.
  Stateful loads require explicitly scheduled time steps.
* IV/MOKE/FE/AMR numerical fixtures use private benches. Numerical references
  remain unchanged; virtual instrument identity metadata is truthful.
* FE/AMR notebooks and GUIs use private example plants; MOKE uses explicit optical
  wiring. The generic-driver shared-sample fallback remains externally available.
* AMR preserves manual lock-in configuration by default. Excitation assumptions
  belong to the setup. The default resistive virtual material reports zero Y;
  specific nonzero-Y fixtures declare their response law.

Validation and remaining release gates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run ``python scripts/check_measurement_notebooks.py`` to execute virtual notebooks
in temporary output folders. Set ``PIEC_DOCS_OFFLINE=1`` in the environment when
building docs to avoid intersphinx network fetches. CI tests Python 3.9 and 3.13
and runs the notebook and documentation checks.

Physical IV/MOKE, FE and AMR records remain **PENDING**. Virtual tests do not
replace bench measurements or operator sign-off. Python 3.9 was unavailable
locally; CI must satisfy that gate before release. Optional scientific additions
(checkpoint 32) and additional AMR electrical adapters were not included.
