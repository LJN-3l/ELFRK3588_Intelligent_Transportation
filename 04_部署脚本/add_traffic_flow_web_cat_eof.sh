cat > /root/add_traffic_flow_web.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Patch RK3588 dashboard traffic-flow support ==="
python3 - <<'PY'
from pathlib import Path
from datetime import datetime

path = Path("/root/web_dashboard_v4.py")
text = path.read_text(encoding="utf-8")
backup = Path("/root/web_dashboard_v4.py.bak_traffic_flow_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print("backup:", backup)

marker = "TRAFFIC_FLOW_DUAL_END_PATCH"
if marker not in text:
    block = r'''
# TRAFFIC_FLOW_DUAL_END_PATCH
TRAFFIC_FLOW_SLOW_THRESHOLD = max(1, int(os.environ.get("TRAFFIC_FLOW_SLOW_THRESHOLD", "5")))
TRAFFIC_FLOW_JAM_THRESHOLD = max(
    TRAFFIC_FLOW_SLOW_THRESHOLD + 1,
    int(os.environ.get("TRAFFIC_FLOW_JAM_THRESHOLD", "10")),
)
traffic_flow_lock = threading.Lock()
TRAFFIC_FLOW_STATUS = {
    "source": "none",
    "vehicle_count": 0,
    "status": "unknown",
    "status_label": "等待数据",
    "counts": {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0},
    "updated_at": "",
    "frame_index": 0,
    "slow_threshold": TRAFFIC_FLOW_SLOW_THRESHOLD,
    "jam_threshold": TRAFFIC_FLOW_JAM_THRESHOLD,
}


def traffic_flow_level(vehicle_count):
    vehicle_count = int(vehicle_count or 0)
    if vehicle_count >= TRAFFIC_FLOW_JAM_THRESHOLD:
        return "jam", "拥堵"
    if vehicle_count >= TRAFFIC_FLOW_SLOW_THRESHOLD:
        return "slow", "缓行"
    return "smooth", "畅通"


def update_traffic_flow_status(payload):
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    normalized_counts = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0}
    for key in normalized_counts:
        try:
            normalized_counts[key] = max(0, int(counts.get(key, 0)))
        except Exception:
            normalized_counts[key] = 0
    try:
        vehicle_count = int(payload.get("vehicle_count", sum(normalized_counts.values())) or 0)
    except Exception:
        vehicle_count = sum(normalized_counts.values())
    status = str(payload.get("status") or "")
    status_label = str(payload.get("status_label") or "")
    if status not in {"smooth", "slow", "jam"} or not status_label:
        status, status_label = traffic_flow_level(vehicle_count)
    updated = {
        "source": str(payload.get("source") or LIVE_SOURCE_NAME),
        "vehicle_count": max(0, vehicle_count),
        "status": status,
        "status_label": status_label,
        "counts": normalized_counts,
        "updated_at": str(payload.get("updated_at") or now_text()),
        "frame_index": int(payload.get("frame_index") or 0),
        "slow_threshold": int(payload.get("slow_threshold") or TRAFFIC_FLOW_SLOW_THRESHOLD),
        "jam_threshold": int(payload.get("jam_threshold") or TRAFFIC_FLOW_JAM_THRESHOLD),
    }
    with traffic_flow_lock:
        TRAFFIC_FLOW_STATUS.update(updated)
        return dict(TRAFFIC_FLOW_STATUS)


def get_traffic_flow_status():
    with traffic_flow_lock:
        return dict(TRAFFIC_FLOW_STATUS)


def update_traffic_flow_from_tracks(tracks, frame_index, source):
    counts = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0}
    active = []
    for track in tracks.values():
        if getattr(track, "missed_frames", 0) == 0:
            active.append(track)
            cls_name = getattr(track, "cls_name", "other")
            key = cls_name if cls_name in counts else "other"
            counts[key] += 1
    status, label = traffic_flow_level(len(active))
    return update_traffic_flow_status({
        "source": source,
        "vehicle_count": len(active),
        "status": status,
        "status_label": label,
        "counts": counts,
        "updated_at": now_text(),
        "frame_index": frame_index,
    })

'''
    anchor = "DATA_DIR.mkdir(parents=True, exist_ok=True)\nIMAGE_DIR.mkdir(parents=True, exist_ok=True)\n"
    if anchor not in text:
        raise SystemExit("cannot find data-dir anchor")
    text = text.replace(anchor, anchor + block + "\n", 1)
    print("patched: traffic flow globals/functions")
else:
    print("skip: traffic flow globals already exist")

route_marker = '@app.route("/api/traffic_flow")'
if route_marker not in text:
    route_block = r'''
@app.route("/api/traffic_flow")
def api_traffic_flow():
    return jsonify({"ok": True, "traffic_flow": get_traffic_flow_status()})


@app.route("/api/upload_traffic_flow", methods=["POST"])
def api_upload_traffic_flow():
    payload = request.get_json(silent=True) or {}
    status = update_traffic_flow_status(payload)
    return jsonify({"ok": True, "traffic_flow": status})


'''
    anchor = '@app.route("/api/upload_violation", methods=["POST"])'
    if anchor not in text:
        raise SystemExit("cannot find upload_violation route anchor")
    text = text.replace(anchor, route_block + anchor, 1)
    print("patched: traffic flow routes")
else:
    print("skip: traffic flow routes already exist")

live_marker = "update_traffic_flow_from_tracks(latest_tracks, frame_index, LIVE_SOURCE_NAME)"
if live_marker not in text:
    old = "                    latest_tracks = tracker.update(detections, frame_index)\n"
    new = old + "                    update_traffic_flow_from_tracks(latest_tracks, frame_index, LIVE_SOURCE_NAME)\n"
    if old not in text:
        raise SystemExit("cannot find latest_tracks update anchor")
    text = text.replace(old, new, 1)
    print("patched: live YOLO flow update")
else:
    print("skip: live YOLO flow update already exists")

frontend_marker = "traffic-flow-widget-hotfix-js"
if frontend_marker not in text:
    frontend = r'''
<script id="traffic-flow-widget-hotfix-js">
(function(){
  function $(id){ return document.getElementById(id); }

  function ensureTrafficCards(){
    if($('trafficFlowStatus') && $('trafficFlowCount')) return;
    const stats = document.querySelector('.stats');
    if(!stats) return;
    const statusCard = document.createElement('div');
    statusCard.id = 'trafficFlowStatusCard';
    statusCard.className = 'card stat flow';
    statusCard.innerHTML = '<label>车流状态</label><b id="trafficFlowStatus">等待数据</b>';
    const countCard = document.createElement('div');
    countCard.className = 'card stat flow';
    countCard.innerHTML = '<label>当前车辆数</label><b id="trafficFlowCount">0</b>';
    stats.appendChild(statusCard);
    stats.appendChild(countCard);
    stats.style.gridTemplateColumns = 'repeat(8,1fr)';
  }

  function applyTrafficFlow(flow){
    ensureTrafficCards();
    flow = flow || {};
    const status = $('trafficFlowStatus');
    const count = $('trafficFlowCount');
    const card = $('trafficFlowStatusCard');
    if(status) status.textContent = flow.status_label || '等待数据';
    if(count) count.textContent = Number(flow.vehicle_count || 0);
    if(card){
      card.classList.remove('smooth', 'slow', 'jam');
      card.classList.add(flow.status || 'smooth');
      const color = flow.status === 'jam' ? '#d64141' : (flow.status === 'slow' ? '#d88612' : '#0f8f8d');
      const b = card.querySelector('b');
      if(b) b.style.color = color;
    }
  }

  async function refreshTrafficFlow(){
    try{
      const res = await fetch('/api/traffic_flow?t=' + Date.now(), {cache:'no-store'});
      const data = await res.json();
      applyTrafficFlow(data.traffic_flow || {});
    }catch(err){
      applyTrafficFlow({status_label:'读取失败', vehicle_count:0, status:'jam'});
    }
  }

  window.addEventListener('load', function(){
    ensureTrafficCards();
    refreshTrafficFlow();
    setInterval(refreshTrafficFlow, 2500);
  });
  ensureTrafficCards();
})();
</script>
'''
    needle = "</body>\n</html>\n\"\"\""
    if needle not in text:
        raise SystemExit("cannot find dashboard HTML close anchor")
    text = text.replace(needle, frontend + "\n</body>\n</html>\n\"\"\"", 1)
    print("patched: frontend traffic widget")
else:
    print("skip: frontend traffic widget already exists")

path.write_text(text, encoding="utf-8")
print("saved:", path)
PY

echo
echo "=== B. Syntax check ==="
python3 -m py_compile /root/web_dashboard_v4.py

echo
echo "=== C. Restart dashboard ==="
pkill -f web_dashboard_v4.py 2>/dev/null || true
pkill -f start_rk_yolo_dashboard.sh 2>/dev/null || true
sleep 1
nohup sh /root/start_rk_yolo_dashboard.sh > /root/dashboard.log 2>&1 &
sleep 6

echo
echo "=== D. Test traffic-flow API ==="
curl --max-time 5 http://127.0.0.1:5000/api/traffic_flow || true
echo
curl --max-time 5 -X POST http://127.0.0.1:5000/api/upload_traffic_flow \
  -H "Content-Type: application/json" \
  -d '{"source":"manual_test","vehicle_count":7,"counts":{"car":5,"motorcycle":2},"frame_index":1}' || true
echo
curl --max-time 5 http://127.0.0.1:5000/api/traffic_flow || true
echo

echo
echo "Done. Open http://192.168.137.82:5000 and press Ctrl+F5 once."
EOF

sh /root/add_traffic_flow_web.sh
