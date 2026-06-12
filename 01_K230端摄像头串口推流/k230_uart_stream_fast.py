from machine import UART, FPIOA
from media.sensor import *
from media.display import *
from media.media import *
import os
import struct
import time


UART_BAUD = 1500000
LCD_TYPE = Display.ST7701
LCD_WIDTH = 800
LCD_HEIGHT = 480

STREAM_WIDTH = 320
STREAM_HEIGHT = 240
JPEG_QUALITY = 38
FRAME_INTERVAL_MS = 0

SENSOR_HMIRROR = False
SENSOR_VFLIP = False


fpioa = FPIOA()
fpioa.set_function(5, FPIOA.UART2_TXD)
fpioa.set_function(6, FPIOA.UART2_RXD)
uart = UART(UART.UART2, UART_BAUD)


def open_sensor():
    for sensor_id in (0, 1, 2):
        try:
            print("try sensor id =", sensor_id)
            current = Sensor(id=sensor_id)
            current.reset()
            print("sensor ok, id =", sensor_id)
            return current
        except Exception as exc:
            print("sensor", sensor_id, "failed:", exc)
    raise RuntimeError("0/1/2 no usable sensor found")


def cleanup(sensor, display_inited, media_inited):
    try:
        if isinstance(sensor, Sensor):
            sensor.stop()
    except Exception:
        pass

    try:
        if display_inited:
            Display.deinit()
    except Exception:
        pass

    try:
        if media_inited:
            time.sleep_ms(100)
            MediaManager.deinit()
    except Exception:
        pass


sensor = None
display_inited = False
media_inited = False

try:
    print("init sensor...")
    sensor = open_sensor()

    sensor.set_framesize(width=LCD_WIDTH, height=LCD_HEIGHT, chn=CAM_CHN_ID_0)
    sensor.set_pixformat(Sensor.YUV420SP, chn=CAM_CHN_ID_0)

    sensor.set_framesize(width=STREAM_WIDTH, height=STREAM_HEIGHT, chn=CAM_CHN_ID_1)
    sensor.set_pixformat(Sensor.RGB565, chn=CAM_CHN_ID_1)

    sensor.set_hmirror(SENSOR_HMIRROR)
    sensor.set_vflip(SENSOR_VFLIP)

    bind_info = sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
    Display.bind_layer(**bind_info, layer=Display.LAYER_VIDEO1)

    Display.init(LCD_TYPE, width=LCD_WIDTH, height=LCD_HEIGHT, to_ide=True)
    display_inited = True

    MediaManager.init()
    media_inited = True

    sensor.run()
    print("uart baud =", UART_BAUD)
    print("stream size = {}x{}".format(STREAM_WIDTH, STREAM_HEIGHT))
    print("jpeg quality =", JPEG_QUALITY)
    print("start lcd preview + uart jpeg stream")

    report_started_ms = time.ticks_ms()
    report_frames = 0
    report_bytes = 0

    while True:
        os.exitpoint()

        img = sensor.snapshot(chn=CAM_CHN_ID_1)
        if img is None:
            continue

        jpg = img.compressed(quality=JPEG_QUALITY)
        frame_size = jpg.size()
        if frame_size <= 0:
            continue

        uart.write(struct.pack(">I", frame_size))
        uart.write(jpg)

        report_frames += 1
        report_bytes += frame_size

        now_ms = time.ticks_ms()
        elapsed_ms = time.ticks_diff(now_ms, report_started_ms)
        if elapsed_ms >= 2000:
            fps = report_frames * 1000.0 / elapsed_ms
            kbps = (report_bytes * 8.0 / elapsed_ms)
            print(
                "fps={:.1f} avg_frame={}B tx={:.1f}kbps".format(
                    fps,
                    int(report_bytes / max(1, report_frames)),
                    kbps,
                )
            )
            report_started_ms = now_ms
            report_frames = 0
            report_bytes = 0

        if FRAME_INTERVAL_MS > 0:
            time.sleep_ms(FRAME_INTERVAL_MS)

except KeyboardInterrupt:
    print("stopped by user")

except BaseException as exc:
    print("runtime error:", exc)

finally:
    cleanup(sensor, display_inited, media_inited)
