"""
Contract tests for measurement lifecycle states, reservation, and run records.

Fulfills Checkpoint 8 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Legal forward transitions and strict rejection of illegal transitions;
- Synchronous reservation with UUID and monotonic generation counter;
- Rejection of concurrent reservations and idle-lease collisions;
- Stale token rejection and duplicate execution rejection;
- Stop control behavior across all lifecycle phases;
- RunRecord immutability, history accumulation, and repeat runs;
- Multi-threaded reservation concurrency and Stop-before-start race resolution;
- BaseMeasurement integration.
"""

from dataclasses import FrozenInstanceError
import threading
import time
from typing import List
import uuid
import pytest

from piec.measurement.contracts import (
    ConcurrentRunError,
    DuplicateExecutionError,
    IllegalStateTransitionError,
    LEGAL_TRANSITIONS,
    LifecycleCoordinator,
    ReservationToken,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyReport,
    SafetyStatus,
    StaleTokenError,
)
from piec.measurement.base import BaseMeasurement


# ============================================================================
# 1. State Enums and Legal Transitions
# ============================================================================

class TestRunStateTransitions:
    """Verify RunState definitions, properties, and strict transition validation."""

    def test_all_eleven_states_defined(self):
        expected_states = {
            "IDLE", "STARTING", "CONFIGURING", "RUNNING", "STOPPING",
            "SAFING", "ANALYZING", "SAVING", "COMPLETED", "ABORTED", "FAILED",
        }
        actual_states = {s.value for s in RunState}
        assert actual_states == expected_states

    def test_state_properties(self):
        assert RunState.IDLE.is_terminal is False
        assert RunState.IDLE.is_active is False

        assert RunState.STARTING.is_terminal is False
        assert RunState.STARTING.is_active is True

        assert RunState.RUNNING.is_terminal is False
        assert RunState.RUNNING.is_active is True

        assert RunState.COMPLETED.is_terminal is True
        assert RunState.COMPLETED.is_active is False

        assert RunState.ABORTED.is_terminal is True
        assert RunState.ABORTED.is_active is False

        assert RunState.FAILED.is_terminal is True
        assert RunState.FAILED.is_active is False

    @pytest.mark.parametrize(
        "source,target",
        [
            (RunState.IDLE, RunState.STARTING),
            (RunState.STARTING, RunState.CONFIGURING),
            (RunState.STARTING, RunState.STOPPING),
            (RunState.STARTING, RunState.FAILED),
            (RunState.CONFIGURING, RunState.RUNNING),
            (RunState.CONFIGURING, RunState.STOPPING),
            (RunState.CONFIGURING, RunState.SAFING),
            (RunState.RUNNING, RunState.STOPPING),
            (RunState.RUNNING, RunState.SAFING),
            (RunState.STOPPING, RunState.SAFING),
            (RunState.STOPPING, RunState.ABORTED),
            (RunState.SAFING, RunState.ANALYZING),
            (RunState.SAFING, RunState.SAVING),
            (RunState.SAFING, RunState.COMPLETED),
            (RunState.SAFING, RunState.ABORTED),
            (RunState.SAFING, RunState.FAILED),
            (RunState.ANALYZING, RunState.SAVING),
            (RunState.ANALYZING, RunState.COMPLETED),
            (RunState.ANALYZING, RunState.FAILED),
            (RunState.SAVING, RunState.COMPLETED),
            (RunState.SAVING, RunState.ABORTED),
            (RunState.SAVING, RunState.FAILED),
            (RunState.COMPLETED, RunState.STARTING),
            (RunState.ABORTED, RunState.STARTING),
            (RunState.FAILED, RunState.STARTING),
        ],
    )
    def test_legal_forward_transitions_succeed(self, source, target):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = source
        coordinator.transition_to(target)
        assert coordinator.run_state == target

    @pytest.mark.parametrize(
        "source,illegal_target",
        [
            (RunState.IDLE, RunState.CONFIGURING),
            (RunState.IDLE, RunState.RUNNING),
            (RunState.IDLE, RunState.COMPLETED),
            (RunState.STARTING, RunState.RUNNING),
            (RunState.STARTING, RunState.ANALYZING),
            (RunState.STARTING, RunState.COMPLETED),
            (RunState.CONFIGURING, RunState.COMPLETED),
            (RunState.CONFIGURING, RunState.ABORTED),
            (RunState.CONFIGURING, RunState.FAILED),
            (RunState.RUNNING, RunState.ANALYZING),
            (RunState.RUNNING, RunState.COMPLETED),
            (RunState.STOPPING, RunState.RUNNING),
            (RunState.STOPPING, RunState.CONFIGURING),
            (RunState.STOPPING, RunState.COMPLETED),
            (RunState.SAFING, RunState.RUNNING),
            (RunState.ANALYZING, RunState.RUNNING),
            (RunState.SAVING, RunState.ANALYZING),
            (RunState.COMPLETED, RunState.RUNNING),
            (RunState.COMPLETED, RunState.CONFIGURING),
            (RunState.ABORTED, RunState.SAVING),
            (RunState.FAILED, RunState.CONFIGURING),
        ],
    )
    def test_illegal_transitions_raise(self, source, illegal_target):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = source
        with pytest.raises(IllegalStateTransitionError, match="Illegal state transition"):
            coordinator.transition_to(illegal_target)


