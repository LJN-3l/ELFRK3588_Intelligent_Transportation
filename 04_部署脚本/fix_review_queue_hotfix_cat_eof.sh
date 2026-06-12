cat > /root/fix_review_queue_hotfix.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Patch standalone review queue frontend ==="
python3 - <<'PY'
from pathlib import Path
from datetime import datetime

path = Path("/root/web_dashboard_v4.py")
text = path.read_text(encoding="utf-8")
backup = Path("/root/web_dashboard_v4.py.bak_review_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print("backup:", backup)

marker = "traffic-review-hotfix-js"
hotfix = r'''
<script id="traffic-review-hotfix-js">
(function(){
  const $ = (id) => document.getElementById(id);
  let reviewBusy = false;

  function escapeHtml(value){
    return String(value ?? '').replace(/[&<>"']/g, function(ch){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
    });
  }

  function toast(msg, kind='info', ms=2600){
    if(typeof window.showToast === 'function'){
      window.showToast(msg, kind, ms);
    }else{
      console.log(kind + ': ' + msg);
    }
  }

  function confidenceText(value){
    const num = Number(value || 0);
    return Number.isFinite(num) ? num.toFixed(2) : '0.00';
  }

  function metaLine(label, value){
    if(value === undefined || value === null || value === '') return '';
    return `${escapeHtml(label)}：${escapeHtml(value)}<br>`;
  }

  function renderReviewEvents(events){
    const root = $('reviewGrid');
    if(!root) return;

    if(!events || events.length === 0){
      root.innerHTML = '<div class="muted">当前没有待审核事件。</div>';
      return;
    }

    root.innerHTML = events.map(function(event){
      const meta = event.metadata || {};
      const flow = meta.traffic_flow || {};
      const extra = [
        metaLine('目标类型', meta.class_name),
        metaLine('头盔状态', meta.helmet_status),
        metaLine('轨迹 ID', meta.track_id),
        flow.vehicle_count !== undefined ? `抓拍时车流：${escapeHtml(flow.vehicle_count || 0)}辆 / ${escapeHtml(flow.status_label || '')}<br>` : '',
        meta.red_score !== undefined ? `红灯分数：${escapeHtml(Number(meta.red_score || 0).toFixed ? Number(meta.red_score || 0).toFixed(3) : meta.red_score)}<br>` : '',
        meta.green_score !== undefined ? `绿灯分数：${escapeHtml(Number(meta.green_score || 0).toFixed ? Number(meta.green_score || 0).toFixed(3) : meta.green_score)}<br>` : ''
      ].join('');

      return `
        <div class="event-card" data-event-id="${escapeHtml(event.id)}">
          <img src="${escapeHtml(event.image_url || '/video_proxy')}" alt="event">
          <div class="event-body">
            <div class="event-title">${escapeHtml(event.reason_label || event.reason_code || '待审核事件')}</div>
            <div class="event-meta">
              时间：${escapeHtml(event.created_at || '')}<br>
              来源：${escapeHtml(event.source || '')}<br>
              置信度：${confidenceText(event.confidence)}<br>
              ${extra || '暂无附加元数据'}
            </div>
            <span class="status-tag">${escapeHtml(event.status_label || event.status || '待审核')}</span>
            <textarea id="note-${escapeHtml(event.id)}" class="event-note" placeholder="填写备注、驳回原因或去重说明...">${escapeHtml(event.review_note || '')}</textarea>
            <div class="event-actions">
              <button class="approve" onclick="reviewEvent(${Number(event.id)}, 'approved')">确认违规</button>
              <button class="reject" onclick="reviewEvent(${Number(event.id)}, 'rejected')">驳回</button>
              <button class="duplicate" onclick="reviewEvent(${Number(event.id)}, 'duplicate')">标记重复</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  window.refreshEvents = async function(){
    const root = $('reviewGrid');
    if(root && !root.dataset.loadedOnce){
      root.innerHTML = '<div class="muted">正在加载待审核事件...</div>';
    }
    try{
      const res = await fetch('/api/events?status=pending&limit=12&t=' + Date.now(), {cache:'no-store'});
      const data = await res.json();
      if(!res.ok){
        throw new Error(data.message || ('HTTP ' + res.status));
      }
      if(root) root.dataset.loadedOnce = '1';
      renderReviewEvents(data.events || []);
    }catch(err){
      if(root){
        root.innerHTML = '<div class="muted">人工审核队列读取失败：' + escapeHtml(err.message) + '</div>';
      }
    }
  };

  window.reviewEvent = async function(id, status){
    if(reviewBusy) return;
    reviewBusy = true;
    const noteEl = $('note-' + id);
    const note = noteEl ? noteEl.value : '';
    try{
      const res = await fetch('/api/events/' + id + '/review', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({status: status, note: note})
      });
      const data = await res.json();
      if(!res.ok || !data.ok){
        throw new Error(data.message || ('HTTP ' + res.status));
      }
      toast('审核结果已保存', 'success', 1800);
      await window.refreshEvents();
      if(typeof window.refreshOverview === 'function'){
        try{ window.refreshOverview(); }catch(e){}
      }
      if(typeof window.refreshReport === 'function'){
        try{ window.refreshReport(); }catch(e){}
      }
    }catch(err){
      toast('提交审核失败：' + err.message, 'error', 4200);
    }finally{
      reviewBusy = false;
    }
  };

  window.addEventListener('load', function(){
    window.refreshEvents();
    setInterval(window.refreshEvents, 5000);
  });
  window.refreshEvents();
})();
</script>
'''

if marker in text:
    print("skip: review hotfix already exists")
else:
    needle = "</body>\n</html>\n\"\"\""
    if needle not in text:
        raise SystemExit("cannot find dashboard HTML close anchor")
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
echo "=== D. Verify events API ==="
curl --max-time 5 "http://127.0.0.1:5000/api/events?status=pending&limit=3" || true
echo

echo
echo "Done. Open http://192.168.137.82:5000 and press Ctrl+F5 once."
EOF

sh /root/fix_review_queue_hotfix.sh
