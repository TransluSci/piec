# Adding a Driver

You can contribute a driver in three ways: write it manually, generate it in an
AI chat using attached files, or use an AI coding agent with repository access
(such as Codex or Antigravity). All three methods follow
`DRIVER_DEVELOPMENT_GUIDE.md` and require you to review and validate the result.

The workflow below adds a model to an existing instrument category. A category
defines the shared interface; your driver implements it for a specific instrument.
If you need an entirely new category, such as a thermometer, see
{ref}`creating-instrument-category` at the end of this page.

**DO NOT ADD ANY TESTS for driver contributions.** Our existing dynamic tests
discover categories and drivers and check the new code against their contracts.
Run those tests; do not add or modify test files, fixtures, or test notebooks to
accommodate your driver. This applies to new categories and new models, whether
written manually or with AI.

## Implement your instrument driver

Find the interface that already describes your instrument:

| Instrument category | Interface file, relative to `src/piec/drivers/` |
|---|---|
| Arbitrary waveform generator | `awg/awg.py` |
| Oscilloscope | `oscilloscope/oscilloscope.py` |
| Sourcemeter | `sourcemeter/sourcemeter.py` |
| Lock-in amplifier | `lockin/lockin.py` |
| Digital multimeter | `dmm/dmm.py` |
| Data acquisition device | `daq/daq.py` |

**Start by copying the category file and filling it out.** For an AWG, copy
`src/piec/drivers/awg/awg.py` to `src/piec/drivers/awg/specific_awg.py`.
Use the actual model name for the new filename when contributing:

```text
src/piec/drivers/<category>/<model_name>.py
```

In the copy:

1. Rename the class to identify the model, import the original category class,
   and inherit from it. For example, replace `class Awg(Instrument)` with
   `class SpecificAwg(Scpi, Awg)` for a SCPI instrument, importing `Awg` from
   `.awg` and `Scpi` from `..scpi`. For a proprietary protocol, use
   `class SpecificAwg(Awg)`.
2. **Keep the parent method docstrings, signatures, defaults, and return
   contracts.** Fill in the method bodies using the programming manual. Append
   model-specific details to the docstrings where useful; do not replace the
   shared API documentation with a shorter generated description.
3. Fill in the copied capability attributes with the model's actual limits and
   supported values, and add its `AUTODETECT_ID`. If the parent declares an
   attribute as `None` because its representation varies by instrument, use a
   tuple for a continuous range or a list for discrete choices as appropriate.
   A parent value of `(None, None)` fixes the type as a tuple; it is not the same
   as `None`. See the guide's class-attribute rules below.
4. Lifecycle methods such as `reset()` are inherited from `Instrument` and
   the applicable protocol convenience class. Reuse working implementations;
   override them in the model when required by the manual or category contract.
   Inherited placeholders do not perform hardware operations. Do not add empty
   methods that hide working implementations.
5. For supported optional methods, fill in the body and remove the copied
   `@optional` decorator: that decorator belongs only on the category interface.
   Omit unsupported optional methods from the model copy so the parent provides
   its documented skip behavior. Implement every required method.

The category file itself is the model template; no separate
`specific_example.py` attachment is needed.

The category interface, its existing virtual driver, and all other existing files
are read-only for this contribution. If the model cannot fit the interface,
describe the missing contract in an issue or your pull request for discussion;
do not change the parent interface or framework to make it fit.

## Gather the reference files

Use files from the **branch you are contributing to**, so the implementation
matches its current contracts. Paths are relative to the repository root.

| Material | Purpose |
|---|---|
| `src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md` | Required development rules |
| Instrument programming manual | Required source of command strings |
| Instrument user manual or specifications | Include if needed for limits and features |
| `src/piec/drivers/<category>/<category>.py` | Required starting template: copy it and fill in the implementation while preserving its docstrings |
| `src/piec/drivers/instrument.py` | Required read-only reference for lifecycle contracts and state tracking |
| `src/piec/drivers/scpi.py` or `src/piec/drivers/digilent.py` | Include the applicable convenience class |

