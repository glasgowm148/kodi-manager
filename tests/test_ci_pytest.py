"""A stalled child must leave a readable log and a failing CI result."""
import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("ci_pytest", Path(__file__).parents[1] / "scripts/ci_pytest.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("code", [0, 7])
def test_child_result_and_output_are_preserved(tmp_path, code):
    log = tmp_path / "pytest.log"
    command = [sys.executable, "-u", "-c", "import sys; print('synthetic result'); sys.exit(%d)" % code]
    assert runner.run_bounded(command, log, timeout=10) == code
    assert b"synthetic result" in log.read_bytes()


def test_stalled_child_is_killed_with_its_output_retained(tmp_path):
    log = tmp_path / "pytest.log"
    command = [sys.executable, "-u", "-c", "import time; print('synthetic stalled test'); time.sleep(60)"]
    assert runner.run_bounded(command, log, timeout=2) == 124
    assert b"synthetic stalled test" in log.read_bytes()
    assert b"terminated" in log.read_bytes()
