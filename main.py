from machine import Pin, SPI, I2C
import time
import socket
import network
import ustruct
import neopixel

from Arducam import (
    Arducam, JPEG, OV5642,
    ARDUCHIP_TRIG, CAP_DONE_MASK, ARDUCHIP_TIM
)

# ----------------------------
# Client/Server Configuration
# ----------------------------
WIFI_SSID = "Network_name"
WIFI_PASS = "secret_password"

SERVER_IP = "xxx.xxx.xxx.xxx"
SERVER_PORT = 4444

# ----------------------------
# Board/Camera Configuration
# ----------------------------
SPI_ID   = 2
SPI_SCK  = 12
SPI_MOSI = 10
SPI_MISO = 11
CS_PIN   = 9

I2C_ID   = 0
I2C_SCL  = 14
I2C_SDA  = 13

LED_PIN = 38
led = neopixel.NeoPixel(Pin(LED_PIN), 1)

# ----------------------------
# Payload Configuration
# ----------------------------
MAX_PAYLOAD = 1200  # safe size to avoid UDP fragmentation

# ----------------------------
# Helper Function
# ----------------------------
def led_set(r, g, b):
    led[0] = (r, g, b)
    led.write()
    
# ----------------------------
# Networking Functions
# ----------------------------

def wifi_connect(ssid, password, timeout_s=20):
    print("Connecting WiFi...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    wlan.connect(ssid, password)

    t0 = time.ticks_ms()
    while True:
        if wlan.isconnected():
            break
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
            raise RuntimeError("WiFi connect timeout")
        time.sleep(0.2)

    ip = wlan.ifconfig()[0]
    print("WiFi OK. IP:", ip)
    return wlan

def sock_send_all(sock, data):
    # MicroPython sockets may not have sendall on all ports, so we loop.
    mv = memoryview(data)
    total = 0
    while total < len(data):
        sent = sock.send(mv[total:])
        if sent is None or sent == 0:
            raise OSError("Socket send failed")
        total += sent

def recv_line(sock, max_len=64):
    """
    Read a command line that ends with '\n'.
    Returns the line without trailing whitespace, or None if nothing received.
    """
    try:
        data = sock.recv(max_len)
    except OSError:
        return None

    if not data:
        # connection closed
        raise OSError("Socket closed by server")

    # handle cases where multiple commands arrive together
    # we only care about START/STOP, so just search inside:
    text = data.decode("ascii", "ignore").upper()
    if "START" in text:
        return "START"
    if "STOP" in text:
        return "STOP"
    return None

def send_frame_chunks(sock, server_ip, port, jpeg, frame_id):
    total = (len(jpeg) + MAX_PAYLOAD - 1) // MAX_PAYLOAD
    for chunk_id in range(total):
        start = chunk_id * MAX_PAYLOAD
        end = min(start + MAX_PAYLOAD, len(jpeg))
        payload = jpeg[start:end]

        # type(1)=0x01, frame_id(2), chunk_id(2), total(2), payload_len(2)
        header = b"\x01" + ustruct.pack(">HHHH", frame_id, chunk_id, total, len(payload))
        sock.sendto(header + payload, (server_ip, port))

# ----------------------------
# Camera Initialization + Capturing
# ----------------------------
def camera_init():
    print("Initializing camera...")
    spi = SPI(
        SPI_ID,
        baudrate=2_000_000,
        polarity=0, phase=0,
        sck=Pin(SPI_SCK),
        mosi=Pin(SPI_MOSI),
        miso=Pin(SPI_MISO),
    )
    i2c = I2C(I2C_ID, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=400_000)
    print("I2C scan:", [hex(x) for x in i2c.scan()])

    cam = Arducam(spi=spi, cs_pin=CS_PIN, i2c=i2c)
    cam.CameraType = OV5642
    cam.Set_Camera_mode(JPEG)

    cam.Camera_Detection()
    cam.Spi_Test(retries=5)
    cam.init()
    time.sleep(0.2)

    # Important (from your example): VSYNC active-low timing bit
    cam.Spi_write(ARDUCHIP_TIM, 0x02)
    time.sleep(0.05)

    print("Camera ready.")
    return cam

def capture_jpeg(cam, timeout_ms=3000):
    """
    Capture one JPEG frame and return bytes.
    Includes a timeout so it doesn't hang forever.
    """
    cam.flush_fifo()
    cam.clear_fifo_flag()
    cam.start_capture()

    t0 = time.ticks_ms()
    while not cam.get_bit(ARDUCHIP_TRIG, CAP_DONE_MASK):
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            return b""
        time.sleep(0.005)

    jpeg = cam.read_jpeg(max_size=None)
    return jpeg

# ----------------------------
# Main streaming loop
# ----------------------------
def main():
    led_set(255, 0, 0)  # RED idle

    wifi_connect(WIFI_SSID, WIFI_PASS)
    cam = camera_init()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP Socket
    sock.bind(("0.0.0.0", SERVER_PORT))   # listen START/STOP
    sock.settimeout(0.1)

    print("UDP control ready on port", SERVER_PORT)

    streaming = False

    while True:
        # Receive START/STOP
        try:
            data, addr = sock.recvfrom(64)
            cmd = data.decode("ascii", "ignore").strip().upper()
            if cmd == "START":
                streaming = True
                led_set(0, 255, 0)
                print("Streaming ON")
            elif cmd == "STOP":
                streaming = False
                led_set(255, 0, 0)
                print("Streaming OFF")
        except OSError:
            pass

        # Stream frames if enabled
        if streaming:
            jpeg = capture_jpeg(cam, timeout_ms=3000)
            if jpeg:
                # frame packet: type + size + jpeg
                packet = b"\x01" + ustruct.pack(">I", len(jpeg)) + jpeg
                sock.sendto(packet, (SERVER_IP, SERVER_PORT))
            time.sleep(0.05)

# Run
main()
