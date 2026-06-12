cat > /root/repair_ultralytics_sd_no_torchvision.sh <<'EOF'
#!/bin/sh
set -eu

PYLIB_DIR="/media/elf/E76C-92AC1/pylibs"

echo "=== A. 修补 ultralytics，去掉对 torchvision / SAM 的硬依赖 ==="
python3 - <<'PY'
from pathlib import Path

root = Path("/media/elf/E76C-92AC1/pylibs/ultralytics")

utils_path = root / "utils" / "__init__.py"
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
    print("skip patch:", utils_path)

models_init = root / "models" / "__init__.py"
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

predictor_path = root / "engine" / "predictor.py"
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
    print("skip patch:", predictor_path)

checks_path = root / "utils" / "checks.py"
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
    print("skip patch:", checks_path)
PY

echo
echo "=== B. 验证 YOLO 能否导入并加载模型 ==="
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
EOF