`Scpi` supplies standard IEEE 488.2 / SCPI lifecycle methods. `Digilent` supplies
MCC/Digilent Universal Library communication. Verify inherited behavior against
the manual and override differences in the new model file. Put the protocol
convenience class **before** the category in the inheritance list:

```python
class MyAwg(Scpi, Awg):
    ...

class MyDaq(Digilent, Daq):
    ...
```

For a proprietary protocol, inherit from the category alone and implement the
required protocol behavior using the instrument manual, including lifecycle
methods absent from the category file.

Read the shared lifecycle docstrings in `Instrument` and the category class
docstring. Reset restores default operating settings with controllable outputs
off; scopes additionally require AUTO trigger sweep and running acquisition.
After resetting hardware, call `self._initialize_state()` to clear cached
`_current_*` settings to `None`; this helper sends no commands and does not reset
the hardware. A working inherited reset may already call it. `clear()` clears
errors/status/buffers without resetting settings, and `initialize()` calls reset
then clear rather than performing a power cycle.

Document additional or different behavior in the class docstring, and explain
model-specific implementation details in method docstrings. Model differences
must still satisfy the shared and category contracts.

## Method 1: Write the driver manually

1. Read `src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md`, reproduced in the
   {ref}`driver-code-rules-reference`, and gather the references above.
2. Copy `src/piec/drivers/<category>/<category>.py` to the new
   `<model_name>.py` in the same directory. Rename the copied class and make it
   inherit from the original category as described above. Preserve the method
   docstrings and signatures, then fill in the bodies. Append hardware-specific
   documentation as needed and handle inherited and optional methods as above.
3. Map device commands and names to the common interface. Declare capabilities
   and initial limits as class attributes: model virtual dispatch skips the
   physical constructor, so constructor-only limits are unavailable in virtual mode.
4. Set `AUTODETECT_ID` to a verified unique substring of the identification
   response, or a list of verified substrings for a model family. If automatic
   identification is unsupported or the identifier is unknown, use
   `"MANUAL_ONLY:<ClassName>"` with the actual class name, for example
   `"MANUAL_ONLY:Geos_Stepper"`. Document the limitation and direct construction
   with an explicit address. Do not use `None` or the bare `"MANUAL_ONLY"` string.
5. Follow the validation and review steps below. Do not add tests.

## Method 2: Generate files in an AI chat

Attach the applicable reference files and programming manual to your chat.
Identify the branch the files came from. The AI needs the file contents, not
just their paths.

Fill in this prompt with **one new model file** as the allowed output.

```text
Create an instrument driver for piec using the attached files from my target branch.

Instrument: <manufacturer and model>
Scope: Add one model to an existing category.
Category and parent class: <category and existing parent class>
Communication protocol: <SCPI / Digilent / proprietary protocol>
Allowed output file: src/piec/drivers/<category>/<model_name>.py
Programming manual: <filename>

Read DRIVER_DEVELOPMENT_GUIDE.md first. All existing source files are read-only
references. Return complete contents of only the listed new files, labelled by
path. Do not propose edits to instrument.py, autodetect.py, virtual_dispatch.py,
virtual_instrument.py, utilities.py, scpi.py, digilent.py, existing category
interfaces, virtual drivers, package initializers, or any other existing file.

Start from a copy of the attached category file, not a separately generated
skeleton. Rename the copied class and make it inherit from the original
category, with the applicable protocol convenience class first.
Preserve the parent method docstrings, signatures, defaults, capability names,
and return formats. Fill in the method bodies and model capability values.
Append model-specific details to docstrings; do not replace the shared text.
Implement all required methods, including hardware behavior for inherited
lifecycle placeholders. Read instrument.py and the category class docstring;
reuse working protocol methods and override them when required. Reset must
restore defaults with controllable outputs off; scopes must also acquire in
AUTO mode. After hardware reset, call self._initialize_state() to clear cached
_current_* settings unless the inherited reset already does so. This helper
does not reset hardware. Document additional or different behavior in the class
docstring while preserving the shared and category contracts. Never add empty
methods that hide working inherited implementations.
Remove copied @optional decorators from supported method implementations.
Omit unsupported optional methods so the parent's skip behavior is inherited.

Use only commands and specifications supported by the attached manuals.
Do not guess commands, capabilities, or identification strings. Use
AUTODETECT_ID = "MANUAL_ONLY:<ClassName>" if automatic identification is
unsupported or the identification substring cannot be verified, substituting
the actual unique driver class name. Document that users must instantiate the
class directly with an explicit address. This marker is not a real ID response
or proof that physical autodetection works; do not make idn() return it.
Declare model capabilities at class level and keep simulation out of the
physical model. No manual registration changes are needed.
For a capability declared as None in the parent, choose a tuple for continuous
limits or a list for discrete choices according to the manual. For a non-None
parent declaration, preserve its required type and structure.

DO NOT ADD ANY TESTS, fixtures, or test notebooks, and do not change existing
tests. The existing dynamic tests discover and check the new drivers.

If the work requires a change outside the allowed files, report the blocker
instead of expanding the scope. List unresolved questions and manual sections
used so I can review the implementation.
```

