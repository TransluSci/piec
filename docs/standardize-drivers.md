# Driver-only branch with replayed history

`standardize-drivers` is based on master `5d83b73` and replays **24 original commits** from `measuremnt-standarization` at `6308a3c`: 6 complete cherry-picks and 18 extractions limited to driver code, driver tests and driver documentation. Original authors, author dates and commit messages are retained. Each commit records its source hash; new hashes are expected when replaying onto another base.

The earlier single-commit snapshot is preserved on `codex/standardize-drivers-snapshot` at `573b0b3`. The original measurement branch is unchanged. Nothing has been pushed.

## Scope

- Physical driver fixes and features: DAQ family/emulators, AWG triggers, DMM configuration/overload handling, sourcemeter channel interface, scope capability/command fixes, and common instrument/autodetect behavior.
- Ordinary virtual-driver changes for DAQ trigger logging, DMM configuration/read callback, calibrator output, and sourcemeter channel validation. The simple DMM voltage-reader callback is standalone and requires no new simulation contracts.
- Driver-test history, including early focused tests, consolidation, folder moves and the final physical/virtual dynamic contracts. Replaced root driver test files are removed by the replayed consolidation history.
- The DAQ notebook, driver development guide and three driver audit documents.

No changes to measurement code, GUIs, notebooks outside the driver directory, analysis code, simulation code, packaging or CI are introduced by this branch. Some retained historical commit titles mention measurements because those commits originally mixed several areas; their `Driver-only-from` trailers identify the scoped extraction.

## Deliberately excluded and adapted

- Excluded the later generic virtual-hook series, simulation contracts/models, VirtualBench and consumer setup work.
- Excluded the latest virtual-lock-in addition because it depends on the omitted hook-era implementation; retained only the DAQ notebook part of `6308a3c`.
- Removed measurement discovery and its measurement-only checks from the shared driver discovery helper/suite.
- Removed hook and waveform-contract regression tests that require the omitted virtual-driver implementation, while retaining the five base virtual-instrument policy tests and the dynamic virtual-driver contract suite.
- Resolved the sourcemeter conflict by retaining master's external-sample reads, non-SCPI inheritance and status methods, adding the historical channel validation. Master's sourcemeter regression tests are retained unchanged.

These scope adjustments are recorded in a separate cleanup commit after the replay. Intermediate historical test-consolidation commits are not claimed to be independently runnable without their successors.

## Validation baseline

On Python 3.13.2, the following completed with **965 passed and 93 failed**:

```powershell
$env:MPLBACKEND = 'Agg'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv\Scripts\python.exe -m pytest tests/driver tests/test_virtual_sourcemeter.py -q -p no:cacheprovider --tb=short
```

- 30 failures in the dynamic physical-driver suite: method implementation checks and stepper autodetection.
- 63 failures in the dynamic virtual-driver suite: method implementation checks.
- The common instrument, discovery and base virtual-instrument modules passed.
- All 18 master sourcemeter regression cases passed, including sample response, compliance, IV integration and method signatures.

Remaining contract failures are a cleanup baseline; this is not a passing release. No hardware or full-repository test run was performed. No source-branch test run was performed to attribute failures to historical commits.

## Original-to-new commit map

| Original | Replayed | Method | Original subject |
|---|---|---|---|
| `1844c3a` | `affd707` | Cherry-pick | clean up usb231.py and add big brother |
| `1f2e32d` | `e00aaa4` | Cherry-pick | fix emulators and usb120hs bug |
| `c2855cf` | `f0af7ae` | Driver/test paths only | Add USB-1208HS family and MOKE measurement framework |
| `d1bac1c` | `4606f4b` | Driver/test paths only | current test on MOKE, not tested on real hardware, need to integrate virtual dmm changes |
| `dfb6c8a` | `520db10` | Cherry-pick | docs(drivers): document list support for AUTODETECT_ID |
| `fbba227` | `917c444` | Driver/test paths only | fix(drivers/awg): un-indent output_trigger to class method and add contract tests (checkpoint 3) |
| `e9c6f47` | `c6547a2` | Cherry-pick | test(drivers/awg): unwrap AutoCheckMeta and assert VirtualAwg trigger effect (checkpoint 3 follow-up) |
| `48414d0` | `53f633d` | Driver/test paths only | fix(drivers/awg): repair configure_trigger trigger_source condition and audit affected drivers (checkpoint 4) |
| `a72bef8` | `6e5b85b` | Driver/test paths only | test(drivers/awg): audit concrete AWG and adapter trigger support with command assertions (checkpoint 4 follow-up) |
| `aa5ca95` | `a96a42c` | Driver/test paths only | test(drivers/awg): distinguish driver gaps from hardware capabilities |
| `695dcf7` | `1899c8c` | Driver/test paths only | feat(drivers/awg): add missing trigger capabilities and correct command mappings |
| `698eade` | `cfb5e20` | Driver/test paths only | feat(drivers/daq): add generic trigger pulses with timer and software backends |
| `4e41f47` | `3ffaa60` | Driver/test paths only | fix(drivers/sourcemeter): align VirtualSourcemeter with channel contract and audit Level 2 surface (checkpoint 5) |
| `ba3aa04` | `a9109bc` | Driver/test paths only | fix(drivers/sourcemeter): harden normalizer against silent drops, duplicate arguments, and excess arguments (checkpoint 5 follow-up) |
| `fa5d8b5` | `9e75174` | Driver/test paths only | refactor(drivers/sourcemeter): standardize channel-first interface and remove legacy compatibility layer |
| `05add94` | `a7fe00b` | Driver/test paths only | feat(drivers/dmm): audit DMM voltage configuration, overload normalization, and reset synchronization (checkpoint 6) |
| `bd0d10b` | `5743eec` | Driver/test paths only | feat(measurement): implement AMR setup role adapters and field-angle contract (checkpoint 21) |
| `da7daec` | `150a75d` | Driver/test paths only | clean up testing suite |
| `b53fb9b` | `24604b2` | Driver/test paths only | test: consolidate shared driver and measurement contracts |
| `f47a5aa` | `7ae1828` | Driver/test paths only | test: discover driver contracts and organize suites |
| `0dbbccb` | `7711c58` | Driver/test paths only | redefine instrument.py with new base commands |
| `b3fa4ec` | `e5ad710` | Cherry-pick | add autodetect ID to base instrument class as well and created dynamic tests for physical and virtual drivers, still WIP |
| `bc035cd` | `477f979` | Cherry-pick | cleaned up driver tests, may need to remove test_virtual_instrument |
| `6308a3c` | `864395b` | Driver/test paths only | current WIP |
