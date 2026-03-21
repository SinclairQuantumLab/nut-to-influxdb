# NUT UPS Readings Relay to InfluxDB

A small Python script that polls a UPS exposed by NUT and relays its readings to InfluxDB. The basic data flow is: **UPS → NUT → this app → InfluxDB**.

> **NOTE**:
> NUT (Network UPS Tools) is the standard open-source software layer that lets a computer talk to a UPS.
> It handles communication with the UPS, exposes the UPS status in a standard way, and lets other tools read it.
> For many USB-connected UPS units (e.g., from APC), the UPS appears as a **USB HID** device, a standard USB device class defined by the USB Implementers Forum (USB-IF), and NUT reads it through the corresponding standard driver.


## Setup

1. Make sure NUT is already working before running this relay. See [Appendix](#appendix-local-nut-setup) to setup and validate an NUT. For example, the following should succeed to proceed:

    ```bash
    $ upsc <ups_name>@localhost
    ```

2. Install dependencies.

    - With `uv`:

        ```bash
        $ uv sync
        ```

    Or 
    
    - with a virtual environment:

        ```bash
        $ python3 -m venv .venv
        $ source .venv/bin/activate
        $ pip install -e .
        ```

3. Use `pytest_connection_test.py` or `test_connection.py` to test if the app can access NUT successfully.

```bash
$ uv run pytest pytest_connection_test.py -v

# OR

$ uv run test_connection.py
```


## How to run

Run the main relay:

With `uv`:

```bash
$ uv run main.py
```

Or with a virtual environment:

```bash
$ source .venv/bin/activate
$ python main.py
```

## Data written to InfluxDB

Measurement name: `NUT_UPS`

Typical tags:
- `ups_name`
- `nut_host`
- `DeviceManufacturer`
- `DeviceModel`
- `DeviceSerial`
- `DeviceDescription`

Typical fields:
- `UPSStatus`
- `OnLine`
- `OnBattery`
- `LowBattery`
- `Charging`
- `Discharging`
- `ReplaceBattery`
- `Overloaded`
- `BatteryCharge[%]`
- `BatteryRuntime[s]`
- `BatteryVoltage[V]`
- `InputVoltage[V]`
- `InputFrequency[Hz]`
- `OutputVoltage[V]`
- `OutputFrequency[Hz]`
- `Load[%]`
- `RealPower[W]`
- `Temperature[degC]`

Unavailable fields are skipped.


## Appendix: Local NUT setup

This relay expects that a working NUT installation already exists and that the target UPS is exposed through `upsd`. The relay itself does not install or manage NUT. This appendix documents one practical setup path that was used and tested during development on a Debian or Raspberry Pi OS system with an APC UPS connected by USB.

### 1. Confirm that the UPS is visible over USB

First, make sure the operating system can see the UPS at all.

```bash
$ lsusb
```

For the APC unit used during development, the UPS appeared as something like:

```text
Bus 001 Device 004: ID 051d:0003 American Power Conversion Uninterruptible Power Supply
```

The important part to note for following steps:
- Bus #: 001
- Device #: 004
- Vendor ID: `051d`
- Product ID = `0003`

The serial number of the UPS can be further obtained using the bus and device # obtained above.

```bash
$ sudo lsusb -s <bus num>:<device num> -v | grep iSerial
  iSerial                 3 AS2533366439 
```


### 2. Install NUT

Install the base NUT packages:

```bash
$ sudo apt update
$ sudo apt install nut nut-client nut-server
```

### 3. Configure NUT standalone mode

Edit `/etc/nut/nut.conf`:

```bash
$ sudo nano /etc/nut/nut.conf
```

Use:

```ini
MODE=standalone
```

This is the simplest mode when the UPS is directly connected to the local machine by USB.

### 4. Configure the UPS in `ups.conf`

Edit `/etc/nut/ups.conf`:

```bash
$ sudo nano /etc/nut/ups.conf
```

A minimal working example:


```ini
[<ups name>]
    driver = <driver name>
    port = <port address>
    vendorid = <4-digit hex codes>
    productid = <4-digit hex codes>
    serial = <serial number>
    desc = "<string>"
```

- `<ups name>`: the UPS name that will later be used in commands such as `upsc <ups_name>@localhost`.
    - Recommended value: SN_\<serial number of the ups; see below\>.
- `<driver name>`: the name of the driver, a compiled binary file located on your system (usually in `/lib/nut/` or `/usr/lib/nut/`) for the UPS.
    - Recommended value: `usbhid-ups` covers the most of modern USB UPS units using the standard HID protocol.
- `<port address>`: port to connect to the ups.
    - USB: set `auto`. It will scan the system's hardware buses to find a device with given serial number.
    - Serial: /dev/ttyS0
    - Network: <network address (e.g. ip address)>
- `vendorid` & `productid`: 4 hex digits obtained in [Step 1](#1-confirm-that-the-ups-is-visible-over-usb) via `lsusb`. Not always strictly required, but they can make troubleshooting easier and avoid ambiguity.
- `serial`: the serial number of the UPS obtained in [Step 1](#1-confirm-that-the-ups-is-visible-over-usb).
- `desc`: description string in a double quotation pair.
    - Recommended value: Product name and model #.

The below is an example configuration.

```ini
[SN_AS2533366439]
    driver = usbhid-ups
    port = auto
    vendorid = 051d
    productid = 0003
    desc = "APC Smart-UPS On-Line SRT2200RMXLA"
```


### 5. Add a udev rule so NUT can access the UPS

A common failure mode is that `lsusb` sees the UPS but the NUT driver cannot open it because of USB permission problems.

Create a udev rules file:

```bash
$ sudo nano /etc/udev/rules.d/99-nut-apc-ups.rules
```

Use:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="051d", ATTR{idProduct}=="0003", MODE="0660", GROUP="nut"
SUBSYSTEMS=="usb", ATTRS{idVendor}=="051d", ATTRS{idProduct}=="0003", MODE="0660", GROUP="nut"
```

Then make sure the `nut` group exists:

```bash
$ getent group nut || sudo groupadd nut
```

Reload the rules:

```bash
$ sudo udevadm control --reload-rules
$ sudo udevadm trigger
```

After that, unplug and reconnect the UPS USB cable.

### 6. Test the USB driver directly

Before debugging the full NUT stack, test the UPS driver itself.

On many Debian or Raspberry Pi OS systems, `usbhid-ups` is not in the default shell `PATH`, so `sudo usbhid-ups ...` may fail with `command not found`. Find the actual binary location first:

```bash
$ dpkg -L nut | grep usbhid-ups
```

Typical locations are:

- `/lib/nut/usbhid-ups`
- `/usr/lib/nut/usbhid-ups`

Then run the driver directly with debug output. For example:

```bash
$ sudo /lib/nut/usbhid-ups -DDD -a <ups_name>
```

or

```bash
$ sudo /usr/lib/nut/usbhid-ups -DDD -a <ups_name>
```

If the USB permissions are correct, this should no longer fail with an access denied error.

### 7. Start and test the NUT services

Once the driver works, restart the NUT services:

```bash
$ sudo systemctl restart nut-server
$ sudo systemctl restart nut-monitor
```

Optionally enable them at boot:

```bash
$ sudo systemctl enable nut-server
$ sudo systemctl enable nut-monitor
```

Now test the configured UPS through `upsd`:

```bash
$ upsc <ups_name>@localhost
```

This is the most important functional test. If this command works and returns UPS variables, then the relay in this repo should also be able to query the UPS.

Typical output may include fields such as:

```text
device.mfr: American Power Conversion
device.model: Back-UPS Pro 1500
ups.status: OL
battery.charge: 100
battery.runtime: 1520
input.voltage: 120.0
ups.load: 18
```

### 8. Optional GUI tools for manual inspection

#### `nut-monitor`

`nut-monitor` was the most convenient GUI during setup and debugging.

Install it with:

```bash
$ sudo apt install nut-monitor
```

Then run:

```bash
$ NUT-Monitor
```

Use the following connection values:

- Host: `localhost`
- Port: `3493`
- UPS name: `<ups_name>`

This is a convenient way to confirm that NUT is working independently of the InfluxDB relay.

#### `nut-cgi`

If a browser-based view is preferred, `nut-cgi` can also be installed:

```bash
$ sudo apt install nut-cgi lighttpd
$ sudo lighty-enable-mod cgi
$ sudo systemctl restart lighttpd
```

Create `/etc/nut/hosts.conf`:

```bash
$ sudo nano /etc/nut/hosts.conf
```

Example content:

```ini
MONITOR myups "<ups_name>@localhost"
```

Then, depending on your CGI setup, open a URL similar to:

```text
http://<raspberry-pi-ip>/cgi-bin/upsstats.cgi?host=myups
```

This can be useful, but in practice `nut-monitor` was the more convenient tool during development.

### 9. Common troubleshooting notes

#### `Error: no UPS definitions found in ups.conf`

This usually means NUT is reading the wrong file, the file name is wrong, the file was not saved, or the file contents are malformed. Re-check `/etc/nut/ups.conf`.

#### `libusb1: Could not open any HID devices: insufficient permissions on everything`

This indicates a USB permission problem. Re-check:

- the udev rule
- the correct `idVendor` and `idProduct`
- whether the `nut` group exists
- whether the UPS was unplugged and reconnected after reloading rules

#### `No matching HID UPS found`

This can happen when the UPS is present but the driver still cannot open it. It is often another symptom of the same permissions problem above.

#### `sudo: usbhid-ups: command not found`

The binary exists, but it is not in the shell `PATH`. Use its absolute path as described above.

#### `upsc <ups_name>@localhost` fails even though the driver seems fine

Re-check:

- `MODE=standalone` in `/etc/nut/nut.conf`
- the UPS name in `/etc/nut/ups.conf`
- that `nut-server` and `nut-monitor` were restarted
- that the UPS name used in `upsc` matches the section name in `ups.conf`

### 10. Final readiness check for this relay

Before running `main.py`, the following command should work:

```bash
$ upsc <ups_name>@localhost
```

If that succeeds, the relay is usually ready to run.