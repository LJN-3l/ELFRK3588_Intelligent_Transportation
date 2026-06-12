import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional


def bootstrap_frozen_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return

    base = getattr(sys, "_MEIPASS", "")
    if not base:
        return

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    candidates = [
        base,
        os.path.join(base, "torch", "lib"),
        os.path.join(base, "numpy.libs"),
        os.path.join(base, "scipy.libs"),
        os.path.join(base, "pandas.libs"),
        os.path.join(base, "faiss_cpu.libs"),
        os.path.join(base, "pywin32_system32"),
        os.path.abspath(os.path.join(base, "cv2", "..", "..", "x64", "vc17", "bin")),
    ]

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen or not os.path.isdir(candidate):
            continue
        seen.add(candidate)
        os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(candidate)
        except (AttributeError, FileNotFoundError, OSError):
            pass


bootstrap_frozen_runtime()

from red_light_violation_prototype import RuntimeConfig, ensure_roi_config, run_pipeline, warmup_ml_runtime


TEXTS: Dict[str, Dict[str, str]] = {
    "zh": {
        "window_title": "智能交通检测工作台",
        "hero_title": "智能交通违章检测工作台",
        "hero_subtitle": "导入视频、双模型协同检测、框选红绿灯与斑马线区域，自动保存闯红灯抓拍结果。",
        "badge_1": "默认中文",
        "badge_2": "双模型工作流",
        "badge_3": "支持 K230 迁移",
        "lang_label": "界面语言",
        "card_basic": "基础配置",
        "card_advanced": "检测参数",
        "card_actions": "运行控制",
        "card_status": "运行状态",
        "card_tips": "使用提示",
        "card_log": "运行日志",
        "label_video": "视频文件",
        "label_base_model": "基础模型",
        "label_helmet_model": "头盔模型",
        "label_roi": "ROI 配置",
        "label_output": "输出目录",
        "label_api_url": "网页接口地址",
        "label_source_name": "来源标识",
        "label_conf": "基础置信度",
        "label_helmet_conf": "头盔置信度",
        "label_imgsz": "输入尺寸",
        "label_frame_skip": "抽帧间隔",
        "label_stable_frames": "稳定帧数",
        "label_red_thresh": "红色阈值",
        "label_green_thresh": "绿色阈值",
        "browse": "浏览",
        "clear": "清空",
        "save_video": "保存标注后视频",
        "reconfigure": "下次运行重新框选 ROI",
        "show_preview": "显示 OpenCV 预览窗口",
        "btn_start": "开始检测",
        "btn_stop": "停止检测",
        "btn_open": "打开输出目录",
        "status_title": "当前状态",
        "status_ready": "就绪",
        "status_running": "运行中",
        "status_stopping": "正在停止",
        "status_completed": "已完成：识别到 {count} 次违章",
        "status_failed": "运行失败",
        "tip_1": "页面支持滚轮上下滚动，OpenCV 预览也会自动缩放到固定比例窗口。",
        "tip_2": "第一次运行会弹出 OpenCV 窗口，先框选红绿灯，再点击斑马线多边形。",
        "tip_3": "基础模型负责车辆检测，头盔模型会对摩托车区域做二次识别。",
        "tip_4": "如果红灯识别抖动，可以提高稳定帧数或适当调整红色阈值。",
        "tip_5": "输出目录会保存抓拍图、事件日志，以及可选的标注视频。",
        "ready_log": "已就绪，请先选择视频和模型。",
        "start_log": "开始检测任务...",
        "warmup_log": "正在预热模型运行时，请稍候...",
        "stop_log": "已请求停止，等待当前帧处理完成...",
        "done_log": "任务完成，输出目录：{path}",
        "busy_title": "任务进行中",
        "busy_msg": "当前已有一个检测任务在运行，请先等待它结束。",
        "invalid_title": "输入有误",
        "error_title": "运行失败",
        "error_msg": "检测任务执行失败，请查看日志了解详细信息。",
        "warmup_error": "模型运行时初始化失败，请检查 exe 依赖或模型环境。",
        "select_video": "选择视频文件",
        "select_base_model": "选择基础模型文件",
        "select_helmet_model": "选择头盔模型文件",
        "select_roi": "选择 ROI 配置文件",
        "select_output": "选择输出目录",
        "video_missing": "请先选择一个视频文件。",
        "video_not_found": "所选视频文件不存在。",
        "model_missing": "请提供基础模型路径。",
        "base_model_not_found": "基础模型文件不存在。",
        "helmet_model_not_found": "头盔模型文件不存在。",
        "frame_skip_error": "抽帧间隔至少应为 1。",
        "stable_frames_error": "稳定帧数至少应为 1。",
        "launch_note": "建议同时配置基础模型和头盔模型。预览窗口会自动按固定比例缩放；头盔模型为空时，系统仍可完成闯红灯检测，但不会标注头盔状态。",
    },
    "en": {
        "window_title": "Smart Traffic Assistant",
        "hero_title": "Intelligent Traffic Violation Workbench",
        "hero_subtitle": "Load a video, run a dual-model workflow, mark the traffic light and crosswalk regions, and save violation captures automatically.",
        "badge_1": "Chinese by default",
        "badge_2": "Dual-model workflow",
        "badge_3": "K230 migration ready",
        "lang_label": "Language",
        "card_basic": "Basic Setup",
        "card_advanced": "Detection Parameters",
        "card_actions": "Run Controls",
        "card_status": "Run Status",
        "card_tips": "Tips",
        "card_log": "Run Log",
        "label_video": "Video File",
        "label_base_model": "Base Model",
        "label_helmet_model": "Helmet Model",
        "label_roi": "ROI Config",
        "label_output": "Output Directory",
        "label_api_url": "Dashboard URL",
        "label_source_name": "Source Name",
        "label_conf": "Base Confidence",
        "label_helmet_conf": "Helmet Confidence",
        "label_imgsz": "Input Size",
        "label_frame_skip": "Frame Skip",
        "label_stable_frames": "Stable Frames",
        "label_red_thresh": "Red Threshold",
        "label_green_thresh": "Green Threshold",
        "browse": "Browse",
        "clear": "Clear",
        "save_video": "Save annotated video",
        "reconfigure": "Redraw ROI on next run",
        "show_preview": "Show OpenCV preview window",
        "btn_start": "Start Detection",
        "btn_stop": "Stop",
        "btn_open": "Open Output Folder",
        "status_title": "Current Status",
        "status_ready": "Ready",
        "status_running": "Running",
        "status_stopping": "Stopping",
        "status_completed": "Completed: {count} violation(s)",
        "status_failed": "Failed",
        "tip_1": "The page supports mouse-wheel scrolling, and the OpenCV preview is auto-scaled into a fixed-size window.",
        "tip_2": "On the first run, OpenCV windows will ask you to mark the traffic light and crosswalk ROI.",
        "tip_3": "The base model detects vehicles, while the helmet model performs a second pass on motorcycle regions.",
        "tip_4": "If the light state flickers, increase stable frames or adjust the red threshold.",
        "tip_5": "The output directory stores captures, event logs, and optionally the annotated video.",
        "ready_log": "Ready. Please choose a video and model first.",
        "start_log": "Starting detection task...",
        "warmup_log": "Warming up the model runtime, please wait...",
        "stop_log": "Stop requested. Waiting for the current frame to finish...",
        "done_log": "Run completed. Output directory: {path}",
        "busy_title": "Task Running",
        "busy_msg": "A detection task is already running. Please wait for it to finish.",
        "invalid_title": "Invalid Input",
        "error_title": "Run Failed",
        "error_msg": "The detection task failed. Check the log for details.",
        "warmup_error": "Model runtime initialization failed. Check the exe dependencies or model environment.",
        "select_video": "Select video file",
        "select_base_model": "Select base model file",
        "select_helmet_model": "Select helmet model file",
        "select_roi": "Select ROI config file",
        "select_output": "Select output directory",
        "video_missing": "Please select a video file.",
        "video_not_found": "The selected video file does not exist.",
        "model_missing": "Please provide a base model path.",
        "base_model_not_found": "The base model file does not exist.",
        "helmet_model_not_found": "The helmet model file does not exist.",
        "frame_skip_error": "Frame Skip must be at least 1.",
        "stable_frames_error": "Stable Frames must be at least 1.",
        "launch_note": "It is recommended to configure both a base model and a helmet model. The preview window is auto-scaled to a fixed size; if the helmet model is empty, helmet status will be skipped.",
    },
}


class TrafficApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.geometry("1180x860")
        self.root.minsize(980, 680)
        self.root.configure(bg="#eef3f9")

        base_dir = Path(__file__).resolve().parent
        self.default_output_dir = base_dir / "violation_run_gui"
        self.default_model_dir = Path.home() / "OneDrive" / "Desktop" / "yolo"
        default_base_model = self.default_model_dir / "yolo11n.pt"
        default_helmet_model = self.default_model_dir / "yolov11n_hemlet.pt"

        self.language_var = tk.StringVar(value="中文")
        self.video_var = tk.StringVar()
        self.model_var = tk.StringVar(value=str(default_base_model) if default_base_model.exists() else "yolo11n.pt")
        self.helmet_model_var = tk.StringVar(value=str(default_helmet_model) if default_helmet_model.exists() else "")
        self.config_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(self.default_output_dir))
        self.api_url_var = tk.StringVar(value="")
        self.source_name_var = tk.StringVar(value="desktop_batch")
        self.conf_var = tk.StringVar(value="0.25")
        self.helmet_conf_var = tk.StringVar(value="0.10")
        self.imgsz_var = tk.StringVar(value="320")
        self.frame_skip_var = tk.StringVar(value="1")
        self.stable_frames_var = tk.StringVar(value="5")
        self.red_thresh_var = tk.StringVar(value="0.015")
        self.green_thresh_var = tk.StringVar(value="0.02")
        self.save_video_var = tk.BooleanVar(value=False)
        self.reconfigure_var = tk.BooleanVar(value=True)
        self.show_window_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()
        self.note_var = tk.StringVar()

        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.status_key = "status_ready"
        self.status_kwargs: Dict[str, object] = {}
        self.note_key: Optional[str] = "launch_note"
        self.note_kwargs: Dict[str, object] = {}
        self.note_literal: Optional[str] = None

        self.text_widgets: Dict[str, object] = {}
        self.tip_labels: List[tk.Label] = []
        self.badge_labels: List[tk.Label] = []

        self._configure_styles()
        self._build_ui()
        self._apply_language()
        self.root.after(120, self._poll_queue)

    def tr(self, key: str, **kwargs: object) -> str:
        template = TEXTS[self.current_language()][key]
        return template.format(**kwargs)

    def current_language(self) -> str:
        return "zh" if self.language_var.get() == "中文" else "en"

    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TEntry", padding=8, fieldbackground="#ffffff", bordercolor="#c9d6e8")
        style.configure("App.TCombobox", padding=6)
        style.configure("App.Vertical.TScrollbar", troughcolor="#edf3f9", background="#a3b7cc", arrowcolor="#35506b")

        style.configure(
            "Primary.TButton",
            padding=(16, 10),
            foreground="#ffffff",
            background="#ff6b35",
            borderwidth=0,
            focusthickness=0,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", "#ff7c4c"), ("disabled", "#f2b39b")])

        style.configure(
            "Secondary.TButton",
            padding=(14, 10),
            foreground="#1f3c5a",
            background="#e4eef8",
            borderwidth=0,
            focusthickness=0,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Secondary.TButton", background=[("active", "#d3e4f5")])

        style.configure(
            "Ghost.TButton",
            padding=(12, 10),
            foreground="#4c6b8a",
            background="#ffffff",
            borderwidth=1,
            relief="solid",
            font=("Microsoft YaHei UI", 10),
        )
        style.map("Ghost.TButton", background=[("active", "#f6f9fc")])

        style.configure(
            "Accent.TCheckbutton",
            background="#ffffff",
            foreground="#2b3b4e",
            font=("Microsoft YaHei UI", 10),
        )

    def _build_ui(self) -> None:
        viewport = tk.Frame(self.root, bg="#eef3f9")
        viewport.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(viewport, bg="#eef3f9", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.page_scroll = ttk.Scrollbar(
            viewport,
            orient="vertical",
            command=self.canvas.yview,
            style="App.Vertical.TScrollbar",
        )
        self.page_scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.page_scroll.set)

        self.page = tk.Frame(self.canvas, bg="#eef3f9")
        self.page_window = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", self._on_page_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        shell = tk.Frame(self.page, bg="#eef3f9")
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        shell.grid_columnconfigure(0, weight=7)
        shell.grid_columnconfigure(1, weight=4)

        header = tk.Frame(shell, bg="#143a52", bd=0, highlightthickness=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.grid_columnconfigure(0, weight=1)

        accent_left = tk.Frame(header, bg="#ff6b35", width=12)
        accent_left.grid(row=0, column=0, sticky="nsw")

        content = tk.Frame(header, bg="#143a52", padx=24, pady=22)
        content.grid(row=0, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        self.text_widgets["hero_title"] = tk.Label(
            content,
            bg="#143a52",
            fg="#ffffff",
            font=("Microsoft YaHei UI", 20, "bold"),
            anchor="w",
        )
        self.text_widgets["hero_title"].grid(row=0, column=0, sticky="w")

        self.text_widgets["hero_subtitle"] = tk.Label(
            content,
            bg="#143a52",
            fg="#d4e6f2",
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        )
        self.text_widgets["hero_subtitle"].grid(row=1, column=0, sticky="w", pady=(8, 10))

        badge_bar = tk.Frame(content, bg="#143a52")
        badge_bar.grid(row=2, column=0, sticky="w")
        for _ in range(3):
            badge = tk.Label(
                badge_bar,
                bg="#214d69",
                fg="#eaf5fb",
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=10,
                pady=5,
            )
            badge.pack(side="left", padx=(0, 8))
            self.badge_labels.append(badge)

        lang_wrap = tk.Frame(content, bg="#143a52")
        lang_wrap.grid(row=0, column=1, rowspan=3, sticky="ne", padx=(16, 0))

        self.text_widgets["lang_label"] = tk.Label(
            lang_wrap,
            bg="#143a52",
            fg="#d4e6f2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.text_widgets["lang_label"].pack(anchor="e")

        self.language_combo = ttk.Combobox(
            lang_wrap,
            textvariable=self.language_var,
            values=("中文", "English"),
            state="readonly",
            width=12,
            style="App.TCombobox",
        )
        self.language_combo.pack(anchor="e", pady=(8, 0))
        self.language_combo.bind("<<ComboboxSelected>>", lambda event: self._apply_language())

        left = tk.Frame(shell, bg="#eef3f9")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        left.grid_columnconfigure(0, weight=1)

        right = tk.Frame(shell, bg="#eef3f9")
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        basic_card = self._make_card(left, 0)
        self.text_widgets["card_basic"] = basic_card["title"]
        row = 0
        row = self._add_file_row(basic_card["body"], row, "label_video", self.video_var, self._browse_video)
        row = self._add_file_row(basic_card["body"], row, "label_base_model", self.model_var, self._browse_base_model)
        row = self._add_file_row(
            basic_card["body"],
            row,
            "label_helmet_model",
            self.helmet_model_var,
            self._browse_helmet_model,
            allow_empty=True,
        )
        row = self._add_file_row(basic_card["body"], row, "label_roi", self.config_var, self._browse_config, allow_empty=True)
        row = self._add_dir_row(basic_card["body"], row, "label_output", self.output_var, self._browse_output_dir)
        row = self._add_text_row(basic_card["body"], row, "label_api_url", self.api_url_var)
        self._add_text_row(basic_card["body"], row, "label_source_name", self.source_name_var)

        advanced_card = self._make_card(left, 1)
        self.text_widgets["card_advanced"] = advanced_card["title"]
        form = advanced_card["body"]
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)
        self._add_param_entry(form, 0, 0, "label_conf", self.conf_var)
        self._add_param_entry(form, 0, 2, "label_helmet_conf", self.helmet_conf_var)
        self._add_param_entry(form, 1, 0, "label_imgsz", self.imgsz_var)
        self._add_param_entry(form, 1, 2, "label_frame_skip", self.frame_skip_var)
        self._add_param_entry(form, 2, 0, "label_stable_frames", self.stable_frames_var)
        self._add_param_entry(form, 2, 2, "label_red_thresh", self.red_thresh_var)
        self._add_param_entry(form, 3, 0, "label_green_thresh", self.green_thresh_var)

        actions_card = self._make_card(left, 2)
        self.text_widgets["card_actions"] = actions_card["title"]

        options_wrap = tk.Frame(actions_card["body"], bg="#ffffff")
        options_wrap.pack(fill="x")
        self.text_widgets["save_video"] = ttk.Checkbutton(options_wrap, variable=self.save_video_var, style="Accent.TCheckbutton")
        self.text_widgets["save_video"].pack(anchor="w", pady=(0, 6))
        self.text_widgets["reconfigure"] = ttk.Checkbutton(options_wrap, variable=self.reconfigure_var, style="Accent.TCheckbutton")
        self.text_widgets["reconfigure"].pack(anchor="w", pady=(0, 6))
        self.text_widgets["show_preview"] = ttk.Checkbutton(options_wrap, variable=self.show_window_var, style="Accent.TCheckbutton")
        self.text_widgets["show_preview"].pack(anchor="w", pady=(0, 10))

        button_row = tk.Frame(actions_card["body"], bg="#ffffff")
        button_row.pack(fill="x", pady=(8, 0))
        self.start_btn = ttk.Button(button_row, command=self.start_run, style="Primary.TButton")
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(button_row, command=self.stop_run, style="Secondary.TButton", state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.open_btn = ttk.Button(button_row, command=self.open_output_dir, style="Ghost.TButton")
        self.open_btn.pack(side="left", padx=(10, 0))
        self.text_widgets["btn_start"] = self.start_btn
        self.text_widgets["btn_stop"] = self.stop_btn
        self.text_widgets["btn_open"] = self.open_btn

        self.text_widgets["launch_note"] = tk.Label(
            actions_card["body"],
            bg="#fff5ef",
            fg="#8a4a2f",
            font=("Microsoft YaHei UI", 9),
            justify="left",
            wraplength=620,
            padx=12,
            pady=10,
        )
        self.text_widgets["launch_note"].pack(fill="x", pady=(14, 0))

        status_card = self._make_card(right, 0)
        self.text_widgets["card_status"] = status_card["title"]

        self.text_widgets["status_title"] = tk.Label(
            status_card["body"],
            bg="#ffffff",
            fg="#6a7f95",
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        )
        self.text_widgets["status_title"].pack(anchor="w")

        status_pill = tk.Frame(status_card["body"], bg="#e8f6ee", padx=14, pady=10)
        status_pill.pack(fill="x", pady=(10, 10))
        self.status_display = tk.Label(
            status_pill,
            textvariable=self.status_var,
            bg="#e8f6ee",
            fg="#17824f",
            font=("Microsoft YaHei UI", 14, "bold"),
            anchor="w",
        )
        self.status_display.pack(anchor="w")

        self.note_label = tk.Label(
            status_card["body"],
            textvariable=self.note_var,
            bg="#ffffff",
            fg="#6b7d90",
            font=("Microsoft YaHei UI", 10),
            justify="left",
            wraplength=320,
        )
        self.note_label.pack(anchor="w")

        tips_card = self._make_card(right, 1)
        self.text_widgets["card_tips"] = tips_card["title"]
        for _ in range(5):
            tip = tk.Label(
                tips_card["body"],
                bg="#ffffff",
                fg="#31485f",
                font=("Microsoft YaHei UI", 10),
                justify="left",
                anchor="w",
                wraplength=320,
                padx=2,
                pady=4,
            )
            tip.pack(anchor="w", fill="x")
            self.tip_labels.append(tip)

        log_card = self._make_card(right, 2)
        self.text_widgets["card_log"] = log_card["title"]
        log_body = tk.Frame(log_card["body"], bg="#0f2231", height=320)
        log_body.pack(fill="both", expand=True)
        log_body.pack_propagate(False)

        self.log_text = tk.Text(
            log_body,
            wrap="word",
            height=18,
            font=("Consolas", 10),
            bg="#0f2231",
            fg="#d9edf7",
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=12,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_body, orient="vertical", command=self.log_text.yview, style="App.Vertical.TScrollbar")
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

    def _make_card(self, parent: tk.Frame, row: int) -> Dict[str, tk.Widget]:
        card = tk.Frame(parent, bg="#ffffff", bd=0, highlightthickness=1, highlightbackground="#dce6f2")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 14))

        title = tk.Label(
            card,
            bg="#ffffff",
            fg="#18354f",
            font=("Microsoft YaHei UI", 13, "bold"),
            anchor="w",
            padx=16,
            pady=14,
        )
        title.pack(fill="x")

        divider = tk.Frame(card, bg="#edf3f9", height=1)
        divider.pack(fill="x")

        body = tk.Frame(card, bg="#ffffff", padx=16, pady=16)
        body.pack(fill="both", expand=True)
        return {"card": card, "title": title, "body": body}

    def _add_file_row(
        self,
        parent: tk.Frame,
        row: int,
        label_key: str,
        variable: tk.StringVar,
        command,
        allow_empty: bool = False,
    ) -> int:
        parent.grid_columnconfigure(1, weight=1)
        label = tk.Label(parent, bg="#ffffff", fg="#4a6178", font=("Microsoft YaHei UI", 10), anchor="w")
        label.grid(row=row, column=0, sticky="w", pady=6)
        self.text_widgets[label_key] = label

        ttk.Entry(parent, textvariable=variable, style="App.TEntry").grid(
            row=row, column=1, sticky="ew", padx=(12, 10), pady=6
        )

        buttons = tk.Frame(parent, bg="#ffffff")
        buttons.grid(row=row, column=2, sticky="e")
        browse_btn = ttk.Button(buttons, command=command, style="Secondary.TButton", width=8)
        browse_btn.pack(side="left")
        self.text_widgets[f"{label_key}_browse"] = browse_btn

        if allow_empty:
            clear_btn = ttk.Button(buttons, command=lambda: variable.set(""), style="Ghost.TButton", width=7)
            clear_btn.pack(side="left", padx=(6, 0))
            self.text_widgets[f"{label_key}_clear"] = clear_btn
        return row + 1

    def _add_dir_row(self, parent: tk.Frame, row: int, label_key: str, variable: tk.StringVar, command) -> int:
        parent.grid_columnconfigure(1, weight=1)
        label = tk.Label(parent, bg="#ffffff", fg="#4a6178", font=("Microsoft YaHei UI", 10), anchor="w")
        label.grid(row=row, column=0, sticky="w", pady=6)
        self.text_widgets[label_key] = label

        ttk.Entry(parent, textvariable=variable, style="App.TEntry").grid(
            row=row, column=1, sticky="ew", padx=(12, 10), pady=6
        )
        button = ttk.Button(parent, command=command, style="Secondary.TButton", width=8)
        button.grid(row=row, column=2, sticky="e", pady=6)
        self.text_widgets[f"{label_key}_browse"] = button
        return row + 1

    def _add_text_row(self, parent: tk.Frame, row: int, label_key: str, variable: tk.StringVar) -> int:
        parent.grid_columnconfigure(1, weight=1)
        label = tk.Label(parent, bg="#ffffff", fg="#4a6178", font=("Microsoft YaHei UI", 10), anchor="w")
        label.grid(row=row, column=0, sticky="w", pady=6)
        self.text_widgets[label_key] = label
        ttk.Entry(parent, textvariable=variable, style="App.TEntry").grid(
            row=row, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=6
        )
        return row + 1

    def _add_param_entry(self, parent: tk.Frame, row: int, col: int, label_key: str, variable: tk.StringVar) -> None:
        label = tk.Label(parent, bg="#ffffff", fg="#4a6178", font=("Microsoft YaHei UI", 10), anchor="w")
        label.grid(row=row, column=col, sticky="w", pady=6)
        self.text_widgets[label_key] = label
        ttk.Entry(parent, textvariable=variable, style="App.TEntry", width=12).grid(
            row=row, column=col + 1, sticky="ew", padx=(12, 14), pady=6
        )

    def _apply_language(self) -> None:
        self.root.title(self.tr("window_title"))

        for key in (
            "hero_title",
            "hero_subtitle",
            "lang_label",
            "card_basic",
            "card_advanced",
            "card_actions",
            "card_status",
            "card_tips",
            "card_log",
            "label_video",
            "label_base_model",
            "label_helmet_model",
            "label_roi",
            "label_output",
            "label_api_url",
            "label_source_name",
            "label_conf",
            "label_helmet_conf",
            "label_imgsz",
            "label_frame_skip",
            "label_stable_frames",
            "label_red_thresh",
            "label_green_thresh",
            "save_video",
            "reconfigure",
            "show_preview",
            "btn_start",
            "btn_stop",
            "btn_open",
            "status_title",
            "launch_note",
        ):
            widget = self.text_widgets.get(key)
            if widget is not None:
                widget.configure(text=self.tr(key))

        self.badge_labels[0].configure(text=self.tr("badge_1"))
        self.badge_labels[1].configure(text=self.tr("badge_2"))
        self.badge_labels[2].configure(text=self.tr("badge_3"))

        for key in ("label_video", "label_base_model", "label_helmet_model", "label_roi", "label_output"):
            self.text_widgets[f"{key}_browse"].configure(text=self.tr("browse"))
        for key in ("label_helmet_model", "label_roi"):
            self.text_widgets[f"{key}_clear"].configure(text=self.tr("clear"))

        for idx, tip in enumerate(self.tip_labels, start=1):
            tip.configure(text=f"{idx}. {self.tr(f'tip_{idx}')}")

        self._refresh_status_text()
        self._refresh_note_text()

        if self.log_text.compare("end-1c", "==", "1.0"):
            self._append_log(self.tr("ready_log"))

    def _browse_video(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("select_video"),
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv"), ("All files", "*.*")],
        )
        if path:
            self.video_var.set(path)
            current_config = self.config_var.get().strip()
            if not current_config or Path(current_config).name.endswith("_roi.json"):
                video_path = Path(path)
                self.config_var.set(str(video_path.with_name(f"{video_path.stem}_roi.json")))

    def _browse_base_model(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("select_base_model"),
            filetypes=[("PyTorch model", "*.pt"), ("All files", "*.*")],
        )
        if path:
            self.model_var.set(path)

    def _browse_helmet_model(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("select_helmet_model"),
            filetypes=[("PyTorch model", "*.pt"), ("All files", "*.*")],
        )
        if path:
            self.helmet_model_var.set(path)

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(
            title=self.tr("select_roi"),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.config_var.set(path)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title=self.tr("select_output"))
        if path:
            self.output_var.set(path)

    def start_run(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showinfo(self.tr("busy_title"), self.tr("busy_msg"))
            return

        try:
            config = self._build_config()
        except ValueError as exc:
            messagebox.showerror(self.tr("invalid_title"), str(exc))
            return

        self._append_log("正在准备 ROI 配置...")
        try:
            roi_config_path = ensure_roi_config(
                Path(config.video),
                config.config,
                config.reconfigure,
                max_width=config.preview_max_width,
                max_height=config.preview_max_height,
            )
        except Exception:
            self._append_log(traceback.format_exc())
            messagebox.showerror(self.tr("error_title"), "圈画 ROI 失败，请检查弹出的 OpenCV 窗口后重试。")
            self._set_status("status_failed")
            self._set_note(literal="ROI 圈画未完成")
            return

        config.config = str(roi_config_path)
        config.reconfigure = False
        self._append_log(f"ROI 配置就绪: {roi_config_path.name}")

        self._append_log(self.tr("warmup_log"))
        try:
            warmup_ml_runtime()
        except Exception:
            self._append_log(traceback.format_exc())
            messagebox.showerror(self.tr("error_title"), self.tr("warmup_error"))
            self._set_status("status_failed")
            self._set_note(key="warmup_error")
            return

        self.stop_event.clear()
        self._set_status("status_running")
        self._set_note(key="launch_note")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._append_log(self.tr("start_log"))

        self.worker = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        self.worker.start()

    def stop_run(self) -> None:
        if self.worker is None or not self.worker.is_alive():
            return
        self.stop_event.set()
        self._set_status("status_stopping")
        self._append_log(self.tr("stop_log"))

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_var.get().strip() or self.default_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))

    def _build_config(self) -> RuntimeConfig:
        video = self.video_var.get().strip()
        if not video:
            raise ValueError(self.tr("video_missing"))
        if not Path(video).exists():
            raise ValueError(self.tr("video_not_found"))

        model = self.model_var.get().strip()
        if not model:
            raise ValueError(self.tr("model_missing"))
        if not Path(model).exists() and model != "yolo11n.pt":
            raise ValueError(self.tr("base_model_not_found"))

        helmet_model = self.helmet_model_var.get().strip()
        if helmet_model and not Path(helmet_model).exists():
            raise ValueError(self.tr("helmet_model_not_found"))

        config_path = self.config_var.get().strip()
        output_dir = self.output_var.get().strip() or str(self.default_output_dir)
        api_url = self.api_url_var.get().strip()
        source_name = self.source_name_var.get().strip() or "desktop_batch"

        conf = float(self.conf_var.get().strip())
        helmet_conf = float(self.helmet_conf_var.get().strip())
        imgsz = int(self.imgsz_var.get().strip())
        frame_skip = int(self.frame_skip_var.get().strip())
        stable_frames = int(self.stable_frames_var.get().strip())
        red_thresh = float(self.red_thresh_var.get().strip())
        green_thresh = float(self.green_thresh_var.get().strip())

        if frame_skip < 1:
            raise ValueError(self.tr("frame_skip_error"))
        if stable_frames < 1:
            raise ValueError(self.tr("stable_frames_error"))

        return RuntimeConfig(
            video=video,
            model=model,
            helmet_model=helmet_model,
            config=config_path,
            output_dir=output_dir,
            conf=conf,
            helmet_conf=helmet_conf,
            imgsz=imgsz,
            frame_skip=frame_skip,
            stable_frames=stable_frames,
            red_thresh=red_thresh,
            green_thresh=green_thresh,
            save_video=self.save_video_var.get(),
            reconfigure=self.reconfigure_var.get(),
            show_window=self.show_window_var.get(),
            window_name=self.tr("window_title"),
            language=self.current_language(),
            violation_api_url=api_url,
            source_name=source_name,
            log_callback=self._queue_log,
            should_stop=self.stop_event.is_set,
        )

    def _run_worker(self, config: RuntimeConfig) -> None:
        try:
            result = run_pipeline(config)
            self.log_queue.put(("done", result))
        except Exception:
            self.log_queue.put(("error", traceback.format_exc()))

    def _queue_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _poll_queue(self) -> None:
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "log":
                self._append_log(item[1])
            elif kind == "done":
                result = item[1]
                self._set_status("status_completed", count=result["violation_count"])
                self._set_note(literal=str(result["output_dir"]))
                self._append_log(self.tr("done_log", path=result["output_dir"]))
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
            elif kind == "error":
                self._set_status("status_failed")
                self._set_note(key="error_msg")
                self._append_log(item[1])
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                messagebox.showerror(self.tr("error_title"), self.tr("error_msg"))

        self.root.after(120, self._poll_queue)

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_status(self, key: str, **kwargs: object) -> None:
        self.status_key = key
        self.status_kwargs = kwargs
        self._refresh_status_text()

    def _refresh_status_text(self) -> None:
        self.status_var.set(self.tr(self.status_key, **self.status_kwargs))

    def _set_note(self, key: Optional[str] = None, literal: Optional[str] = None, **kwargs: object) -> None:
        self.note_key = key
        self.note_kwargs = kwargs
        self.note_literal = literal
        self._refresh_note_text()

    def _refresh_note_text(self) -> None:
        if self.note_literal is not None:
            self.note_var.set(self.note_literal)
        elif self.note_key is not None:
            self.note_var.set(self.tr(self.note_key, **self.note_kwargs))
        else:
            self.note_var.set("")

    def _on_page_configure(self, event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.page_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        delta = int(-1 * (event.delta / 120))
        if delta == 0:
            return

        widget = event.widget
        if self._is_descendant(widget, self.log_text):
            self.log_text.yview_scroll(delta, "units")
        else:
            self.canvas.yview_scroll(delta, "units")

    def _is_descendant(self, widget: object, ancestor: object) -> bool:
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            current = getattr(current, "master", None)
        return False


def main() -> None:
    root = tk.Tk()
    TrafficApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
