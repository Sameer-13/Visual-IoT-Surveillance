import socket
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import io

ESP_IP = "yyy.yyy.yyy.yyy"
PORT = 4444

# Shared frame buffer
latest_jpeg = None
latest_ts = 0.0
lock = threading.Lock()
running = True


def udp_receiver():
    """Background thread: receive UDP packets and store latest JPEG."""
    global latest_jpeg, latest_ts

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    sock.settimeout(0.5)

    print(f"[UDP] Listening on 0.0.0.0:{PORT}")

    while running:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except Exception:
            break

        # Accept only ESP packets
        if addr[0] != ESP_IP:
            continue

        # Expect at least: type(1) + size(4)
        if len(data) < 5:
            continue

        if data[0] != 0x01:
            continue

        size = struct.unpack(">I", data[1:5])[0]
        jpeg = data[5:]

        if len(jpeg) != size:
            continue

        with lock:
            latest_jpeg = jpeg
            latest_ts = time.time()

    sock.close()


def send_cmd(cmd: str):
    """Send START/STOP to ESP32 via UDP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(cmd.encode("ascii"), (ESP_IP, PORT))
    s.close()
    print(f"[CTRL] Sent {cmd} to {ESP_IP}:{PORT}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Visual IoT Surveillance")
        self.geometry("900x600")

        # Top controls
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        self.status_var = tk.StringVar(value="Idle (press START)")
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.LEFT)

        ttk.Button(top, text="START", command=self.on_start).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top, text="STOP", command=self.on_stop).pack(side=tk.RIGHT, padx=5)

        # Video area
        self.image_label = ttk.Label(self)
        self.image_label.pack(side=tk.TOP, expand=True, fill=tk.BOTH, padx=10, pady=10)

        self._tk_img = None  
        self.after(50, self.update_frame)  # UI refresh loop

    def on_start(self):
        send_cmd("START")
        self.status_var.set("START sent. Waiting for frames...")

    def on_stop(self):
        send_cmd("STOP")
        self.status_var.set("STOP sent. (stream should stop)")

    def update_frame(self):
        """Update displayed image if a new frame is available."""
        global latest_jpeg, latest_ts

        frame = None
        ts = 0.0
        with lock:
            if latest_jpeg is not None:
                frame = latest_jpeg
                ts = latest_ts

        if frame:
            try:
                img = Image.open(io.BytesIO(frame))
                # Resize to fit window
                w = self.winfo_width() - 40
                h = self.winfo_height() - 120
                if w > 50 and h > 50:
                    img.thumbnail((w, h))
                self._tk_img = ImageTk.PhotoImage(img)
                self.image_label.configure(image=self._tk_img)
                self.status_var.set(time.strftime("Receiving… last frame %H:%M:%S", time.localtime(ts)))
            except Exception as e:
                self.status_var.set(f"Decode error: {e}")

        self.after(50, self.update_frame)


if __name__ == "__main__":
    # Start UDP receiver thread
    t = threading.Thread(target=udp_receiver, daemon=True)
    t.start()

    app = App()
    try:
        app.mainloop()
    finally:
        running = False
