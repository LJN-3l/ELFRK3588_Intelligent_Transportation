cat > /root/setup_yolo_sd_target.sh <<'EOF'
#!/bin/sh
set -eu

SD_ROOT="/media/elf/E76C-92AC1"
PYLIB_DIR="$SD_ROOT/pylibs"
ULTRA_DIR="$PYLIB_DIR/ultralytics"

echo "=== A. 检查存储卡路径 ==="
ls -ld "$SD_ROOT"

echo
echo "=== B. 准备存储卡 Python 目录 ==="
mkdir -p "$PYLIB_DIR"

echo
echo "=== C. 清理旧的 ultralytics 目标目录 ==="
rm -rf "$PYLIB_DIR/ultralytics" \
       "$PYLIB_DIR"/ultralytics-*.dist-info || true

echo
echo "=== D. 只把 ultralytics 本体装到存储卡，不升级 torch ==="
python3 -m pip install --no-cache-dir --no-deps --target "$PYLIB_DIR" ultralytics

echo
echo "=== E. 修补 torchvision 元数据强依赖 ==="
python3 - <<'PY'
from pathlib import Path

utils_path = Path("/media/elf/E76C-92AC1/pylibs/ultralytics/utils/__init__.py")
text = utils_path.read_text(encoding="utf-8")

old = 'TORCHVISION_VERSION = importlib.metadata.version("torchvision")  # faster than importing torchvision'
new = '''try:
    TORCHVISION_VERSION = importlib.metadata.version("torchvision")  # faster than importing torchvision
except importlib.metadata.PackageNotFoundError:
    TORCHVISION_VERSION = "0.0.0"'''

if old in text:
    text = text.replace(old, new)
    utils_path.write_text(text, encoding="utf-8")
    print("patched:", utils_path)
else:
    print("skip patch, target line not found:", utils_path)

models_init = Path("/media/elf/E76C-92AC1/pylibs/ultralytics/models/__init__.py")
models_init.write_text(
    '# Ultralytics AGPL-3.0 License - https://ultralytics.com/license\n'
    '\n'
    'from . import yolo\n'
    'from .yolo import YOLO, YOLOE, YOLOWorld\n'
    '\n'
    '__all__ = "YOLO", "YOLOE", "YOLOWorld", "yolo"\n',
    encoding="utf-8",
)
print("patched:", models_init)

predictor_path = Path("/media/elf/E76C-92AC1/pylibs/ultralytics/engine/predictor.py")
predictor_text = predictor_path.read_text(encoding="utf-8")
predictor_old = '''        if (
            self.source_type.stream
            or self.source_type.screenshot
            or len(self.dataset) > 1000  # many images
            or any(getattr(self.dataset, "video_flag", [False]))
        ):  # long sequence
            import torchvision  # noqa (import here triggers torchvision NMS use in nms.py)

            if not getattr(self, "stream", True):  # videos
                LOGGER.warning(STREAM_WARNING)
'''
predictor_new = '''        if (
            self.source_type.stream
            or self.source_type.screenshot
            or len(self.dataset) > 1000  # many images
            or any(getattr(self.dataset, "video_flag", [False]))
        ):  # long sequence
            if not getattr(self, "stream", True):  # videos
                LOGGER.warning(STREAM_WARNING)
'''
if predictor_old in predictor_text:
    predictor_text = predictor_text.replace(predictor_old, predictor_new)
    predictor_path.write_text(predictor_text, encoding="utf-8")
    print("patched:", predictor_path)
else:
    print("skip patch, target block not found:", predictor_path)

checks_path = Path("/media/elf/E76C-92AC1/pylibs/ultralytics/utils/checks.py")
checks_text = checks_path.read_text(encoding="utf-8")
checks_old = '''    compatibility_table = {
'''
checks_new = '''    if TORCHVISION_VERSION.startswith("0.0"):
        return

    compatibility_table = {
'''
if checks_old in checks_text:
    checks_text = checks_text.replace(checks_old, checks_new, 1)
    checks_path.write_text(checks_text, encoding="utf-8")
    print("patched:", checks_path)
else:
    print("skip patch, target block not found:", checks_path)
PY

echo
echo "=== F. 验证导入和模型加载 ==="
PYTHONPATH="$PYLIB_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import flask, cv2, numpy
print("basic ok")
import torch
print("torch ok", torch.__version__)
from ultralytics import YOLO
print("ultralytics ok")
YOLO("/root/models/yolo11n.pt")
print("base model ok")
YOLO("/root/models/yolov11n_hemlet.pt")
print("helmet model ok")
PY

echo
echo "=== G. 生成网页端启动脚本 ==="
cat > /root/start_rk_yolo_dashboard.sh <<'EOS'
#!/bin/sh
set -eu

export PYTHONPATH="/media/elf/E76C-92AC1/pylibs${PYTHONPATH:+:$PYTHONPATH}"
export LIVE_STREAM_URL="${LIVE_STREAM_URL:-http://127.0.0.1:5001/video}"
export LIVE_STATUS_URL="${LIVE_STATUS_URL:-http://127.0.0.1:5001/status}"
export LIVE_ENABLE_AI="${LIVE_ENABLE_AI:-1}"
export LIVE_BASE_MODEL="${LIVE_BASE_MODEL:-/root/models/yolo11n.pt}"
export LIVE_HELMET_MODEL="${LIVE_HELMET_MODEL:-/root/models/yolov11n_hemlet.pt}"
export LIVE_ROI_JSON="${LIVE_ROI_JSON:-/root/live_roi.json}"
export LIVE_VIEW_HFLIP="${LIVE_VIEW_HFLIP:-1}"
export LIVE_VIEW_VFLIP="${LIVE_VIEW_VFLIP:-1}"
export LIVE_FRAME_STRIDE="${LIVE_FRAME_STRIDE:-3}"
export LIVE_IMGSZ="${LIVE_IMGSZ:-256}"
export LIVE_HELMET_INTERVAL_SECONDS="${LIVE_HELMET_INTERVAL_SECONDS:-0.60}"

exec python3 /root/rk3588_dashboard_dual_end.py
EOS

chmod +x /root/start_rk_yolo_dashboard.sh
echo "done: /root/start_rk_yolo_dashboard.sh"
EOF
