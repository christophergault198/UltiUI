"""Tests for the temperature setpoint + jog/home safety logic in routes/printer.py.

These endpoints let a user command real hardware (heaters, stepper motors),
so the two things worth pinning down with tests are: (1) temperature inputs
always get clamped into a safe range no matter what's sent, and (2)
movement commands are refused whenever the print job state isn't
affirmatively known to be safe (fail-safe allowlist, not a denylist).
"""
import routes.printer as printer_routes
from routes.printer import (
    BED_TEMP_RANGE,
    NOZZLE_TEMP_RANGE,
    _clamp,
    _JOG_UNSAFE_PRINT_STATES,
    _reject_if_unsafe_to_move,
)


def test_clamp_within_range_passes_through():
    assert _clamp(60.0, BED_TEMP_RANGE) == 60.0
    assert _clamp(200.0, NOZZLE_TEMP_RANGE) == 200.0


def test_clamp_bed_temperature_bounds():
    assert _clamp(-50.0, BED_TEMP_RANGE) == 0.0
    assert _clamp(999.0, BED_TEMP_RANGE) == 120.0


def test_clamp_nozzle_temperature_bounds():
    assert _clamp(-10.0, NOZZLE_TEMP_RANGE) == 0.0
    assert _clamp(1000.0, NOZZLE_TEMP_RANGE) == 280.0


def test_clamp_accepts_boundary_values():
    assert _clamp(0.0, BED_TEMP_RANGE) == 0.0
    assert _clamp(120.0, BED_TEMP_RANGE) == 120.0
    assert _clamp(280.0, NOZZLE_TEMP_RANGE) == 280.0


def test_unsafe_states_allowlist_blocks_active_print_states():
    for state in ('printing', 'pausing', 'paused', 'resuming',
                  'pre_print', 'post_print', 'wait_cleanup', 'wait_user_action'):
        assert state in _JOG_UNSAFE_PRINT_STATES


def test_unsafe_states_allowlist_permits_idle_states():
    # Anything not explicitly known-unsafe should NOT be in the blocklist,
    # e.g. 'idle' -- the printer with no job loaded.
    for state in ('idle', 'error', 'maintenance'):
        assert state not in _JOG_UNSAFE_PRINT_STATES


async def test_reject_if_unsafe_to_move_blocks_when_printing(monkeypatch):
    async def fake_state():
        return 'printing'
    monkeypatch.setattr(printer_routes, '_current_print_job_state', fake_state)

    result = await _reject_if_unsafe_to_move()
    assert result is not None
    assert result.status == 409


async def test_reject_if_unsafe_to_move_allows_when_idle(monkeypatch):
    async def fake_state():
        return 'idle'
    monkeypatch.setattr(printer_routes, '_current_print_job_state', fake_state)

    result = await _reject_if_unsafe_to_move()
    assert result is None


async def test_reject_if_unsafe_to_move_allows_when_no_job(monkeypatch):
    async def fake_state():
        return None
    monkeypatch.setattr(printer_routes, '_current_print_job_state', fake_state)

    result = await _reject_if_unsafe_to_move()
    assert result is None


async def test_reject_if_unsafe_to_move_fails_safe_on_unknown_state(monkeypatch):
    # _current_print_job_state returns 'unknown' when it couldn't reach the
    # printer at all -- treat that as unsafe rather than silently allowing
    # movement.
    async def fake_state():
        return 'unknown'
    monkeypatch.setattr(printer_routes, '_current_print_job_state', fake_state)

    result = await _reject_if_unsafe_to_move()
    assert result is not None
    assert result.status == 409
