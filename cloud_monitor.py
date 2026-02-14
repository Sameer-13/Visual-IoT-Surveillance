# cloud.py  (Streamlit GUI + socket server)
# Run: streamlit run cloud.py
#
# Protocol (recommended):
# - ESP32 connects to this PC on TCP port 4444
# - Commands from PC -> ESP32: b"START\n" or b"STOP\n"
# - Frames from ESP32 -> PC: 4-byte big-endian length N, then N bytes of JPEG
#
# Notes:
# - Streamlit runs in a web app model; we use a background thread to accept the ESP32
#   and continuously read frames.
# - The GUI button toggles START/STOP and sends the command to ESP32 over the same TCP socket.

import socket
import struct
import threading
import time
from typing import Optional

import streamlit as st

HOST = "0.0.0.0"
PORT = 4444
SOCKET_TIMEOUT_S = 1.0

# ---------- Shared state (kept in st.session_state) ----------

def _init_state():
    ss = st.session_state
    ss.setdefault("server_running", False)
    ss.setdefault("server_thread", None)

    ss.setdefault("client_sock", None)          # type: Optional[socket.socket]
    ss.setdefault("client_addr", None)

    ss.setdefault("reader_thread", None)
    ss.setdefault("reader_running", False)

    ss.setdefault("streaming_on", False)
    ss.setdefault("last_frame_bytes", None)     # latest JPEG bytes from ESP32
    ss.setdefault("last_frame_ts", 0.0)
    ss.setdefault("status_msg", "Server stopped.")


# ---------- Socket helpers ----------

def _safe_close(sock: Optional[socket.socket]):
    try:
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            sock.close()
    except Exception:
        pass


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    """Receive exactly n bytes, or return None on disconnect/timeout."""
    data = bytearray()
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
        except socket.timeout:
            return None
        except Exception:
            return None
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def _send_cmd(cmd: str):
    """Send START/STOP to client if connected."""
    sock = st.session_state.client_sock
    if not sock:
        st.session_state.status_msg = "No ESP32 connected yet."
        return
    try:
        sock.sendall((cmd.strip().upper() + "\n").encode("ascii"))
        st.session_state.status_msg = f"Sent command: {cmd.upper()}"
    except Exception as e:
        st.session_state.status_msg = f"Failed to send command ({cmd}): {e}"
        _safe_close(sock)
        st.session_state.client_sock = None
        st.session_state.client_addr = None


# ---------- Background threads ----------

def _server_loop():
    """Accept exactly one ESP32 connection at a time."""
    ss = st.session_state

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    srv.settimeout(SOCKET_TIMEOUT_S)

    ss.status_msg = f"Server listening on {HOST}:{PORT} (waiting for ESP32)..."

    try:
        while ss.server_running:
            # If already connected, just wait a bit.
            if ss.client_sock is not None:
                time.sleep(0.2)
                continue

            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except Exception as e:
                ss.status_msg = f"Accept error: {e}"
                continue

            client.settimeout(SOCKET_TIMEOUT_S)
            ss.client_sock = client
            ss.client_addr = addr
            ss.status_msg = f"ESP32 connected from {addr[0]}:{addr[1]}"

            # Start/Restart reader thread
            ss.reader_running = True
            t = threading.Thread(target=_reader_loop, daemon=True)
            ss.reader_thread = t
            t.start()

    finally:
        _safe_close(srv)
        ss.status_msg = "Server stopped."
        # Cleanup any client
        _safe_close(ss.client_sock)
        ss.client_sock = None
        ss.client_addr = None
        ss.reader_running = False


def _reader_loop():
    """Continuously read frames from ESP32 (4-byte length prefix + JPEG bytes)."""
    ss = st.session_state
    sock = ss.client_sock
    if not sock:
        return

    while ss.reader_running and ss.client_sock is sock:
        # Read 4-byte length
        hdr = _recv_exact(sock, 4)
        if hdr is None:
            # Could be timeout or disconnect; if timeout, just loop
            # but _recv_exact returns None on timeout too, so we need to check again
            # by attempting a non-blocking-ish read later.
            time.sleep(0.01)
            continue

        (n,) = struct.unpack(">I", hdr)
        if n <= 0 or n > 10_000_000:
            ss.status_msg = f"Bad frame length: {n}"
            break

        frame = _recv_exact(sock, n)
        if frame is None:
            time.sleep(0.01)
            continue

        ss.last_frame_bytes = frame
        ss.last_frame_ts = time.time()

    # On exit, cleanup
    if ss.client_sock is sock:
        _safe_close(sock)
        ss.client_sock = None
        ss.client_addr = None
        ss.status_msg = "ESP32 disconnected."
    ss.reader_running = False
    ss.streaming_on = False


# ---------- Streamlit UI ----------

_init_state()

st.set_page_config(page_title="COE 454 Visual IoT Surveillance", layout="wide")
st.title("COE 454 – Visual IoT Surveillance")

colA, colB = st.columns([1, 2], gap="large")

with colA:
    st.subheader("Connection")
    st.write("**Status:**", st.session_state.status_msg)

    addr = st.session_state.client_addr
    if addr:
        st.success(f"Connected: {addr[0]}:{addr[1]}")
    else:
        st.warning("No ESP32 connected.")

    st.divider()

    if not st.session_state.server_running:
        if st.button("Start Server (port 4444)", use_container_width=True):
            st.session_state.server_running = True
            st.session_state.server_thread = threading.Thread(target=_server_loop, daemon=True)
            st.session_state.server_thread.start()
            st.rerun()
    else:
        if st.button("Stop Server", use_container_width=True):
            st.session_state.server_running = False
            st.session_state.reader_running = False
            _safe_close(st.session_state.client_sock)
            st.session_state.client_sock = None
            st.session_state.client_addr = None
            st.session_state.streaming_on = False
            st.session_state.status_msg = "Server stopping..."
            st.rerun()

    st.divider()
    st.subheader("Streaming Control")

    # Start/Stop toggle
    if not st.session_state.streaming_on:
        if st.button("▶️ Start Streaming", type="primary", use_container_width=True):
            _send_cmd("START")
            st.session_state.streaming_on = True
            st.rerun()
    else:
        if st.button("⏹️ Stop Streaming", use_container_width=True):
            _send_cmd("STOP")
            st.session_state.streaming_on = False
            st.rerun()

    st.caption("LED behavior is implemented on ESP32: RED when off, GREEN when streaming.")

with colB:
    st.subheader("Live Video")

    frame = st.session_state.last_frame_bytes
    ts = st.session_state.last_frame_ts

    if frame:
        st.image(frame, caption=f"Last frame: {time.strftime('%H:%M:%S', time.localtime(ts))}", channels="RGB")
    else:
        st.info("No frames received yet. Connect ESP32 and press Start Streaming.")

    # Auto-refresh while streaming (simple approach)
    if st.session_state.server_running:
        # refresh every ~200ms
        time.sleep(0.2)
        st.rerun()
