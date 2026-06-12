cat > /root/add_report_fast_ai_modes.sh <<'EOF'
#!/bin/sh
set -eu

echo "=== A. Patch report fast/AI dual modes ==="
python3 - <<'PY'
from pathlib import Path
from datetime import datetime

path = Path("/root/web_dashboard_v4.py")
text = path.read_text(encoding="utf-8")
backup = Path("/root/web_dashboard_v4.py.bak_report_modes_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print("backup:", backup)

backend_marker = "REPORT_FAST_AI_DUAL_MODE_BACKEND"
if backend_marker not in text:
    backend = r'''
# REPORT_FAST_AI_DUAL_MODE_BACKEND
def clean_report_display_text(text_value: str) -> str:
    value = str(text_value or "").strip()
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.I | re.S).strip()
    value = re.sub(r"^\s*robot\s*:\s*", "", value, flags=re.I).strip()
    value = value.replace("```", "").strip()
    return value


def build_fast_report_package() -> Dict[str, Any]:
    stats, rows = collect_report_rows()
    report_text = build_structured_report_text(stats, rows)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    return {
        "report_text": report_text,
        "report_mode": "draft",
        "message": "快速报告已生成：未调用本地大模型，适合演示和现场快速出结果。",
    }


def build_free_ai_report_package() -> Dict[str, Any]:
    stats, rows = collect_report_rows()
    draft_text = build_structured_report_text(stats, rows)

    if not os.path.exists(LLM_DEMO):
        REPORT_PATH.write_text(draft_text, encoding="utf-8")
        return {
            "report_text": draft_text,
            "report_mode": "draft",
            "message": "未检测到本地 AI 模型，已生成快速结构化报告。",
        }

    prompt = build_ai_report_prompt(stats, rows)
    prompt += (
        "\n\n请直接输出最终报告正文，不要输出思考过程。"
        "如果信息不足，请写“系统未提供”，不要编造。"
    )
    answer = ask_deepseek(
        prompt,
        max_prompt=REPORT_AI_MAX_PROMPT,
        max_gen=REPORT_AI_MAX_GEN,
        timeout=REPORT_AI_TIMEOUT,
    )
    answer = clean_report_display_text(answer)

    if not answer or answer.startswith("请输入问题") or answer.startswith("未找到") or answer.startswith("调用失败"):
        report_text = draft_text
        report_mode = "draft"
        message = "AI 润色超时或失败，已保留快速结构化报告。"
    else:
        report_text = "\n".join([
            "智能交通 AI 审核报告",
            f"生成时间：{now_text()}",
            "",
            answer,
            "",
            "附录｜结构化摘要",
            draft_text,
        ])
        report_mode = "ai"
        message = "AI 润色报告已生成。"

    REPORT_PATH.write_text(report_text, encoding="utf-8")
    return {"report_text": report_text, "report_mode": report_mode, "message": message}


@app.route("/api/report/generate_fast", methods=["POST"])
def api_generate_report_fast_mode() -> Response:
    if get_report_status().get("running"):
        return jsonify({
            "ok": False,
            "message": "AI 报告正在生成中，请稍后再生成快速报告。",
            "running": True,
            "report_text": load_report_text(),
            "report_mode": get_report_status().get("report_mode") or "draft",
        }), 409

    package = build_fast_report_package()
    status = set_report_status(
        running=False,
        ok=True,
        message=str(package["message"]),
        report_text=str(package["report_text"]),
        report_mode=str(package["report_mode"]),
    )
    return jsonify({"ok": True, "started": False, **status})


@app.route("/api/report/generate_ai", methods=["POST"])
def api_generate_report_ai_mode() -> Response:
    with report_lock:
        if REPORT_STATUS.get("running"):
            return jsonify({
                "ok": True,
                "started": False,
                "message": "AI 润色报告已在生成中，请稍候。",
                **dict(REPORT_STATUS),
            }), 200
        REPORT_STATUS.update({
            "running": True,
            "ok": True,
            "message": "AI 润色报告生成中，RK3588 会比快速报告慢一些...",
            "updated_at": now_text(),
            "report_text": load_report_text(),
            "report_mode": "generating",
        })

    def worker() -> None:
        try:
            package = build_free_ai_report_package()
            set_report_status(
                running=False,
                ok=True,
                message=str(package.get("message") or "AI 润色报告已生成。"),
                report_text=str(package.get("report_text") or load_report_text()),
                report_mode=str(package.get("report_mode") or "ai"),
            )
        except Exception as exc:
            app.logger.exception("AI report generation failed")
            package = build_fast_report_package()
            set_report_status(
                running=False,
                ok=False,
                message=f"AI 润色失败：{exc}。已回退为快速结构化报告。",
                report_text=str(package["report_text"]),
                report_mode="draft",
            )

    threading.Thread(target=worker, name="ai-report-generator", daemon=True).start()
    return jsonify({"ok": True, "started": True, **get_report_status()}), 202

'''
    anchor = '@app.route("/api/report")\ndef api_report() -> Response:'
    if anchor not in text:
        raise SystemExit("cannot find /api/report anchor")
    text = text.replace(anchor, backend + "\n" + anchor, 1)
    print("patched: backend routes")
else:
    print("skip: backend already patched")

frontend_marker = "traffic-report-mode-hotfix-js"
if frontend_marker not in text:
    frontend = r'''
<script id="traffic-report-mode-hotfix-js">
(function(){
  const $ = (id) => document.getElementById(id);
  let busy = false;
  let timer = null;

  function toast(msg, kind='info', ms=2600){
    if(typeof window.showToast === 'function'){
      window.showToast(msg, kind, ms);
    }else{
      console.log(kind + ': ' + msg);
    }
  }

  function setBadge(mode){
    const badge = $('reportModeBadge');
    const box = $('reportBox');
    if(!badge || !box) return;
    badge.className = 'report-mode-badge';
    box.classList.remove('ai', 'legacy', 'generating');
    if(mode === 'ai'){
      badge.classList.add('ai');
      box.classList.add('ai');
      badge.textContent = 'AI 润色报告';
    }else if(mode === 'generating'){
      badge.classList.add('generating');
      box.classList.add('generating');
      badge.textContent = 'AI 生成中';
    }else{
      badge.textContent = '快速结构化报告';
    }
  }

  function setBusy(isBusy, mode, hint){
    busy = !!isBusy;
    window.reportBusy = !!isBusy;
    const fastBtn = $('generateReportBtn');
    const aiBtn = $('generateAiReportBtn');
    const hintBox = $('reportHint');
    if(fastBtn){
      fastBtn.disabled = !!isBusy;
      fastBtn.innerHTML = isBusy && mode === 'fast' ? '<span class="btn-loader">快速生成中...</span>' : '快速报告';
    }
    if(aiBtn){
      aiBtn.disabled = !!isBusy;
      aiBtn.innerHTML = isBusy && mode === 'ai' ? '<span class="btn-loader">AI 润色中...</span>' : 'AI润色报告';
    }
    if(hintBox && hint){
      hintBox.textContent = hint;
    }
    if(isBusy){
      setBadge(mode === 'ai' ? 'generating' : 'draft');
    }
  }

  async function loadReportStatus(){
    const res = await fetch('/api/report/status?t=' + Date.now(), {cache:'no-store'});
    const status = await res.json();
    const box = $('reportBox');
    const hint = $('reportHint');
    if(box && status.report_text){
      box.textContent = status.report_text;
    }
    if(hint && status.message){
      hint.textContent = status.message;
    }
    setBadge(status.running ? 'generating' : (status.report_mode || 'draft'));
    return status;
  }

  function pollAi(){
    if(timer) clearInterval(timer);
    let count = 0;
    timer = setInterval(async function(){
      count += 1;
      try{
        const status = await loadReportStatus();
        if(!status.running || count > 120){
          clearInterval(timer);
          timer = null;
          setBusy(false, 'ai', status.message || 'AI 报告任务结束。');
          toast(status.ok ? 'AI 报告已完成' : 'AI 报告失败，已回退快速报告', status.ok ? 'success' : 'error', 3200);
        }
      }catch(err){
        if(count > 12){
          clearInterval(timer);
          timer = null;
          setBusy(false, 'ai', '报告状态读取失败，请查看 /root/dashboard.log');
          toast('报告状态读取失败：' + err.message, 'error', 4200);
        }
      }
    }, 1000);
  }

  window.generateReport = async function(mode='fast'){
    if(busy) return;
    const isAi = mode === 'ai';
    setBusy(true, isAi ? 'ai' : 'fast', isAi ? 'AI 润色报告生成中，可能需要几十秒...' : '快速报告生成中，通常 1 秒内完成...');
    toast(isAi ? '已启动 AI 润色报告' : '正在生成快速报告', 'info', 1800);
    try{
      const endpoint = isAi ? '/api/report/generate_ai' : '/api/report/generate_fast';
      const res = await fetch(endpoint + '?t=' + Date.now(), {method:'POST', cache:'no-store'});
      const data = await res.json();
      if(!res.ok || !data.ok){
        throw new Error(data.message || ('HTTP ' + res.status));
      }
      if(data.report_text && $('reportBox')){
        $('reportBox').textContent = data.report_text;
      }
      if(isAi && data.running){
        pollAi();
      }else if(isAi && data.started){
        pollAi();
      }else{
        setBusy(false, 'fast', data.message || '快速报告已生成。');
        setBadge(data.report_mode || 'draft');
        toast(data.message || '快速报告已生成', 'success', 2600);
      }
    }catch(err){
      setBusy(false, isAi ? 'ai' : 'fast', '报告生成失败，请查看后端日志。');
      toast('生成报告失败：' + err.message, 'error', 4800);
    }
  };

  function installButtons(){
    const fastBtn = $('generateReportBtn');
    if(!fastBtn) return;
    fastBtn.textContent = '快速报告';
    fastBtn.onclick = function(){ window.generateReport('fast'); };
    if(!$('generateAiReportBtn')){
      const aiBtn = document.createElement('button');
      aiBtn.id = 'generateAiReportBtn';
      aiBtn.type = 'button';
      aiBtn.textContent = 'AI润色报告';
      aiBtn.onclick = function(){ window.generateReport('ai'); };
      fastBtn.insertAdjacentElement('afterend', aiBtn);
    }
    const hint = $('reportHint');
    if(hint){
      hint.textContent = '快速报告：秒出、稳定、适合现场演示；AI润色报告：调用 RK3588 本地 DeepSeek，内容更像正式简报但会更慢。';
    }
  }

  window.addEventListener('load', function(){
    installButtons();
    loadReportStatus().catch(function(){});
  });
  installButtons();
})();
</script>
'''
    needle = "</body>\n</html>\n\"\"\""
    if needle not in text:
        raise SystemExit("cannot find dashboard HTML </body> anchor")
    text = text.replace(needle, frontend + "\n</body>\n</html>\n\"\"\"", 1)
    print("patched: frontend buttons")
else:
    print("skip: frontend already patched")

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
pkill -f llm_demo 2>/dev/null || true
sleep 1
nohup sh /root/start_rk_yolo_dashboard.sh > /root/dashboard.log 2>&1 &
sleep 6

echo
echo "=== D. Test fast report ==="
curl --max-time 8 -X POST http://127.0.0.1:5000/api/report/generate_fast || true
echo

echo
echo "=== E. Status ==="
curl --max-time 5 http://127.0.0.1:5000/api/report/status || true
echo

echo
echo "Done. Open http://192.168.137.82:5000 and press Ctrl+F5 once."
EOF

sh /root/add_report_fast_ai_modes.sh
