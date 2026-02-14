# Arducam OV5642 UDP Video Streaming

A MicroPython-based video streaming system using Arducam Mini 5MP Plus (OV5642) on ESP32-S3, with a Python desktop viewer.

## Overview

This project streams JPEG frames from an ESP32-S3 with Arducam camera over UDP to a desktop application with a simple GUI for viewing the live feed.


## Hardware Requirements

- ESP32-S3 DevKitC-1
- Arducam Mini 5MP Plus (OV5642)

## Wiring

| Arducam Pin | ESP32-S3 Pin |
|-------------|--------------|
| CS          | GPIO 9       |
| MOSI        | GPIO 10      |
| MISO        | GPIO 11      |
| SCK         | GPIO 12      |
| SDA         | GPIO 13      |
| SCL         | GPIO 14      |
| VCC         | 3.3V         |
| GND         | GND          |

The onboard NeoPixel LED (GPIO 38) indicates status:
- **Red**: Idle / Not streaming
- **Green**: Streaming active

## Project Structure

```
/
├── lib/
│   ├── Arducam.py       # Camera driver
│   └── OV5642_reg.py    # OV5642 register definitions
├── main.py              # ESP32 streaming firmware
└── cloud.py             # Desktop viewer application
```

## Installation

### ESP32-S3 Setup

#### Option A: Using esptool and mpremote (Command Line)

Install the required tools:
```bash
pip install esptool mpremote
```

1. Flash MicroPython firmware to your ESP32-S3:
   ```bash
   esptool.py --chip esp32s3 --port /dev/ttyUSB0 erase_flash
   esptool.py --chip esp32s3 --port /dev/ttyUSB0 write_flash -z 0 ESP32_GENERIC_S3-xxxxxxxx.bin
   ```

2. Upload the driver files:
   ```bash
   mpremote mkdir lib
   mpremote cp lib/Arducam.py :lib/Arducam.py
   mpremote cp lib/OV5642_reg.py :lib/OV5642_reg.py
   ```

3. Upload the main script:
   ```bash
   mpremote cp main.py :main.py
   ```

#### Option B: Using Thonny (GUI)

1. Download and install Thonny from: https://thonny.org

2. Download the MicroPython firmware for ESP32-S3 from: https://micropython.org/download/ESP32_GENERIC_S3/

3. Open Thonny, go to **Tools → Options → Interpreter** and select "MicroPython (ESP32)".

4. Click "Install or update MicroPython" to flash the firmware to your ESP32-S3.

5. Connect to your ESP32-S3.

6. In the file browser, create a `lib` folder on the device.

7. Upload `Arducam.py` and `OV5642_reg.py` to the `lib` folder.

8. Upload `main.py` to the root of the device.

### Desktop Viewer Setup

Install the required Python packages:
```bash
pip install pillow
```

## Configuration

### ESP32 (main.py)

Edit the following variables in `main.py`:

```python
WIFI_SSID = "Your_WiFi_Name"
WIFI_PASS = "Your_WiFi_Password"

SERVER_IP = "xxx.xxx.xxx.xxx"  # Your desktop IP address
SERVER_PORT = 4444
```

### Desktop Viewer (cloud.py)

Edit the ESP32's IP address in `cloud.py`:

```python
ESP_IP = "yyy.yyy.yyy.yyy"  # Your ESP32's IP address
PORT = 4444
```

## Usage

1. Power on the ESP32-S3. It will connect to WiFi and wait for commands.

2. Run the desktop viewer:
   ```bash
   python cloud.py
   ```

3. Click **START** to begin streaming.

4. Click **STOP** to stop streaming.

## Protocol

The system uses a simple UDP protocol:

**Commands (Desktop → ESP32):**
- `START` - Begin streaming
- `STOP` - Stop streaming

**Frame Packet (ESP32 → Desktop):**
| Byte | Description |
|------|-------------|
| 0    | Type (0x01 = JPEG frame) |
| 1-4  | JPEG size (big-endian) |
| 5+   | JPEG data |

## Troubleshooting

- **No frames received**: Verify IP addresses and ensure both devices are on the same network.
- **WiFi connect timeout**: Check SSID and password in `main.py`.
- **Camera not detected**: Verify wiring connections, especially I2C (SDA/SCL).
- **Choppy video**: Reduce resolution or increase the delay between frames.

## License

MIT
