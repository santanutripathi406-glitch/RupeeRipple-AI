"""Headless Streamlit run of every page (no API key set)."""
import glob
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = ["app.py"] + [str(pathlib.Path(p).relative_to(ROOT)) for p in sorted(glob.glob(str(ROOT / "pages" / "*.py")))]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_simulator_delay_changes_results_and_state_is_shared():
    at = AppTest.from_file(str(ROOT / "pages" / "3_Ripple_Simulator.py"), default_timeout=120).run()
    delay = [s for s in at.slider if s.label == "Payment delay (days)"][0]
    first = {m.label: m.value for m in at.metric}
    delay.set_value(0).run()
    zero = {m.label: m.value for m in at.metric}
    assert zero["Days below buffer"] == "0" or zero["Days below buffer"] == 0
    assert first["Days below buffer"] != zero["Days below buffer"]
    assert at.session_state["sim_cfg"]["delay_days"] == 0
