cat > /root/fix_rk_yolo_start_env.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Stop dashboard only ==="
pkill -f web_dashboard_v4.py || true
pkill -f start_rk_yolo_dashboard.sh || true
pkill -f llm_demo || true
sleep 1

echo
echo "=== B. Reinstall unified starter ==="
cat > /root/start_rk_yolo_dashboard.sh <<'STARTER'
#!/bin/sh
set -eu

export PYTHONPATH="/media/elf/E76C-92AC1/pylibs${PYTHONPATH:+:$PYTHONPATH}"
export DASHBOARD_HOST="${DASHBOARD_HOST:-0.0.0.0}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-5000}"
export LIVE_STREAM_URL="${LIVE_STREAM_URL:-http://127.0.0.1:5001/video}"
export LIVE_STATUS_URL="${LIVE_STATUS_URL:-http://127.0.0.1:5001/status}"
export LIVE_ENABLE_AI="${LIVE_ENABLE_AI:-1}"
export LIVE_BASE_MODEL="${LIVE_BASE_MODEL:-/root/models/yolo11n.pt}"
export LIVE_HELMET_MODEL="${LIVE_HELMET_MODEL:-/root/models/yolov11n_hemlet.pt}"
export LIVE_ROI_JSON="${LIVE_ROI_JSON:-/root/live_roi.json}"
export LIVE_VIEW_HFLIP="${LIVE_VIEW_HFLIP:-0}"
export LIVE_VIEW_VFLIP="${LIVE_VIEW_VFLIP:-0}"
export LIVE_FRAME_STRIDE="${LIVE_FRAME_STRIDE:-3}"
export LIVE_IMGSZ="${LIVE_IMGSZ:-256}"
export LIVE_HELMET_INTERVAL_SECONDS="${LIVE_HELMET_INTERVAL_SECONDS:-0.60}"
export REPORT_AI_MODE="${REPORT_AI_MODE:-deepseek}"
export REPORT_AI_MAX_PROMPT="${REPORT_AI_MAX_PROMPT:-1024}"
export REPORT_AI_MAX_GEN="${REPORT_AI_MAX_GEN:-420}"
export REPORT_AI_TIMEOUT="${REPORT_AI_TIMEOUT:-75}"

exec python3 /root/web_dashboard_v4.py
STARTER
chmod +x /root/start_rk_yolo_dashboard.sh

echo
echo "=== C. Check Python deps and required files ==="
PYTHONPATH="/media/elf/E76C-92AC1/pylibs${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
from pathlib import Path
checks = {
    "pylibs": Path("/media/elf/E76C-92AC1/pylibs").exists(),
    "base_model": Path("/root/models/yolo11n.pt").exists(),
    "helmet_model": Path("/root/models/yolov11n_hemlet.pt").exists(),
    "roi_json": Path("/root/live_roi.json").exists(),
}
for name, ok in checks.items():
    print(f"{name}: {'ok' if ok else 'missing'}")
try:
    import cv2, numpy
    from ultralytics import YOLO
    print("python deps: ok")
except Exception as exc:
    print("python deps: failed:", exc)
PY

echo
echo "=== D. Start dashboard with unified starter ==="
nohup sh /root/start_rk_yolo_dashboard.sh > /root/dashboard.log 2>&1 &
sleep 8
tail -n 120 /root/dashboard.log || true

echo
echo "=== E. Verify dashboard / AI / report ==="
ss -lntp | grep 5000 || true
curl --max-time 5 http://127.0.0.1:5000/api/live_status || true
echo
curl --max-time 5 http://127.0.0.1:5000/api/report/status || true
echo
echo "Done."
EOF

echo "Created: /root/fix_rk_yolo_start_env.sh"
