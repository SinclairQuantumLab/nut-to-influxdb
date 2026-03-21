"""
test_connection.py

Minimal sequential test script for checking connectivity to a NUT UPS.

This script:
1. Verifies that the `upsc` command exists
2. Calls `upsc apc@localhost`
3. Prints the raw output
4. Parses the output into a dictionary
5. Prints a few representative fields for quick inspection

This version is intentionally simple and linear for debugging.
"""

import shutil
import subprocess
import sys


# Configuration
UPS_NAME = "apc"
UPS_HOST = "localhost"
UPS_TARGET = f"{UPS_NAME}@{UPS_HOST}"

print("=== NUT connection test starting ===")
print(f"Target UPS: {UPS_TARGET}")
print()

# Step 1: Check whether the `upsc` command is available.
print("Step 1: Checking whether `upsc` is installed and visible in PATH...")
upsc_path = shutil.which("upsc")

if upsc_path is None:
    print("ERROR: `upsc` command was not found in PATH.")
    print("Make sure NUT client tools are installed and `upsc` works in the shell.")
    sys.exit(1)

print(f"`upsc` found at: {upsc_path}")
print()

# Step 2: Run `upsc` and capture stdout/stderr.
print(f"Step 2: Running `{upsc_path} {UPS_TARGET}` ...")

result = subprocess.run(
    [upsc_path, UPS_TARGET],
    capture_output=True,
    text=True,
)

print(f"Return code: {result.returncode}")
print()

# Print stderr first if present, since it often explains failures.
if result.stderr.strip():
    print("=== STDERR ===")
    print(result.stderr.strip())
    print()

# If `upsc` failed, stop here.
if result.returncode != 0:
    print("ERROR: `upsc` command failed.")
    print("Check that:")
    print("  - NUT server is running")
    print("  - the UPS name is correct")
    print("  - the UPS is reachable from this machine")
    sys.exit(result.returncode)

# Step 3: Print the raw stdout for direct inspection.
print("Step 3: Raw `upsc` output:")
print("=== STDOUT ===")
print(result.stdout.strip())
print()

# Step 4: Parse `key: value` lines into a dictionary.
print("Step 4: Parsing output into a dictionary...")

ups_data = {}

for line in result.stdout.splitlines():
    line = line.strip()

    # Skip empty lines.
    if not line:
        continue

    # NUT `upsc` output is normally `key: value`.
    if ":" not in line:
        print(f"Skipping unparsable line: {line}")
        continue

    key, value = line.split(":", 1)
    key = key.strip()
    value = value.strip()

    ups_data[key] = value

print(f"Parsed {len(ups_data)} fields.")
print()

# Step 5: Print all parsed keys in sorted order.
print("Step 5: Parsed fields:")
for key in sorted(ups_data):
    print(f"{key} = {ups_data[key]}")
print()

# Step 6: Print a few commonly useful fields for quick confirmation.
print("Step 6: Quick summary of common fields:")
common_keys = [
    "device.mfr",
    "device.model",
    "ups.status",
    "battery.charge",
    "battery.runtime",
    "input.voltage",
    "ups.load",
]

for key in common_keys:
    print(f"{key}: {ups_data.get(key, '<not present>')}")
print()

print("=== NUT connection test completed successfully ===")