Review the output, then save only the allowed files into your checkout. A second
chat can review the result with the same guide, interfaces, and manuals; ask it to
identify discrepancies and cite the relevant manual sections. You remain
responsible for checking the code and running the existing tests.

## Method 3: Use an AI agent in the repository

A repository agent such as Codex or Antigravity can edit files directly. Start
from a clean working tree when possible. Otherwise, record `git status --short`
and your current diff to distinguish prior work from the agent's changes.
Provide local paths to the manuals and reference files.

Use the implementation prompt above, replacing the attachment/output directions
with repository paths and these editing instructions. Replace the allowed-file
placeholder with the exact model path before starting; do not simply ask the agent to
"add support" for an instrument.

```text
Work in this checkout on the current branch. Read the development guide,
reference files, and manuals at the supplied paths.

You may CREATE ONLY this new file:
src/piec/drivers/<category>/<model_name>.py

Create it by copying src/piec/drivers/<category>/<category>.py. Rename the
copied class and inherit from the original category. Preserve its method
docstrings and signatures, fill in the implementation, and append relevant
model-specific documentation. Follow the implementation prompt's rules for
delegating inherited methods and handling optional methods.

DO NOT MODIFY, DELETE, RENAME, or overwrite any existing files. In particular,
instrument.py, autodetect.py, virtual_dispatch.py, virtual_instrument.py,
utilities.py, scpi.py, digilent.py, all existing category interfaces and
drivers, existing __init__.py files, tests, and project configuration are
read-only. Do not refactor shared code or change parent contracts to make
the new driver pass. Do not revert unrelated changes already in the checkout.

DO NOT ADD ANY TESTS, fixtures, or test notebooks. Run the existing dynamic
driver tests with python -m pytest tests/driver/ -v. Fix failures only within
the allowed new files. If a fix needs a change elsewhere, stop that work and
report the blocker without editing that file.

Before finishing, inspect git status --short, git diff, and git diff --cached.
Report every file created or changed, test results, and unresolved manual or
hardware verification questions. Do not claim physical hardware verification
from virtual or mocked tests.
```

This permits only the specific instrument file, never changes higher up the
inheritance chain. **Check the agent's actual changes yourself**; its summary is
not a substitute for inspecting the files.

## Discovery and virtual operation

Model discovery scans driver modules for `AUTODETECT_ID`. Your model uses the
category's existing virtual driver. You do not need to register or re-export
the model in an existing file.

- `ModelClass("VIRTUAL")` selects the category's virtual implementation and
  applies the model's capability class attributes. Parameter validation is
  enabled by default for these model-profiled virtual instances.
- `autodetect("VIRTUAL_<category>")` selects the generic category virtual driver,
  for example `autodetect("VIRTUAL_AWG")`.
- The exact address `"VIRTUAL"` is for concrete model constructors;
  `"VIRTUAL_<category>"` is for `autodetect`. A failed physical connection does
  not silently become a virtual connection.

Keep simulation in the category's virtual driver. Do not add virtual-mode
branches to a physical model or modify central dispatch code.

