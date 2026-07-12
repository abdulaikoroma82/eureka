"""Tests for the hosted-deployment session isolation in the Streamlit UI.

Once the app runs on a shared server for multiple users, every browser
session must get its own private output directory - not the shared
default ``output/`` folder, which would let one user's generated package
(potentially containing sensitive survey content) collide with or be
readable alongside another's."""

import tempfile
import time
from pathlib import Path

import pytest

from xlsform_studio.app import ui


@pytest.fixture
def fake_session_state():
    """Swap st.session_state for a plain dict for the duration of one test,
    then restore Streamlit's real SessionStateProxy - st is the shared,
    global streamlit module, so leaving the swap in place would leak into
    every test that runs afterward in the same pytest process."""
    original = ui.st.session_state
    try:
        yield
    finally:
        ui.st.session_state = original


def test_session_output_dir_is_isolated_per_session(fake_session_state):
    """Two independent 'sessions' (simulated via separate session_state
    dicts, since st.session_state only supports dict-like access) must
    get two different, both-existing directories."""
    session_a: dict = {}
    session_b: dict = {}

    ui.st.session_state = session_a
    dir_a = ui._session_output_dir()
    ui.st.session_state = session_b
    dir_b = ui._session_output_dir()

    assert dir_a != dir_b
    assert dir_a.is_dir()
    assert dir_b.is_dir()
    assert dir_a.name.startswith(ui._SESSION_DIR_PREFIX)


def test_session_output_dir_reused_across_reruns(fake_session_state):
    """The SAME session must get the SAME directory on a later call
    (Streamlit reruns the script on every interaction)."""
    session: dict = {}
    ui.st.session_state = session
    first = ui._session_output_dir()
    second = ui._session_output_dir()
    assert first == second


def test_sweep_removes_only_stale_prefixed_dirs():
    stale = Path(tempfile.mkdtemp(prefix=ui._SESSION_DIR_PREFIX))
    fresh = Path(tempfile.mkdtemp(prefix=ui._SESSION_DIR_PREFIX))
    unrelated = Path(tempfile.mkdtemp(prefix="not_xlsform_studio_"))

    old_time = time.time() - (ui._SESSION_DIR_MAX_AGE_HOURS + 1) * 3600
    import os
    os.utime(stale, (old_time, old_time))

    try:
        ui._sweep_stale_session_dirs()
        assert not stale.exists()
        assert fresh.exists()
        assert unrelated.exists()
    finally:
        for d in (fresh, unrelated):
            if d.exists():
                import shutil
                shutil.rmtree(d, ignore_errors=True)
