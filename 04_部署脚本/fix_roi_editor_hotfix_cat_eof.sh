cat > /root/fix_roi_editor_hotfix.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Patch standalone ROI editor frontend ==="
python3 - <<'PY'
from pathlib import Path
from datetime import datetime

path = Path("/root/web_dashboard_v4.py")
text = path.read_text(encoding="utf-8")
backup = Path("/root/web_dashboard_v4.py.bak_roi_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print("backup:", backup)

marker = "traffic-roi-hotfix-js"
hotfix = r'''
<script id="traffic-roi-hotfix-js">
(function(){
  const state = {
    image: null,
    imageWidth: 0,
    imageHeight: 0,
    config: {traffic_light_roi: [], crosswalk_polygon: []},
    mode: 'light',
    dragging: false,
    dragStart: null,
    dragCurrent: null
  };

  function $(id){ return document.getElementById(id); }

  function msg(text){
    const box = $('roiStatus');
    if(box) box.textContent = text || '';
  }

  function toast(text, kind){
    if(typeof window.showToast === 'function'){
      window.showToast(text, kind || 'info', 2600);
    }else{
      console.log(text);
    }
  }

  function setBtnActive(){
    const light = $('roiModeLightBtn');
    const cross = $('roiModeCrosswalkBtn');
    if(light) light.classList.toggle('active', state.mode === 'light');
    if(cross) cross.classList.toggle('active', state.mode === 'crosswalk');
  }

  function pointFromEvent(ev){
    const canvas = $('roiCanvas');
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / Math.max(1, rect.width);
    const sy = canvas.height / Math.max(1, rect.height);
    return {
      x: Math.max(0, Math.min(canvas.width, (ev.clientX - rect.left) * sx)),
      y: Math.max(0, Math.min(canvas.height, (ev.clientY - rect.top) * sy))
    };
  }

  function normalizeRect(a, b){
    const x1 = Math.max(0, Math.min(a.x, b.x));
    const y1 = Math.max(0, Math.min(a.y, b.y));
    const x2 = Math.min(state.imageWidth, Math.max(a.x, b.x));
    const y2 = Math.min(state.imageHeight, Math.max(a.y, b.y));
    return [Math.round(x1), Math.round(y1), Math.max(1, Math.round(x2 - x1)), Math.max(1, Math.round(y2 - y1))];
  }

  function drawRect(ctx, rect, color){
    if(!rect || rect.length !== 4) return;
    ctx.save();
    ctx.strokeStyle = color || '#ff5252';
    ctx.fillStyle = 'rgba(255,82,82,.18)';
    ctx.lineWidth = 3;
    ctx.strokeRect(rect[0], rect[1], rect[2], rect[3]);
    ctx.fillRect(rect[0], rect[1], rect[2], rect[3]);
    ctx.restore();
  }

  function drawPoly(ctx, pts){
    if(!pts || !pts.length) return;
    ctx.save();
    ctx.strokeStyle = '#00d4ff';
    ctx.fillStyle = 'rgba(0,212,255,.16)';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for(let i = 1; i < pts.length; i += 1){
      ctx.lineTo(pts[i][0], pts[i][1]);
    }
    if(pts.length >= 3){
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
    pts.forEach(function(p, i){
      ctx.beginPath();
      ctx.fillStyle = '#0b57d0';
      ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.font = '12px sans-serif';
      ctx.fillText(String(i + 1), p[0] + 8, p[1] - 8);
    });
    ctx.restore();
  }

  function draw(){
    const canvas = $('roiCanvas');
    if(!canvas) return;
    const ctx = canvas.getContext('2d');

    if(!state.image){
      canvas.width = 960;
      canvas.height = 540;
      ctx.fillStyle = '#09111b';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#d6e5ff';
      ctx.font = '18px sans-serif';
      ctx.fillText('Loading live snapshot...', 24, 40);
      return;
    }

    canvas.width = state.imageWidth;
    canvas.height = state.imageHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(state.image, 0, 0, canvas.width, canvas.height);

    drawRect(ctx, state.config.traffic_light_roi, '#ff5252');
    drawPoly(ctx, state.config.crosswalk_polygon || []);

    if(state.mode === 'light' && state.dragging && state.dragStart && state.dragCurrent){
      drawRect(ctx, normalizeRect(state.dragStart, state.dragCurrent), '#1e6fff');
    }

    setBtnActive();
    const light = state.config.traffic_light_roi || [];
    const poly = state.config.crosswalk_polygon || [];
    msg('\u5f53\u524d\u6a21\u5f0f\uff1a' + (state.mode === 'light' ? '\u7ea2\u7eff\u706f\u6846' : '\u6591\u9a6c\u7ebf\u591a\u8fb9\u5f62') +
        ' | \u7ea2\u7eff\u706f\uff1a' + (light.length === 4 ? light.join(',') : '\u672a\u8bbe\u7f6e') +
        ' | \u6591\u9a6c\u7ebf\u70b9\u6570\uff1a' + poly.length);
  }

  async function loadSnapshot(keepConfig){
    msg('\u6b63\u5728\u6293\u53d6\u5b9e\u65f6\u753b\u9762...');
    draw();
    const res = await fetch('/api/roi/editor_state?t=' + Date.now(), {cache:'no-store'});
    let data = null;
    try{
      data = await res.json();
    }catch(err){
      throw new Error('ROI \u63a5\u53e3\u8fd4\u56de\u4e0d\u662f JSON\uff0cHTTP ' + res.status);
    }
    if(!res.ok || !data.ok){
      throw new Error((data && data.message) || ('ROI \u63a5\u53e3\u5931\u8d25\uff0cHTTP ' + res.status));
    }

    const img = new Image();
    img.onload = function(){
      state.image = img;
      state.imageWidth = Number(data.image_width || img.width);
      state.imageHeight = Number(data.image_height || img.height);
      if(!keepConfig){
        state.config = data.config || {traffic_light_roi: [], crosswalk_polygon: []};
        state.config.traffic_light_roi = state.config.traffic_light_roi || [];
        state.config.crosswalk_polygon = state.config.crosswalk_polygon || [];
      }
      state.dragging = false;
      draw();
      toast('\u5df2\u6253\u5f00 ROI \u6807\u5b9a', 'success');
    };
    img.onerror = function(){
      msg('\u753b\u9762\u52a0\u8f7d\u5931\u8d25\uff0c\u8bf7\u786e\u8ba4 K230 \u76f4\u64ad\u6b63\u5e38');
    };
    img.src = 'data:image/jpeg;base64,' + data.image_base64;
  }

  function bindCanvas(){
    const canvas = $('roiCanvas');
    if(!canvas || canvas.dataset.roiHotfixBound === '1') return;
    canvas.dataset.roiHotfixBound = '1';

    canvas.addEventListener('mousedown', function(ev){
      if(!state.image || state.mode !== 'light') return;
      state.dragging = true;
      state.dragStart = pointFromEvent(ev);
      state.dragCurrent = state.dragStart;
      draw();
    });

    canvas.addEventListener('mousemove', function(ev){
      if(!state.image || !state.dragging || state.mode !== 'light') return;
      state.dragCurrent = pointFromEvent(ev);
      draw();
    });

    window.addEventListener('mouseup', function(ev){
      if(!state.image || !state.dragging || state.mode !== 'light') return;
      state.dragCurrent = pointFromEvent(ev);
      state.config.traffic_light_roi = normalizeRect(state.dragStart, state.dragCurrent);
      state.dragging = false;
      draw();
    });

    canvas.addEventListener('click', function(ev){
      if(!state.image || state.mode !== 'crosswalk') return;
      const p = pointFromEvent(ev);
      state.config.crosswalk_polygon = state.config.crosswalk_polygon || [];
      state.config.crosswalk_polygon.push([Math.round(p.x), Math.round(p.y)]);
      draw();
    });

    canvas.addEventListener('contextmenu', function(ev){
      ev.preventDefault();
      window.undoCrosswalkPoint();
    });
  }

  window.openRoiEditor = function(){
    const modal = $('roiModal');
    if(!modal){
      alert('ROI modal not found');
      return;
    }
    modal.classList.add('open');
    bindCanvas();
    loadSnapshot(false).catch(function(err){
      msg('\u6253\u5f00 ROI \u5931\u8d25\uff1a' + err.message);
      alert('\u6253\u5f00 ROI \u5931\u8d25\uff1a' + err.message);
    });
  };

  window.closeRoiEditor = function(){
    const modal = $('roiModal');
    if(modal) modal.classList.remove('open');
    state.dragging = false;
  };

  window.setRoiMode = function(mode){
    state.mode = mode === 'crosswalk' ? 'crosswalk' : 'light';
    draw();
  };

  window.refreshRoiSnapshot = function(){
    loadSnapshot(true).catch(function(err){
      msg('\u91cd\u65b0\u6293\u5e27\u5931\u8d25\uff1a' + err.message);
      alert('\u91cd\u65b0\u6293\u5e27\u5931\u8d25\uff1a' + err.message);
    });
  };

  window.clearLightRoi = function(){
    state.config.traffic_light_roi = [];
    draw();
  };

  window.clearCrosswalkRoi = function(){
    state.config.crosswalk_polygon = [];
    draw();
  };

  window.undoCrosswalkPoint = function(){
    state.config.crosswalk_polygon = state.config.crosswalk_polygon || [];
    state.config.crosswalk_polygon.pop();
    draw();
  };

  window.saveRoiConfig = async function(){
    const light = state.config.traffic_light_roi || [];
    const poly = state.config.crosswalk_polygon || [];
    if(light.length !== 4){
      alert('\u8bf7\u5148\u62d6\u51fa\u7ea2\u7eff\u706f\u533a\u57df');
      return;
    }
    if(poly.length < 3){
      alert('\u8bf7\u81f3\u5c11\u70b9\u51fb 3 \u4e2a\u70b9\u5f62\u6210\u6591\u9a6c\u7ebf\u533a\u57df');
      return;
    }

    msg('\u6b63\u5728\u4fdd\u5b58 ROI \u5e76\u91cd\u8f7d AI...');
    try{
      const res = await fetch('/api/roi/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          image_width: state.imageWidth,
          image_height: state.imageHeight,
          traffic_light_roi: light,
          crosswalk_polygon: poly
        })
      });
      const data = await res.json();
      if(!res.ok || !data.ok){
        throw new Error(data.message || ('HTTP ' + res.status));
      }
      toast('\u4fdd\u5b58 ROI \u6210\u529f\uff0cAI \u5df2\u91cd\u8f7d', 'success', 3200);
      msg('\u4fdd\u5b58\u6210\u529f');
      window.closeRoiEditor();
      if(typeof window.refreshAll === 'function'){
        window.refreshAll();
      }
    }catch(err){
      msg('\u4fdd\u5b58 ROI \u5931\u8d25\uff1a' + err.message);
      alert('\u4fdd\u5b58 ROI \u5931\u8d25\uff1a' + err.message);
    }
  };

  window.addEventListener('load', function(){
    bindCanvas();
    const modal = $('roiModal');
    if(modal && modal.dataset.roiHotfixBound !== '1'){
      modal.dataset.roiHotfixBound = '1';
      modal.addEventListener('click', function(ev){
        if(ev.target && ev.target.id === 'roiModal'){
          window.closeRoiEditor();
        }
      });
    }
  });
})();
</script>
'''

if marker in text:
    print("skip: ROI hotfix already exists")
else:
    needle = "</body>\n</html>\n\"\"\""
    if needle not in text:
        raise SystemExit("cannot find dashboard HTML </body> anchor")
    text = text.replace(needle, hotfix + "\n</body>\n</html>\n\"\"\"", 1)
    path.write_text(text, encoding="utf-8")
    print("patched:", path)
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
echo "=== D. Test ROI backend ==="
curl --max-time 8 http://127.0.0.1:5000/api/roi/editor_state -o /tmp/roi_state.json -w "HTTP=%{http_code} SIZE=%{size_download}\n" || true
python3 - <<'PY' || true
import json
from pathlib import Path
p = Path("/tmp/roi_state.json")
if not p.exists():
    print("roi_state: missing")
    raise SystemExit
try:
    data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
except Exception as exc:
    print("roi_state: invalid json", exc)
    print(p.read_text(encoding="utf-8", errors="ignore")[:500])
    raise SystemExit
print("roi_state ok:", data.get("ok"))
print("image:", data.get("image_width"), "x", data.get("image_height"))
print("config:", data.get("config"))
print("message:", data.get("message", ""))
PY

echo
echo "=== E. Live status ==="
curl --max-time 5 http://127.0.0.1:5000/api/live_status || true
echo

echo
echo "Done. Open http://192.168.137.82:5000 and press Ctrl+F5 once."
EOF

sh /root/fix_roi_editor_hotfix.sh