# ============================================================================
# 2. Reservation Contract and Token Generation
# ============================================================================

class TestReservationContract:
    """Verify synchronous reservation, monotonic generations, and UUIDs."""

    def test_reserve_from_idle(self):
        coordinator = LifecycleCoordinator()
        assert coordinator.run_state == RunState.IDLE
        assert coordinator.generation == 0

        token = coordinator.reserve()
        assert isinstance(token, ReservationToken)
        assert token.generation == 1
        assert isinstance(uuid.UUID(token.run_id), uuid.UUID)
        assert coordinator.run_state == RunState.STARTING
        assert coordinator.active_token == token

    @pytest.mark.parametrize(
        "terminal_state", [RunState.COMPLETED, RunState.ABORTED, RunState.FAILED]
    )
    def test_reserve_from_terminal_states_increments_generation(self, terminal_state):
        coordinator = LifecycleCoordinator()
        token1 = coordinator.reserve()
        coordinator._run_state = terminal_state

        token2 = coordinator.reserve()
        assert token2.generation == 2
        assert token2.run_id != token1.run_id
        assert coordinator.run_state == RunState.STARTING
        assert coordinator.generation == 2

    @pytest.mark.parametrize(
        "active_state",
        [
            RunState.STARTING,
            RunState.CONFIGURING,
            RunState.RUNNING,
            RunState.STOPPING,
            RunState.SAFING,
            RunState.ANALYZING,
            RunState.SAVING,
        ],
    )
    def test_concurrent_reserve_while_active_raises(self, active_state):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = active_state
        with pytest.raises(ConcurrentRunError, match="Cannot reserve run while another run is active"):
            coordinator.reserve()

    def test_reserve_clears_stop_and_pause_events(self):
        coordinator = LifecycleCoordinator()
        coordinator.reserve()  # now in STARTING
        coordinator.request_stop()  # sets stop_event and transitions to STOPPING
        coordinator.request_pause(True)
        coordinator._run_state = RunState.COMPLETED

        assert coordinator.is_stop_requested is True
        assert coordinator.is_pause_requested is True

        token = coordinator.reserve()
        assert coordinator.is_stop_requested is False
        assert coordinator.is_pause_requested is False


# ============================================================================
# 3. Token Validation: Stale, Mismatched, and Duplicate Rejection
# ============================================================================

class TestTokenValidation:
    """Verify strict token validation before execution begins."""

    def test_valid_token_consumes_successfully(self):
        coordinator = LifecycleCoordinator()
        token = coordinator.reserve()
        # Should not raise
        coordinator.validate_token(token)

    def test_duplicate_execution_rejected(self):
        coordinator = LifecycleCoordinator()
        token = coordinator.reserve()
        coordinator.validate_token(token)

        with pytest.raises(DuplicateExecutionError, match="has already begun execution"):
            coordinator.validate_token(token)

    def test_stale_token_rejected(self):
        coordinator = LifecycleCoordinator()
        stale_token = coordinator.reserve()
        coordinator._run_state = RunState.COMPLETED
        # Newer reservation
        newer_token = coordinator.reserve()

        with pytest.raises(StaleTokenError, match="is stale"):
            coordinator.validate_token(stale_token)

    def test_mismatched_run_id_rejected(self):
        coordinator = LifecycleCoordinator()
        token = coordinator.reserve()
        fake_token = ReservationToken(run_id=str(uuid.uuid4()), generation=token.generation)

        with pytest.raises(StaleTokenError, match="does not match active reservation"):
            coordinator.validate_token(fake_token)

    def test_invalid_token_type_rejected(self):
        coordinator = LifecycleCoordinator()
        coordinator.reserve()
        with pytest.raises(TypeError, match="Expected ReservationToken"):
            coordinator.validate_token("not_a_token")


# ============================================================================
# 4. Stop Control Contract
# ============================================================================