## Validate and review before submitting

With piec and pytest installed, run the existing tests from the repository root:

```sh
python -m pytest tests/driver/ -v
python -m pytest tests/ -v
```

The dynamic suites in `tests/driver/` discover new categories and models and
check contracts such as inheritance, method implementation, signatures,
capabilities, and virtual dispatch. The physical-driver suite uses test
transports; passing it does **not** prove commands work on real hardware.
Do not add tests or change discovery code, fixtures, or assertions for your
contribution. Fix failures in your new files and report framework issues separately.

Before submitting:

- Cross-check commands, limits, units, and response parsing against the manual,
  including inherited protocol methods.
- Verify the physical driver on the real instrument. Existing category notebooks
  may be used interactively where applicable; do not copy, add, or commit changes
  to test notebooks. Record hardware verification results in the pull request.
- Confirm a real `AUTODETECT_ID` matches the identification response. For a
  `MANUAL_ONLY:<ClassName>` marker, verify direct construction with an explicit
  address and document that physical autodetection is unsupported or unverified.
- Review `git status --short`, `git diff`, and `git diff --cached`. Open untracked
  files too: ordinary `git diff` does not show their contents. Confirm that your
  contribution contains only the allowed new files and no edits to existing
  files higher up the chain, unrelated files, or tests.
- State which tests and hardware checks passed, any unresolved limitations, and
  any significant AI assistance in the pull request. Physical hardware
  verification is required before a driver is ready for contribution.

(driver-code-rules-reference)=
## Code Rules Reference

The guide below is included directly from
`src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md`, so it follows the checked-out
branch. Supply that file to any AI assisting with a driver.

```{include} ../../../src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md
```

(creating-instrument-category)=
## Create a new instrument category

Use this route only when the instrument does not fit an existing category.
**It is HIGHLY recommended to create the category manually**, even if you use AI
to fill out the specific drivers afterwards. This helps ensure erroneous
functions aren't added and the base class attributes make sense for the whole
instrument type.

This is the most important part because it sets up the entire category. Think
of the minimum requirements of the instrument: what is the most general
interface, with some consolidations for convenience where useful? Prefer
`set_`, `get_`, and `configure_` methods for individual settings, values, and
groups of settings. Use the guide's `read_` or `run_` conventions when needed;
existing methods such as `quick_read()` remain part of their current interfaces.

For things we expect all instruments of that type to have, define common names
and capability defaults in the base class. For example, `channel = [1]` means
every model has at least channel 1; a model with more channels adds them to its
list. Different manufacturers may call the same feature different things, but
the specific driver translates from the defaults and names in the file you are
making into the instrument's commands. This keeps the measurement code valid across all drivers in that class.

These defaults describe the shared capabilities, not arbitrary values to send
to hardware. Leave model-specific limits unspecified, and use `None` if an
attribute has different implementations across instruments (e.g. a tuple on one model and a list on another). Features that not
every instrument has belong in optional methods, rather than becoming required
just because one manufacturer's manual lists them.

For example, a new `thermometer` category with its first model would add:

```text
src/piec/drivers/thermometer/
    __init__.py
    thermometer.py
    virtual_thermometer.py
    <model_name>.py
```

These are new files, confined to the new category directory:

1. **`__init__.py`**: keep the new package initializer minimal; it may be empty.
2. **`thermometer.py`**: define exactly one canonical category class inheriting
   from `Instrument`. The interface filename must match the directory name.
   Use `example/example.py` and a current category interface as references.
   Define the category's capability names, method signatures, units, and return
   formats. Common lifecycle methods (`idn`, `reset`, `clear`, etc.) are already
   defined by `Instrument`; do not copy them into a new category. Document
   additional or different category requirements in the class docstring.
   Actual hardware behavior belongs in the protocol convenience class or the
   specific driver.
   Initialize a capability to `None` when its representation may vary by model
   (for example, a tuple on one instrument and a list on another). Use a concrete
   type only when the category requires that representation across models.
   Keep device command strings out of the interface. Use `@optional` here for
   features that are useful in practice and available on many instruments, but
   not every model. Expose them in the common interface while recognizing that
   cheaper or simpler models may not have that capability.
