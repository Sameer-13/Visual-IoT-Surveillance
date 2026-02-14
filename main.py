# main.py (MicroPython on ESP32-S3)
#
# Visual IoT Surveillance System (Edge Client)
# - Connect to WiFi
# - Connect to PC "cloud" server via TCP port 4444
# - Wait for commands: "START\n" and "STOP\n"
# - When START: LED -> GREEN and stream JPEG frames
# - When STOP:  LED -> RED and stop streaming
#
# Frame format sent to server (recommended):
#   [4-byte big-endian length][JPEG bytes]
#
# Tested API usage follows your provided Arducam.py + main_example.py style:
#   cam.capture()
#   jpeg = cam.read_jpeg()

import time
import socket
import struct
import network
import neopixel
from machine import Pin, SPI, I2C

from Arducam import (
    Arducam, JPEG, OV5642, OV2640,
    ARDUCHIP_TIM
)

# ---------- USER SETTINGS ----------
WIFI_SSID = "Sm13"
WIFI_PASS = "sam2003wm"

SERVER_IP   = "192.168.1.15"   # <-- change to your PC IP
SERVER_PORT = 4444

CAMERA_TYPE = OV5642

# Limit JPEG to reduce MemoryError risk (Arducam default is 256KB)
MAX_JPEG_BYTES = 120 * 1024

# Target frames per second (approx). Increase if your link is fast.
TARGET_FPS = 8
# ----------------------------------

# Pins (match your provided main_example.py)
SPI_ID   = 2
SPI_SCK  = 12
SPI_MOSI = 10
SPI_MISO = 11
CS_PIN   = 9

I2C_ID   = 0
I2C_SCL  = 14
I2C_SDA  = 13

# NeoPixel built-in LED used in your example (Pin 38, 1 pixel)
# If your board doesn't have NeoPixel there, switch to a normal Pin LED.
led = neopixel.NeoPixel(Pin(38), 1)

def led_off():
    led[0] = (0, 0, 0)
    led.write()

def led_red():
    led[0] = (255, 0, 0)
    led.write()

def led_green():
    led[0] = (0, 255, 0)
    led.write()


def connect_wifi(ssid: str, password: str) -> str:
    """Connect to WiFi and return IP address."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, password)

        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 20000:
                raise RuntimeError("WiFi connect timeout")
            time.sleep(0.2)

    ip = wlan.ifconfig()[0]
    print("WiFi connected, IP =", ip)
    return ip


def init_camera():
    """Initialize SPI/I2C and Arducam camera."""
    spi = SPI(
        SPI_ID,
        baudrate=8_000_000,
        polarity=0,
        phase=0,
        sck=Pin(SPI_SCK),
        mosi=Pin(SPI_MOSI),
        miso=Pin(SPI_MISO),
    )
    i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000)

    cam = Arducam(spi=spi, cs_pin=CS_PIN, i2c=i2c)
    cam.CameraType = CAMERA_TYPE
    cam.Set_Camera_mode(JPEG)

    # Detect + init
    cam.Camera_Detection()
    cam.Spi_Test(retries=5)
    cam.init()

    # # Reduce memory risk
    # try:
    #     cam.set_max_jpeg_size(MAX_JPEG_BYTES)
    # except Exception:
    #     pass

    # This timing bit was necessary in your example (VSYNC active-low)
    try:
        cam.Spi_write(ARDUCHIP_TIM, 0x02)
    except Exception:
        pass

    time.sleep(0.2)
    print("Camera initialized.")
    return cam


def connect_server(ip: str, port: int) -> socket.socket:
    """Connect to the cloud server via TCP."""
    print("Connecting to server %s:%d ..." % (ip, port))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect((ip, port))
    s.settimeout(2.0)
    print("Connected to server.")
    return s


def recv_line(sock: socket.socket) -> bytes:
    """
    Read until '\n'. Keeps it simple for START/STOP commands.
    Returns b'' on disconnect.
    """
    buf = bytearray()
    while True:
        try:
            b = sock.recv(1)
        except OSError:
            return b""
        if not b:
            return b""
        buf += b
        if b == b"\n":
            return bytes(buf)


def capture_jpeg(cam) -> bytes:
    """Capture one JPEG frame using Arducam API."""
    cam.capture()
    jpeg = cam.read_jpeg(max_size=MAX_JPEG_BYTES)
    return jpeg


def send_frame(sock: socket.socket, jpeg: bytes) -> bool:
    """Send one frame with 4-byte length prefix. Return False on failure."""
    if not jpeg:
        return True  # just skip empty frames
    try:
        sock.sendall(struct.pack(">I", len(jpeg)))
        sock.sendall(jpeg)
        return True
    except OSError:
        return False


def main():
    led_red()  # streaming must start OFF (RED)

    # 1) WiFi
    connect_wifi(WIFI_SSID, WIFI_PASS)

    # 2) Camera
    cam = init_camera()

    streaming = False
    sock = None

    # Simple reconnect loop (useful during debugging)
    while True:
        try:
            if sock is None:
                sock = connect_server(SERVER_IP, SERVER_PORT)

            # Wait for commands from server
            cmd = recv_line(sock)
            if cmd == b"":
                raise OSError("Disconnected")

            cmd = cmd.strip().upper()
            if cmd == b"START":
                streaming = True
                led_green()
                print("START received -> streaming ON")

            elif cmd == b"STOP":
                streaming = False
                led_red()
                print("STOP received -> streaming OFF")

            # If streaming is ON, send frames until STOP arrives
            while streaming:
                t0 = time.ticks_ms()

                # Non-blocking-ish check for STOP while streaming:
                # - Use short timeout; if nothing received, keep streaming.
                try:
                    sock.settimeout(0.001)
                    maybe = sock.recv(16)
                    if maybe:
                        # If the server sent STOP\n during streaming, handle it
                        if b"STOP" in maybe.upper():
                            streaming = False
                            led_red()
                            print("STOP received -> streaming OFF")
                            sock.settimeout(2.0)
                            break
                    sock.settimeout(2.0)
                except OSError:
                    sock.settimeout(2.0)

                jpeg = capture_jpeg(cam)
                ok = send_frame(sock, jpeg)
                if not ok:
                    raise OSError("Send failed")

                # FPS control
                frame_ms = time.ticks_diff(time.ticks_ms(), t0)
                target_ms = int(1000 / max(1, TARGET_FPS))
                if frame_ms < target_ms:
                    time.sleep_ms(target_ms - frame_ms)

        except Exception as e:
            print("Error:", e)
            streaming = False
            led_red()

            # Close socket and retry
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
            sock = None

            # Small backoff before reconnect
            time.sleep(1)


# Run
main()