class TestStopControlContract:
    """Verify cooperative Stop semantics across all states."""

    @pytest.mark.parametrize(
        "active_state", [RunState.STARTING, RunState.CONFIGURING, RunState.RUNNING]
    )
    def test_stop_in_early_active_states_transitions_to_stopping(self, active_state):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = active_state
        assert coordinator.is_stop_requested is False

        coordinator.request_stop()
        assert coordinator.is_stop_requested is True
        assert coordinator.run_state == RunState.STOPPING

    def test_stop_in_stopping_is_idempotent(self):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = RunState.STOPPING
        coordinator.request_stop()
        assert coordinator.run_state == RunState.STOPPING

    @pytest.mark.parametrize(
        "safing_state", [RunState.SAFING, RunState.ANALYZING, RunState.SAVING]
    )
    def test_stop_in_safing_analyzing_saving_does_not_regress_state(self, safing_state):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = safing_state

        coordinator.request_stop()
        assert coordinator.is_stop_requested is True
        assert coordinator.run_state == safing_state

    @pytest.mark.parametrize(
        "dormant_state", [RunState.IDLE, RunState.COMPLETED, RunState.ABORTED, RunState.FAILED]
    )
    def test_stop_in_dormant_states_is_ignored(self, dormant_state):
        coordinator = LifecycleCoordinator()
        coordinator._run_state = dormant_state

        coordinator.request_stop()
        assert coordinator.run_state == dormant_state


# ============================================================================
# 5. Idle Command Lease Contract
# ============================================================================

class TestIdleCommandLease:
    """Verify mutual exclusion between idle operations and run reservation."""

    def test_idle_lease_blocks_reservation(self):
        coordinator = LifecycleCoordinator()
        assert coordinator.run_state == RunState.IDLE

        with coordinator.idle_command_lease():
            with pytest.raises(ConcurrentRunError, match="idle shutdown lease is active"):
                coordinator.reserve()

        # Once lease is released, reservation succeeds
        token = coordinator.reserve()
        assert token.generation == 1

    def test_active_run_blocks_idle_lease(self):
        coordinator = LifecycleCoordinator()
        coordinator.reserve()
        assert coordinator.run_state == RunState.STARTING

        with pytest.raises(ConcurrentRunError, match="while run is active"):
            with coordinator.idle_command_lease():
                pass

    def test_nested_idle_lease_rejected(self):
        coordinator = LifecycleCoordinator()
        with coordinator.idle_command_lease():
            with pytest.raises(ConcurrentRunError, match="already active"):
                with coordinator.idle_command_lease():
                    pass


# ============================================================================
# 6. Run Records and Immutability
# ============================================================================

class TestRunRecordsAndHistory:
    """Verify RunRecord immutability, history accumulation, and safety reports."""

    def test_run_request_immutability(self):
        opts = {"voltage_limit": 10.0}
        request = RunRequest(save=True, options=opts)

        # Mutating original dict must not mutate request.options
        opts["voltage_limit"] = 999.0
        assert request.options["voltage_limit"] == 10.0

        # Attempting to mutate request attributes must raise
        with pytest.raises(FrozenInstanceError):
            request.save = False

    def test_run_record_immutability(self):
        safety = SafetyReport(
            status=SafetyStatus.SAFE,
            actions=(SafetyAction("disable_output", True, True, 0.05),),
            readback_verified=True,
        )
        record = RunRecord(
            run_id=str(uuid.uuid4()),
            generation=1,
            start_time=100.0,
            end_time=105.0,
            state=RunState.COMPLETED,
            safety=safety,
            save_requested=True,
            filename="test.csv",
        )
        with pytest.raises(FrozenInstanceError):
            record.filename = "other.csv"

    def test_record_run_updates_history_and_terminal_state(self):
        coordinator = LifecycleCoordinator()
        token = coordinator.reserve()
        coordinator.transition_to(RunState.CONFIGURING)
        coordinator.transition_to(RunState.RUNNING)
        coordinator.transition_to(RunState.SAFING)

        safety = SafetyReport(status=SafetyStatus.SAFE)
        record = RunRecord(
            run_id=token.run_id,
            generation=token.generation,
            start_time=time.time(),
            end_time=time.time() + 1.0,
            state=RunState.COMPLETED,
            safety=safety,
        )
        coordinator.record_run(record)

        assert coordinator.run_state == RunState.COMPLETED
        assert coordinator.safety_status == SafetyStatus.SAFE
        assert coordinator.last_run_record is record
        assert coordinator.run_records == (record,)

    def test_repeat_runs_accumulate_records(self):
        coordinator = LifecycleCoordinator()
        records: List[RunRecord] = []

        for gen in range(1, 4):
            token = coordinator.reserve()
            coordinator.transition_to(RunState.CONFIGURING)
            coordinator.transition_to(RunState.SAFING)
            rec = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=float(gen * 10),
                end_time=float(gen * 10 + 2),
                state=RunState.COMPLETED,
                safety=SafetyReport(status=SafetyStatus.SAFE),
            )
            coordinator.record_run(rec)
            records.append(rec)

        assert coordinator.generation == 3
        assert coordinator.run_records == tuple(records)
        assert coordinator.last_run_record == records[-1]

    def test_record_run_rejects_non_terminal_state(self):
        coordinator = LifecycleCoordinator()
        token = coordinator.reserve()
        invalid_record = RunRecord(
            run_id=token.run_id,
            generation=token.generation,
            start_time=1.0,
            state=RunState.RUNNING,  # not terminal!
        )
        with pytest.raises(ValueError, match="state must be terminal"):
            coordinator.record_run(invalid_record)