3. **`virtual_thermometer.py`**: define one virtual class inheriting from
   `VirtualInstrument` first and the new category second. Implement the required
   interface with in-memory simulation. Its constructor must call
   `super().__init__(...)` exactly once. Use a current virtual driver as a
   reference. The dynamic suite expects a virtual implementation for every
   category; this is driver code, not a new test.
   Optional features do not need simulated implementations; inherit the parent's
   skip behavior unless you need to simulate them.
4. **`<model_name>.py`**: copy the new category interface, rename the copied class
   and make it inherit from that category, then fill in the physical implementation.
   Preserve the method docstrings and signatures and use the programming manual
   for commands and capabilities, following the same copying workflow above.

Keep exactly one `virtual_*.py` module containing one virtual driver class in the
category. Discovery uses the folder and interface filename; the Python category
class name need not match them. No edits to a central registry, `autodetect.py`,
or existing package initializers are needed. Convenience aliases are separate
API changes and are outside this contribution.

### Implement the new category manually or with AI

All three contribution methods still apply, with the new category's files as
the scope, but review and define the shared interface manually first wherever
possible. If using AI to draft it, check every proposed method and capability
against what the category should actually support. In addition to the guide and
programming manual, gather `src/piec/drivers/example/example.py`, a current category interface,
`src/piec/drivers/virtual_instrument.py`, and a current virtual driver as references.

- **Manually:** define the category interface first, implement its virtual
  behavior, then copy the new interface into the physical model file and fill it out.
- **AI chat:** attach these additional references and replace the model-only
  scope and implementation instructions in the chat prompt with the block below.
  Request complete contents of the four new files, labelled by path.
- **Repository agent:** supply paths to the additional references and replace
  the model-only scope and allowed-file list with the block below. Keep all
  restrictions on changing existing files and adding tests.

Fill in the actual category and model names before using this block:

```text
Scope: Create a new instrument category and its first physical model.
Allowed new files:
src/piec/drivers/<new_category>/__init__.py
src/piec/drivers/<new_category>/<new_category>.py
src/piec/drivers/<new_category>/virtual_<new_category>.py
src/piec/drivers/<new_category>/<model_name>.py

Create a minimal package initializer, a manufacturer-independent interface
inheriting Instrument, one virtual implementation inheriting VirtualInstrument
first and the new category second, and the physical model. Implement all
required interface methods in the virtual and physical drivers. Keep hardware
command strings out of the category interface and simulation out of the model.
Use the reviewed category requirements to define common names and capability
defaults for features expected on all models. Do not invent functions or turn
one manufacturer's extra features into category requirements. The physical
driver translates these common names into the manufacturer's commands. Leave
optional virtual features unimplemented unless their simulation is needed.
Keep the category general: prefer set_, get_, and configure_ methods, and mark
useful features absent from some models as optional. Inherit common lifecycle
methods from Instrument; document additional or different category requirements
in the class docstring instead of adding duplicate lifecycle stubs.
Declare parent capability attributes as None when the representation can vary
by instrument, such as a continuous tuple versus a discrete list. Supply the
actual limits or options on the physical model class.
Once the new interface is defined, copy it as the starting point for the
physical model. Rename that class and inherit from the new category, preserving
the method docstrings and signatures while filling in the implementation.
Apply the same rules for inherited lifecycle methods and optional methods as
in the model-driver workflow.

All existing files remain read-only, including instrument.py, autodetect.py,
and the shared virtual infrastructure. Do not add registration changes.
DO NOT ADD ANY TESTS, fixtures, or test notebooks. Run the existing dynamic
tests. Report blockers that require changes outside these four new files.
```

Follow the same validation and changed-file review steps above. Check category
discovery with `autodetect("VIRTUAL_<new_category>")` and model-profiled virtual
operation with `ModelClass("VIRTUAL")`. Exercise the new interface on physical
hardware and record the results in the pull request. Confirm that only the new
category's files were added and no existing files were changed.
