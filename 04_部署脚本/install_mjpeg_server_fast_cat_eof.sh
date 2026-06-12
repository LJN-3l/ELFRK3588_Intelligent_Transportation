cat > /root/mjpeg_server.py <<'EOF'
#!/usr/bin/env python3

import os
import struct
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify

try:
    import serial
except Exception as exc:
    serial = None
    SERIAL_IMPORT_ERROR = str(exc)
else:
    SERIAL_IMPORT_ERROR = ""


SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "1500000"))
SERIAL_TIMEOUT = float(os.environ.get("SERIAL_TIMEOUT", "1.0"))
SERIAL_RECONNECT_SECONDS = float(os.environ.get("SERIAL_RECONNECT_SECONDS", "1.0"))
FRAME_MAX_BYTES = int(os.environ.get("FRAME_MAX_BYTES", "262144"))

HTTP_HOST = os.environ.get("MJPEG_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("MJPEG_PORT", "5001"))
JPEG_BOUNDARY = "frame"

app = Flask(__name__)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_exact(ser, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = ser.read(size - len(chunks))
        if not part:
            raise TimeoutError("serial read timeout")
        chunks.extend(part)
    return bytes(chunks)


class FrameHub:
    def __init__(self):
        self.cond = threading.Condition()
        self.frame_id = 0
        self.latest_jpeg = b""
        self.latest_size = 0
        self.frames_received = 0
        self.invalid_headers = 0
        self.invalid_jpegs = 0
        self.last_error = SERIAL_IMPORT_ERROR
        self.last_frame_at = ""
        self.reader_online = False

    def set_reader_state(self, online, error=""):
        with self.cond:
            self.reader_online = online
            if error:
                self.last_error = error
            self.cond.notify_all()

    def update_frame(self, jpeg):
        with self.cond:
            self.frame_id += 1
            self.latest_jpeg = jpeg
            self.latest_size = len(jpeg)
            self.frames_received += 1
            self.last_frame_at = now_text()
            self.last_error = ""
            self.reader_online = True
            self.cond.notify_all()

    def mark_invalid_header(self, error):
        with self.cond:
            self.invalid_headers += 1
            self.last_error = error

    def mark_invalid_jpeg(self, error):
        with self.cond:
            self.invalid_jpegs += 1
            self.last_error = error

    def wait_for_frame(self, previous_id, timeout=15.0):
        deadline = time.time() + timeout
        with self.cond:
            while self.frame_id <= previous_id:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return self.frame_id, self.latest_jpeg
                self.cond.wait(timeout=remaining)
            return self.frame_id, self.latest_jpeg

    def status(self):
        with self.cond:
            return {
                "serial_port": SERIAL_PORT,
                "serial_baud": SERIAL_BAUD,
                "reader_online": self.reader_online,
                "frames_received": self.frames_received,
                "latest_size": self.latest_size,
                "last_frame_at": self.last_frame_at,
                "invalid_headers": self.invalid_headers,
                "invalid_jpegs": self.invalid_jpegs,
                "last_error": self.last_error,
                "has_frame": bool(self.latest_jpeg),
            }


HUB = FrameHub()


def open_serial():
    if serial is None:
        raise RuntimeError("pyserial import failed: {}".format(SERIAL_IMPORT_ERROR))
    try:
        ser = serial.Serial(
            SERIAL_PORT,
            SERIAL_BAUD,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
            exclusive=True,
        )
    except TypeError:
        ser = serial.Serial(
            SERIAL_PORT,
            SERIAL_BAUD,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
        )
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    return ser


def serial_reader():
    while True:
        ser = None
        try:
            HUB.set_reader_state(False, "")
            ser = open_serial()
            HUB.set_reader_state(True, "")
            print("serial connected:", SERIAL_PORT, SERIAL_BAUD)
            while True:
                header = read_exact(ser, 4)
                frame_size = struct.unpack(">I", header)[0]
                if frame_size <= 0 or frame_size > FRAME_MAX_BYTES:
                    HUB.mark_invalid_header("bad frame size: {}".format(frame_size))
                    try:
                        ser.reset_input_buffer()
                    except Exception:
                        pass
                    continue
                jpeg = read_exact(ser, frame_size)
                if not (jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
                    HUB.mark_invalid_jpeg("bad jpeg frame: {} bytes".format(frame_size))
                    continue
                HUB.update_frame(jpeg)
        except Exception as exc:
            HUB.set_reader_state(False, str(exc))
            print("serial disconnected:", exc)
            time.sleep(SERIAL_RECONNECT_SECONDS)
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass


def mjpeg_generator():
    previous_id = -1
    while True:
        frame_id, jpeg = HUB.wait_for_frame(previous_id)
        if not jpeg:
            time.sleep(0.1)
            continue
        previous_id = frame_id
        yield (
            b"--" + JPEG_BOUNDARY.encode("ascii") + b"\r\n"
            + b"Content-Type: image/jpeg\r\n"
            + "Content-Length: {}\r\n\r\n".format(len(jpeg)).encode("ascii")
            + jpeg
            + b"\r\n"
        )


@app.route("/")
def index():
    status = HUB.status()
    return Response(
        "\n".join(
            [
                "UART MJPEG server running",
                "video: /video",
                "status: /status",
                "port: {} @ {}".format(status["serial_port"], status["serial_baud"]),
                "reader_online: {}".format(status["reader_online"]),
                "frames_received: {}".format(status["frames_received"]),
                "last_frame_at: {}".format(status["last_frame_at"] or "-"),
                "last_error: {}".format(status["last_error"] or "-"),
            ]
        )
        + "\n",
        mimetype="text/plain; charset=utf-8",
    )


@app.route("/status")
def status():
    return jsonify(HUB.status())


@app.route("/video")
def video():
    response = Response(
        mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary={}".format(JPEG_BOUNDARY),
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


if __name__ == "__main__":
    threading.Thread(target=serial_reader, daemon=True, name="serial-reader").start()
    print("HTTP listening on {}:{}".format(HTTP_HOST, HTTP_PORT))
    app.run(host=HTTP_HOST, port=HTTP_PORT, threaded=True)
EOF

cat > /root/start_mjpeg_server_fast.sh <<'EOF'
#!/bin/sh

export SERIAL_PORT="${SERIAL_PORT:-/dev/ttyUSB0}"
export SERIAL_BAUD="${SERIAL_BAUD:-1500000}"
export SERIAL_TIMEOUT="${SERIAL_TIMEOUT:-1.0}"
export SERIAL_RECONNECT_SECONDS="${SERIAL_RECONNECT_SECONDS:-1.0}"
export FRAME_MAX_BYTES="${FRAME_MAX_BYTES:-262144}"
export MJPEG_HOST="${MJPEG_HOST:-0.0.0.0}"
export MJPEG_PORT="${MJPEG_PORT:-5001}"

python3 /root/mjpeg_server.py
EOF

chmod +x /root/mjpeg_server.py /root/start_mjpeg_server_fast.sh
echo "installed: /root/mjpeg_server.py"
echo "installed: /root/start_mjpeg_server_fast.sh"