# ============================================================================
# 7. Multi-Threaded Concurrency
# ============================================================================

class TestThreadConcurrency:
    """Verify thread-safety of reservations and Stop-before-start race handling."""

    def test_concurrent_reservations_race_cleanly(self):
        coordinator = LifecycleCoordinator()
        successful_tokens = []
        errors = []

        def worker():
            try:
                tok = coordinator.reserve()
                successful_tokens.append(tok)
            except ConcurrentRunError as err:
                errors.append(err)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 thread must have succeeded
        assert len(successful_tokens) == 1
        assert len(errors) == 9
        assert coordinator.run_state == RunState.STARTING
        assert coordinator.generation == 1

    def test_stop_before_start_race_resolution(self):
        coordinator = LifecycleCoordinator()
        # 1. UI thread reserves synchronously
        token = coordinator.reserve()
        assert coordinator.run_state == RunState.STARTING

        # 2. Stop clicked before worker thread executes
        coordinator.request_stop()
        assert coordinator.run_state == RunState.STOPPING
        assert coordinator.is_stop_requested is True

        # 3. Worker starts and validates token
        coordinator.validate_token(token)

        # 4. Worker detects Stop latched before I/O began -> transitions to ABORTED directly
        coordinator.transition_to(RunState.ABORTED)
        record = RunRecord(
            run_id=token.run_id,
            generation=token.generation,
            start_time=100.0,
            end_time=100.1,
            state=RunState.ABORTED,
            safety=SafetyReport(status=SafetyStatus.NOT_NEEDED),
            save_requested=False,
        )
        coordinator.record_run(record)

        assert coordinator.run_state == RunState.ABORTED
        assert coordinator.safety_status == SafetyStatus.NOT_NEEDED


# ============================================================================
# 8. BaseMeasurement Class Integration
# ============================================================================

class TestBaseMeasurementIntegration:
    """Verify BaseMeasurement provides unified lifecycle properties and controls."""

    def test_initial_state_and_properties(self):
        meas = BaseMeasurement()
        assert meas.run_state == RunState.IDLE
        assert meas.safety_status == SafetyStatus.UNKNOWN
        assert meas.last_run_record is None
        assert meas.run_records == ()
        assert meas.active_token is None
        assert meas.filename is None
        assert meas.partial_filename is None
        assert meas.data is None
        assert meas.raw_data is None

    def test_pause_unsupported_by_default(self):
        meas = BaseMeasurement()
        assert meas.supports_pause is False
        with pytest.raises(NotImplementedError, match="does not support cooperative pause"):
            meas.request_pause(True)

    def test_pause_supported_when_enabled(self):
        class PausableMeasurement(BaseMeasurement):
            supports_pause = True

        meas = PausableMeasurement()
        meas.request_pause(True)
        assert meas._coordinator.is_pause_requested is True
        meas.request_pause(False)
        assert meas._coordinator.is_pause_requested is False

    def test_full_protected_lifecycle_walkthrough(self):
        meas = BaseMeasurement()
        token = meas._reserve()
        assert meas.run_state == RunState.STARTING

        meas._validate_token(token)
        meas._transition_to(RunState.CONFIGURING)
        assert meas.run_state == RunState.CONFIGURING

        meas._transition_to(RunState.RUNNING)
        assert meas.run_state == RunState.RUNNING

        meas._transition_to(RunState.SAFING)
        assert meas.run_state == RunState.SAFING

        meas._transition_to(RunState.ANALYZING)
        assert meas.run_state == RunState.ANALYZING

        meas._transition_to(RunState.SAVING)
        assert meas.run_state == RunState.SAVING

        rec = RunRecord(
            run_id=token.run_id,
            generation=token.generation,
            start_time=1.0,
            end_time=2.0,
            state=RunState.COMPLETED,
            safety=SafetyReport(status=SafetyStatus.SAFE),
        )
        meas._record_run(rec)

        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        assert meas.last_run_record is rec
        assert meas.run_records == (rec,)
