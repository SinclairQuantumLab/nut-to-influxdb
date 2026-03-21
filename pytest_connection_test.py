"""
Pytest tests for test_connection.py.

These tests treat test_connection.py as an executable script and validate:
1. It succeeds when `upsc apc@localhost` succeeds
2. It fails cleanly when `upsc` is missing
3. It fails cleanly when `upsc` returns a nonzero exit code
4. It parses and prints representative fields from valid NUT output

This approach is robust for the current sequential script style because
test_connection.py is not structured as importable functions.
"""

from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = PROJECT_ROOT / "test_connection.py"


def run_script_with_monkeypatched_sitecustomize(tmp_path, sitecustomize_code):
    """
    Run test_connection.py in a subprocess while injecting monkeypatches through
    sitecustomize.py.

    Python automatically imports sitecustomize on startup if it is found on
    sys.path, so this lets us patch shutil.which and subprocess.run before
    the script executes.
    """
    sitecustomize_path = tmp_path / "sitecustomize.py"
    sitecustomize_path.write_text(sitecustomize_code, encoding="utf-8")

    env = {
        "PYTHONPATH": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=env,
    )
    return result


def test_script_exists():
    """Sanity check that the target script exists."""
    assert SCRIPT_PATH.exists(), f"Could not find script: {SCRIPT_PATH}"


def test_successful_connection(tmp_path):
    """The script should succeed and print expected summary fields when upsc works."""
    fake_stdout = """device.mfr: American Power Conversion
device.model: Back-UPS Pro 1500
ups.status: OL
battery.charge: 100
battery.runtime: 1520
input.voltage: 120.0
ups.load: 18
"""

    sitecustomize_code = f"""
import shutil
import subprocess

def fake_which(cmd):
    if cmd == "upsc":
        return "/usr/bin/upsc"
    return None

def fake_run(args, capture_output=False, text=False, **kwargs):
    class Result:
        returncode = 0
        stdout = {fake_stdout!r}
        stderr = ""
    return Result()

shutil.which = fake_which
subprocess.run = fake_run
"""

    result = run_script_with_monkeypatched_sitecustomize(tmp_path, sitecustomize_code)

    assert result.returncode == 0
    assert "NUT connection test completed successfully" in result.stdout
    assert "device.mfr = American Power Conversion" in result.stdout
    assert "device.model = Back-UPS Pro 1500" in result.stdout
    assert "ups.status: OL" in result.stdout
    assert "battery.charge: 100" in result.stdout


def test_missing_upsc_command(tmp_path):
    """The script should exit with code 1 if `upsc` is not found."""
    sitecustomize_code = """
import shutil

def fake_which(cmd):
    return None

shutil.which = fake_which
"""

    result = run_script_with_monkeypatched_sitecustomize(tmp_path, sitecustomize_code)

    assert result.returncode == 1
    assert "`upsc` command was not found in PATH" in result.stdout


def test_upsc_nonzero_exit(tmp_path):
    """The script should fail if `upsc` returns a nonzero exit code."""
    sitecustomize_code = """
import shutil
import subprocess

def fake_which(cmd):
    if cmd == "upsc":
        return "/usr/bin/upsc"
    return None

def fake_run(args, capture_output=False, text=False, **kwargs):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "Error: Data stale"
    return Result()

shutil.which = fake_which
subprocess.run = fake_run
"""

    result = run_script_with_monkeypatched_sitecustomize(tmp_path, sitecustomize_code)

    assert result.returncode == 1
    assert "ERROR: `upsc` command failed." in result.stdout
    assert "=== STDERR ===" in result.stdout
    assert "Error: Data stale" in result.stdout


def test_unparsable_lines_are_skipped(tmp_path):
    """Lines without ':' should be skipped without crashing."""
    fake_stdout = """device.mfr: American Power Conversion
THIS LINE IS BAD
ups.status: OL
"""

    sitecustomize_code = f"""
import shutil
import subprocess

def fake_which(cmd):
    if cmd == "upsc":
        return "/usr/bin/upsc"
    return None

def fake_run(args, capture_output=False, text=False, **kwargs):
    class Result:
        returncode = 0
        stdout = {fake_stdout!r}
        stderr = ""
    return Result()

shutil.which = fake_which
subprocess.run = fake_run
"""

    result = run_script_with_monkeypatched_sitecustomize(tmp_path, sitecustomize_code)

    assert result.returncode == 0
    assert "Skipping unparsable line: THIS LINE IS BAD" in result.stdout
    assert "device.mfr = American Power Conversion" in result.stdout
    assert "ups.status = OL" in result.stdout