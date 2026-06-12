#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
\u57fa\u4e8e\u7528\u6237\u73b0\u6709 RK3588 Flask \u4eea\u8868\u76d8\u6539\u9020\u7684\u53cc\u7aef\u4e92\u901a\u7248\u3002

\u4fdd\u7559\u539f\u6709\u4e3b\u8def\u7531\uff1a
- /
- /chat
- /api/stats
- /video_status
- /video_proxy
- /generate_report
- /chat_ask

\u65b0\u589e\u80fd\u529b\uff1a
1. \u684c\u9762\u7aef\u6279\u5904\u7406\u7ed3\u679c\u53ef\u901a\u8fc7 /api/upload_violation \u4e0a\u4f20\u5230 RK3588 \u7f51\u9875\u7aef
2. \u7f51\u9875\u7aef\u63d0\u4f9b\u4eba\u5de5\u5ba1\u6838\u3001\u53bb\u91cd\u3001\u786e\u8ba4 / \u9a73\u56de
3. \u7f51\u9875\u7aef\u53ef\u751f\u6210\u57fa\u4e8e\u5ba1\u6838\u7ed3\u679c\u7684\u62a5\u544a
4. \u53ef\u9009\u5f00\u542f RK3588 \u672c\u5730\u5728\u7ebf YOLO \u8f85\u52a9\u5206\u6790\uff0c\u5e76\u5728\u7f51\u9875\u663e\u793a AI \u53e0\u52a0\u753b\u9762
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None


app = Flask(__name__)
chat_lock = threading.Lock()
report_lock = threading.Lock()
REPORT_STATUS: Dict[str, Any] = {
    "running": False,
    "ok": True,
    "message": "",
    "updated_at": "",
    "report_text": "",
    "report_mode": "draft",
}
traffic_flow_lock = threading.Lock()
TRAFFIC_FLOW_STATUS: Dict[str, Any] = {
    "source": "none",
    "vehicle_count": 0,
    "status": "unknown",
    "status_label": "等待数据",
    "counts": {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0},
    "updated_at": "",
    "frame_index": 0,
    "slow_threshold": 5,
    "jam_threshold": 10,
}


HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "5000"))

STREAM_URL = os.environ.get("LIVE_STREAM_URL", "http://127.0.0.1:5001/video")
STATUS_URL = os.environ.get("LIVE_STATUS_URL", "http://127.0.0.1:5001/status")

LLM_DEMO = os.environ.get("LLM_DEMO", "/root/Deepseek/demo_Linux_aarch64/llm_demo")
MODEL_PATH = os.environ.get("LLM_MODEL_PATH", "/root/Deepseek/DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm")
WORK_DIR = os.environ.get("LLM_WORK_DIR", "/root/Deepseek/demo_Linux_aarch64")

DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", "/root/puff_traffic_dashboard"))
IMAGE_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "violations.sqlite3"
REPORT_PATH = DATA_DIR / "report.txt"
LEGACY_REPORT_SCRIPT = os.environ.get("LEGACY_REPORT_SCRIPT", "/root/auto_analyze_final.py")
ENABLE_LEGACY_REPORT = os.environ.get("ENABLE_LEGACY_REPORT", "0").strip().lower() in {"1", "true", "yes", "on"}
REPORT_AI_MODE = os.environ.get("REPORT_AI_MODE", "deepseek").strip().lower()
REPORT_AI_MAX_PROMPT = max(512, int(os.environ.get("REPORT_AI_MAX_PROMPT", "1024")))
REPORT_AI_MAX_GEN = max(192, int(os.environ.get("REPORT_AI_MAX_GEN", "420")))
REPORT_AI_TIMEOUT = max(20, int(os.environ.get("REPORT_AI_TIMEOUT", "75")))
REPORT_AI_APPEND_DRAFT = os.environ.get("REPORT_AI_APPEND_DRAFT", "1").strip().lower() in {"1", "true", "yes", "on"}

LIVE_ENABLE_AI = os.environ.get("LIVE_ENABLE_AI", "1").strip().lower() in {"1", "true", "yes", "on"}
LIVE_BASE_MODEL = os.environ.get("LIVE_BASE_MODEL", "/root/models/yolo11n.pt")
LIVE_HELMET_MODEL = os.environ.get("LIVE_HELMET_MODEL", "")
LIVE_ROI_JSON = os.environ.get("LIVE_ROI_JSON", "/root/live_roi.json")
LIVE_SOURCE_NAME = os.environ.get("LIVE_SOURCE_NAME", "k230_live")
LIVE_VIEW_HFLIP = os.environ.get("LIVE_VIEW_HFLIP", "0").strip().lower() in {"1", "true", "yes", "on"}
LIVE_VIEW_VFLIP = os.environ.get("LIVE_VIEW_VFLIP", "0").strip().lower() in {"1", "true", "yes", "on"}
LIVE_FRAME_STRIDE = max(1, int(os.environ.get("LIVE_FRAME_STRIDE", "2")))
LIVE_CONF = float(os.environ.get("LIVE_CONF", "0.25"))
LIVE_HELMET_CONF = float(os.environ.get("LIVE_HELMET_CONF", "0.12"))
LIVE_IMGSZ = int(os.environ.get("LIVE_IMGSZ", "320"))
LIVE_STABLE_FRAMES = max(1, int(os.environ.get("LIVE_STABLE_FRAMES", "4")))
LIVE_RED_THRESH = float(os.environ.get("LIVE_RED_THRESH", "0.015"))
LIVE_GREEN_THRESH = float(os.environ.get("LIVE_GREEN_THRESH", "0.02"))
LIVE_HELMET_INTERVAL_SECONDS = float(os.environ.get("LIVE_HELMET_INTERVAL_SECONDS", "0.35"))
LIVE_EVENT_COOLDOWN_SECONDS = float(os.environ.get("LIVE_EVENT_COOLDOWN_SECONDS", "4.0"))
TRAFFIC_FLOW_SLOW_THRESHOLD = max(1, int(os.environ.get("TRAFFIC_FLOW_SLOW_THRESHOLD", "5")))
TRAFFIC_FLOW_JAM_THRESHOLD = max(
    TRAFFIC_FLOW_SLOW_THRESHOLD + 1,
    int(os.environ.get("TRAFFIC_FLOW_JAM_THRESHOLD", "10")),
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


if np is not None:
    RED_RANGE_1_LOWER = np.array([0, 25, 35], dtype=np.uint8)
    RED_RANGE_1_UPPER = np.array([20, 255, 255], dtype=np.uint8)
    RED_RANGE_2_LOWER = np.array([140, 25, 35], dtype=np.uint8)
    RED_RANGE_2_UPPER = np.array([180, 255, 255], dtype=np.uint8)
    GREEN_RANGE_LOWER = np.array([35, 45, 45], dtype=np.uint8)
    GREEN_RANGE_UPPER = np.array([100, 255, 255], dtype=np.uint8)
else:
    RED_RANGE_1_LOWER = None
    RED_RANGE_1_UPPER = None
    RED_RANGE_2_LOWER = None
    RED_RANGE_2_UPPER = None
    GREEN_RANGE_LOWER = None
    GREEN_RANGE_UPPER = None

DEFAULT_CLASS_NAMES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

CAR_ALIASES = {
    "car",
    "vehicle",
    "auto",
    "sedan",
    "van",
    "\u673a\u52a8\u8f66",
    "\u6c7d\u8f66",
    "\u5c0f\u6c7d\u8f66",
    "\u8f7f\u8f66",
}
MOTORCYCLE_ALIASES = {
    "motorcycle",
    "motorbike",
    "moto",
    "bike",
    "scooter",
    "moped",
    "\u6469\u6258\u8f66",
    "\u7535\u52a8\u8f66",
    "\u673a\u8f66",
}
BUS_ALIASES = {"bus", "coach", "minibus", "\u516c\u4ea4\u8f66", "\u5ba2\u8f66", "\u5df4\u58eb"}
TRUCK_ALIASES = {"truck", "lorry", "pickup", "\u8d27\u8f66", "\u5361\u8f66", "\u5de5\u7a0b\u8f66"}
HELMET_ALIASES = {"helmet", "withhelmet", "wearhelmet", "safetyhelmet", "\u5934\u76d4", "\u6234\u5934\u76d4"}
NO_HELMET_ALIASES = {"nohelmet", "withouthelmet", "unhelmeted", "\u672a\u6234\u5934\u76d4", "\u4e0d\u6234\u5934\u76d4", "\u65e0\u5934\u76d4"}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def normalize_status(status: str) -> str:
    value = (status or "pending").strip().lower()
    if value not in {"pending", "approved", "rejected", "duplicate"}:
        return "pending"
    return value


def status_label(status: str) -> str:
    mapping = {
        "pending": "\u5f85\u5ba1\u6838",
        "approved": "\u5df2\u786e\u8ba4",
        "rejected": "\u5df2\u9a73\u56de",
        "duplicate": "\u91cd\u590d\u4e8b\u4ef6",
    }
    return mapping.get(status, status)


def normalize_reason_label(reason_code: str, reason_label: str) -> str:
    if reason_label.strip():
        return reason_label.strip()
    mapping = {
        "red_light_violation": "\u95ef\u7ea2\u706f",
        "no_helmet": "\u672a\u6234\u5934\u76d4",
        "helmet": "\u5df2\u6234\u5934\u76d4",
        "manual": "\u4eba\u5de5\u6807\u6ce8",
    }
    return mapping.get(reason_code, reason_code)


def ask_deepseek(prompt: str, max_prompt: int = 2048, max_gen: int = 1024, timeout: int = 120) -> str:
    if not prompt.strip():
        return "\u8bf7\u8f93\u5165\u95ee\u9898\u3002"
    if not os.path.exists(LLM_DEMO):
        return "\u672a\u627e\u5230 Deepseek \u53ef\u6267\u884c\u6587\u4ef6\uff0c\u8bf7\u68c0\u67e5 LLM_DEMO \u8def\u5f84\u3002"

    child = None
    with chat_lock:
        try:
            import pexpect

            child = pexpect.spawn(
                LLM_DEMO,
                [MODEL_PATH, str(max_prompt), str(max_gen)],
                cwd=WORK_DIR,
                env={"LD_LIBRARY_PATH": "./lib", "HOME": "/root"},
                encoding="utf-8",
                timeout=timeout,
                echo=False,
            )
            child.expect("user:", timeout=60)
            child.sendline(prompt)
            child.expect("user:", timeout=timeout)
            answer = child.before.replace(prompt, "").strip()
            return answer or "\u6a21\u578b\u6ca1\u6709\u8fd4\u56de\u5185\u5bb9\u3002"
        except Exception as exc:
            return f"\u8c03\u7528\u5931\u8d25\uff1a{exc}"
        finally:
            if child is not None:
                try:
                    child.close(force=True)
                except Exception:
                    pass


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_time TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                reason_label TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'pending',
                review_note TEXT NOT NULL DEFAULT '',
                review_updated_at TEXT,
                image_path TEXT NOT NULL DEFAULT '',
                image_sha1 TEXT NOT NULL DEFAULT '',
                duplicate_of INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_status ON violations(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_created_at ON violations(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_source ON violations(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_violations_sha1 ON violations(image_sha1)")


def save_image_bytes(image_bytes: bytes, hint: str) -> Path:
    suffix = ".jpg"
    name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hint}_{secrets.token_hex(4)}{suffix}"
    out_path = IMAGE_DIR / name
    out_path.write_bytes(image_bytes)
    return out_path


def find_duplicate_event_id(image_sha1: str) -> Optional[int]:
    if not image_sha1:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM violations WHERE image_sha1 = ? ORDER BY id ASC LIMIT 1",
            (image_sha1,),
        ).fetchone()
    return int(row["id"]) if row is not None else None


def insert_event(
    *,
    source: str,
    reason_code: str,
    reason_label: str,
    confidence: float,
    event_time: str,
    image_bytes: Optional[bytes],
    metadata: Dict[str, Any],
) -> int:
    image_path = ""
    image_sha1 = ""
    duplicate_of = None
    status = "pending"
    review_note = ""

    if image_bytes:
        image_sha1 = hashlib.sha1(image_bytes).hexdigest()
        duplicate_of = find_duplicate_event_id(image_sha1)
        image_path = str(save_image_bytes(image_bytes, reason_code))
        if duplicate_of is not None:
            status = "duplicate"
            review_note = f"\u7cfb\u7edf\u5224\u5b9a\u4e0e\u4e8b\u4ef6 #{duplicate_of} \u56fe\u7247\u4e00\u81f4"

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO violations (
                created_at, event_time, source, reason_code, reason_label, confidence,
                status, review_note, review_updated_at, image_path, image_sha1, duplicate_of, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                now_text(),
                str(event_time),
                source or "desktop_batch",
                reason_code or "unknown",
                normalize_reason_label(reason_code or "unknown", reason_label or ""),
                float(confidence),
                status,
                review_note,
                image_path,
                image_sha1,
                duplicate_of,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def serialize_event(row: sqlite3.Row) -> Dict[str, Any]:
    image_name = Path(row["image_path"]).name if row["image_path"] else ""
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "event_time": row["event_time"],
        "source": row["source"],
        "reason_code": row["reason_code"],
        "reason_label": row["reason_label"],
        "confidence": round(float(row["confidence"] or 0.0), 3),
        "status": row["status"],
        "status_label": status_label(row["status"]),
        "review_note": row["review_note"],
        "review_updated_at": row["review_updated_at"],
        "duplicate_of": row["duplicate_of"],
        "image_url": f"/images/{image_name}" if image_name else "",
        "metadata": metadata,
    }


def list_events(status: str = "", limit: int = 24) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM violations WHERE status = ? ORDER BY id DESC LIMIT ?",
                (normalize_status(status), limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM violations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [serialize_event(row) for row in rows]


def update_review(event_id: int, status: str, note: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE violations
            SET status = ?, review_note = ?, review_updated_at = ?
            WHERE id = ?
            """,
            (normalize_status(status), (note or "").strip(), now_text(), event_id),
        )


def compute_stats() -> Dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count,
                SUM(CASE WHEN status = 'duplicate' THEN 1 ELSE 0 END) AS duplicate_count,
                SUM(CASE WHEN reason_code = 'red_light_violation' AND status IN ('pending', 'approved') THEN 1 ELSE 0 END) AS red_light_count,
                SUM(CASE WHEN reason_code = 'no_helmet' AND status IN ('pending', 'approved') THEN 1 ELSE 0 END) AS no_helmet_count,
                SUM(CASE WHEN reason_code = 'helmet' AND status IN ('pending', 'approved') THEN 1 ELSE 0 END) AS helmet_count
            FROM violations
            """
        ).fetchone()
        source_rows = conn.execute(
            """
            SELECT source, COUNT(*) AS cnt
            FROM violations
            GROUP BY source
            ORDER BY cnt DESC
            LIMIT 8
            """
        ).fetchall()

    total_count = int(row["total_count"] or 0)
    pending_count = int(row["pending_count"] or 0)
    approved_count = int(row["approved_count"] or 0)
    rejected_count = int(row["rejected_count"] or 0)
    duplicate_count = int(row["duplicate_count"] or 0)
    red_light_count = int(row["red_light_count"] or 0)
    no_helmet_count = int(row["no_helmet_count"] or 0)
    helmet_count = int(row["helmet_count"] or 0)

    return {
        "total_count": total_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "duplicate_count": duplicate_count,
        "red_light_count": red_light_count,
        "no_helmet_count": no_helmet_count,
        "helmet_count": helmet_count,
        "sources": [{"source": item["source"], "count": int(item["cnt"] or 0)} for item in source_rows],
        "helmet": {"\u6234\u5934\u76d4": helmet_count, "\u672a\u6234\u5934\u76d4": no_helmet_count},
        "red_light": red_light_count,
        "valid": pending_count + approved_count,
        "excluded": rejected_count + duplicate_count,
    }


def default_report_text() -> str:
    return "\u6682\u65e0\u62a5\u544a\uff0c\u8bf7\u5148\u5b8c\u6210\u4eba\u5de5\u5ba1\u6838\u540e\u70b9\u51fb\u201c\u751f\u6210\u62a5\u544a\u201d\u3002"


def load_report_text() -> str:
    if REPORT_PATH.exists():
        return REPORT_PATH.read_text(encoding="utf-8")
    return default_report_text()


def maybe_run_legacy_report() -> Optional[str]:
    if not ENABLE_LEGACY_REPORT:
        return None
    script_path = Path(LEGACY_REPORT_SCRIPT)
    if not script_path.exists():
        return None
    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(script_path.parent),
            timeout=180,
        )
        if result.returncode == 0:
            legacy_text = (result.stdout or "").strip()
            if legacy_text:
                return legacy_text
            return "\u65e7\u94fe\u8def\u5206\u6790\u811a\u672c\u4e5f\u5df2\u6267\u884c\u5b8c\u6210\u3002"
        return f"\u65e7\u94fe\u8def\u5206\u6790\u811a\u672c\u6267\u884c\u5931\u8d25\uff1a{result.stderr or result.stdout}"
    except Exception as exc:
        return f"\u65e7\u94fe\u8def\u5206\u6790\u811a\u672c\u5f02\u5e38\uff1a{exc}"


def collect_report_rows() -> Tuple[Dict[str, Any], List[sqlite3.Row]]:
    stats = compute_stats()
    with get_db() as conn:
        approved_rows = conn.execute(
            "SELECT * FROM violations WHERE status = 'approved' ORDER BY id DESC"
        ).fetchall()
        pending_rows = conn.execute(
            "SELECT * FROM violations WHERE status = 'pending' ORDER BY id DESC"
        ).fetchall()

    rows = approved_rows if approved_rows else pending_rows
    return stats, list(rows)


def build_structured_report_text(stats: Dict[str, Any], rows: List[sqlite3.Row]) -> str:
    lines = [
        "\u4ea4\u901a\u8fdd\u6cd5\u5ba1\u6838\u62a5\u544a",
        f"\u751f\u6210\u65f6\u95f4\uff1a{now_text()}",
        "",
        "\u7edf\u8ba1\u6982\u89c8",
        f"- \u603b\u4e8b\u4ef6\u6570\uff1a{stats['total_count']}",
        f"- \u5f85\u5ba1\u6838\uff1a{stats['pending_count']}",
        f"- \u5df2\u786e\u8ba4\uff1a{stats['approved_count']}",
        f"- \u5df2\u9a73\u56de\uff1a{stats['rejected_count']}",
        f"- \u91cd\u590d\u4e8b\u4ef6\uff1a{stats['duplicate_count']}",
        f"- \u95ef\u7ea2\u706f\uff1a{stats['red_light_count']}",
        f"- \u672a\u6234\u5934\u76d4\uff1a{stats['no_helmet_count']}",
        "",
        "\u4e8b\u4ef6\u660e\u7ec6",
    ]

    if not rows:
        lines.append("- \u6682\u65e0\u53ef\u5199\u5165\u62a5\u544a\u7684\u4e8b\u4ef6\u3002")
    else:
        for index, row in enumerate(rows, start=1):
            event = serialize_event(row)
            lines.append(
                f"{index}. {event['created_at']} | {event['reason_label']} | "
                f"\u7f6e\u4fe1\u5ea6 {event['confidence']:.2f} | \u6765\u6e90 {event['source']} | \u72b6\u6001 {event['status_label']}"
            )
            meta = event["metadata"]
            if meta.get("class_name"):
                lines.append(f"   \u76ee\u6807\u7c7b\u578b\uff1a{meta['class_name']}")
            if meta.get("helmet_status"):
                lines.append(f"   \u5934\u76d4\u72b6\u6001\uff1a{meta['helmet_status']}")
            if event["review_note"]:
                lines.append(f"   \u5ba1\u6838\u5907\u6ce8\uff1a{event['review_note']}")
            if event["image_url"]:
                lines.append(f"   \u56fe\u7247\u5730\u5740\uff1a{event['image_url']}")

    return "\n".join(lines)


def build_ai_report_prompt(stats: Dict[str, Any], rows: List[sqlite3.Row]) -> str:
    items: List[str] = []
    for index, row in enumerate(rows[:8], start=1):
        event = serialize_event(row)
        meta = event["metadata"]
        details = [
            f"{index}. {event['created_at']} | {event['reason_label']} | \u7f6e\u4fe1\u5ea6 {event['confidence']:.2f} | \u6765\u6e90 {event['source']} | \u72b6\u6001 {event['status_label']}",
        ]
        if meta.get("class_name"):
            details.append(f"   \u7c7b\u578b\uff1a{meta['class_name']}")
        if meta.get("helmet_status"):
            details.append(f"   \u5934\u76d4\uff1a{meta['helmet_status']}")
        if event["review_note"]:
            details.append(f"   \u5907\u6ce8\uff1a{event['review_note']}")
        items.append("\n".join(details))

    events_text = "\n".join(items) if items else "- \u6682\u65e0\u53ef\u7528\u4e8b\u4ef6"
    return (
        "\u4f60\u662f\u4e00\u540d\u4ea4\u901a\u6267\u6cd5\u62a5\u544a\u64b0\u5199\u52a9\u7406\u3002\n"
        "\u8bf7\u57fa\u4e8e\u4ee5\u4e0b\u7edf\u8ba1\u4e0e\u4e8b\u4ef6\uff0c\u7528\u4e2d\u6587\u5199\u4e00\u4efd\u6b63\u5f0f\u3001\u6d41\u7545\u3001\u4e0d\u5938\u5f20\u7684\u667a\u80fd\u4ea4\u901a\u5ba1\u6838\u62a5\u544a\u3002\n"
        "\u8981\u6c42\uff1a\n"
        "1. \u8f93\u51fa\u7ed3\u6784\u5305\u542b\uff1a\u603b\u4f53\u7ed3\u8bba\u3001\u6838\u5fc3\u53d1\u73b0\u3001\u5178\u578b\u4e8b\u4ef6\u3001\u5904\u7f6e\u5efa\u8bae\u3002\n"
        "2. \u8bed\u6c14\u8981\u50cf\u6210\u54c1\u8f6f\u4ef6\u81ea\u52a8\u751f\u6210\u7684\u6267\u6cd5\u7b80\u62a5\uff0c\u7b80\u6d01\u4f46\u4e0d\u8981\u751f\u786c\u3002\n"
        "3. \u4e0d\u8981\u7f16\u9020\u6ca1\u6709\u63d0\u4f9b\u7684\u6570\u636e\u6216\u6cd5\u6761\u3002\n"
        "4. \u4e0d\u8981\u8f93\u51fa Markdown \u4ee3\u7801\u5757\u3002\n"
        "5. \u6b63\u6587\u63a7\u5236\u5728 450 \u5230 800 \u5b57\u4e4b\u95f4\u3002\n\n"
        f"\u603b\u4e8b\u4ef6\u6570\uff1a{stats['total_count']}\n"
        f"\u5f85\u5ba1\u6838\uff1a{stats['pending_count']}\n"
        f"\u5df2\u786e\u8ba4\uff1a{stats['approved_count']}\n"
        f"\u5df2\u9a73\u56de\uff1a{stats['rejected_count']}\n"
        f"\u91cd\u590d\u4e8b\u4ef6\uff1a{stats['duplicate_count']}\n"
        f"\u95ef\u7ea2\u706f\uff1a{stats['red_light_count']}\n"
        f"\u672a\u6234\u5934\u76d4\uff1a{stats['no_helmet_count']}\n\n"
        "\u5178\u578b\u4e8b\u4ef6\uff1a\n"
        f"{events_text}\n"
    )


def build_ai_report_text(stats: Dict[str, Any], rows: List[sqlite3.Row], draft_text: str) -> Tuple[Optional[str], str]:
    mode = REPORT_AI_MODE.strip().lower()
    if mode in {"off", "draft", "structured"}:
        return None, "\u5f53\u524d\u4e3a\u7ed3\u6784\u5316\u62a5\u544a\u6a21\u5f0f\u3002"
    if mode == "legacy":
        legacy_text = maybe_run_legacy_report()
        if legacy_text and "\u6267\u884c\u5931\u8d25" not in legacy_text and "\u5f02\u5e38" not in legacy_text:
            return legacy_text, "\u65e7\u7248 AI \u811a\u672c\u62a5\u544a\u5df2\u751f\u6210\u3002"
        return None, legacy_text or "\u65e7\u7248 AI \u811a\u672c\u4e0d\u53ef\u7528\uff0c\u5df2\u56de\u9000\u5230\u7ed3\u6784\u5316\u62a5\u544a\u3002"
    if not os.path.exists(LLM_DEMO):
        return None, "\u672a\u68c0\u6d4b\u5230\u672c\u5730 AI \u62a5\u544a\u6a21\u578b\uff0c\u5df2\u56de\u9000\u5230\u7ed3\u6784\u5316\u62a5\u544a\u3002"

    prompt = build_ai_report_prompt(stats, rows)
    answer = ask_deepseek(
        prompt,
        max_prompt=REPORT_AI_MAX_PROMPT,
        max_gen=REPORT_AI_MAX_GEN,
        timeout=REPORT_AI_TIMEOUT,
    ).strip()
    if not answer or answer.startswith("\u8bf7\u8f93\u5165\u95ee\u9898") or answer.startswith("\u672a\u627e\u5230") or answer.startswith("\u8c03\u7528\u5931\u8d25"):
        return None, answer or "AI \u62a5\u544a\u751f\u6210\u5931\u8d25\uff0c\u5df2\u56de\u9000\u5230\u7ed3\u6784\u5316\u62a5\u544a\u3002"

    lines = [
        "\u667a\u80fd\u4ea4\u901a AI \u5ba1\u6838\u62a5\u544a",
        f"\u751f\u6210\u65f6\u95f4\uff1a{now_text()}",
        "",
        answer,
    ]
    if REPORT_AI_APPEND_DRAFT:
        lines.extend(["", "\u9644\u5f55\uff5c\u7ed3\u6784\u5316\u6458\u8981", draft_text])
    return "\n".join(lines), "AI \u6da6\u8272\u62a5\u544a\u5df2\u751f\u6210\u3002"


def build_report_package() -> Dict[str, Any]:
    stats, rows = collect_report_rows()
    draft_text = build_structured_report_text(stats, rows)
    report_text = draft_text
    report_mode = "draft"
    message = "\u7ed3\u6784\u5316\u62a5\u544a\u5df2\u751f\u6210\u3002"

    ai_text, ai_message = build_ai_report_text(stats, rows, draft_text)
    if ai_text:
        report_text = ai_text
        report_mode = "ai" if REPORT_AI_MODE != "legacy" else "legacy"
        message = ai_message
    elif ai_message:
        message = ai_message

    if report_mode != "legacy":
        legacy_message = maybe_run_legacy_report()
        if legacy_message:
            report_text = report_text + "\n\n\u5916\u90e8\u811a\u672c\u4fe1\u606f\n" + legacy_message
            if report_mode == "draft":
                message = "\u7ed3\u6784\u5316\u62a5\u544a\u5df2\u751f\u6210\uff0c\u5e76\u5df2\u5c1d\u8bd5\u5916\u90e8\u811a\u672c\u5206\u6790\u3002"

    REPORT_PATH.write_text(report_text, encoding="utf-8")
    return {"report_text": report_text, "report_mode": report_mode, "message": message}


def build_report_text() -> str:
    return build_report_package()["report_text"]


def set_report_status(
    *,
    running: bool,
    ok: bool,
    message: str,
    report_text: Optional[str] = None,
    report_mode: Optional[str] = None,
) -> Dict[str, Any]:
    with report_lock:
        if report_text is None:
            report_text = REPORT_STATUS.get("report_text") or load_report_text()
        if report_mode is None:
            report_mode = str(REPORT_STATUS.get("report_mode") or "draft")
        REPORT_STATUS.update(
            {
                "running": running,
                "ok": ok,
                "message": message,
                "updated_at": now_text(),
                "report_text": report_text,
                "report_mode": report_mode,
            }
        )
        return dict(REPORT_STATUS)


def get_report_status() -> Dict[str, Any]:
    with report_lock:
        if not REPORT_STATUS.get("updated_at"):
            REPORT_STATUS["updated_at"] = now_text()
        if not REPORT_STATUS.get("report_text"):
            REPORT_STATUS["report_text"] = load_report_text()
        if not REPORT_STATUS.get("report_mode"):
            REPORT_STATUS["report_mode"] = "draft"
        return dict(REPORT_STATUS)


def start_report_generation() -> Tuple[bool, Dict[str, Any]]:
    with report_lock:
        if REPORT_STATUS.get("running"):
            return False, dict(REPORT_STATUS)
        REPORT_STATUS.update(
            {
                "running": True,
                "ok": True,
                "message": "\u6b63\u5728\u8c03\u7528 AI \u751f\u6210\u62a5\u544a\uff0c\u8bf7\u7a0d\u5019...",
                "updated_at": now_text(),
                "report_text": load_report_text(),
                "report_mode": str(REPORT_STATUS.get("report_mode") or "draft"),
            }
        )

    def worker() -> None:
        try:
            package = build_report_package()
            set_report_status(
                running=False,
                ok=True,
                message=str(package.get("message") or "\u62a5\u544a\u5df2\u751f\u6210\uff0c\u53f3\u4fa7\u5185\u5bb9\u5df2\u5237\u65b0\u3002"),
                report_text=str(package.get("report_text") or default_report_text()),
                report_mode=str(package.get("report_mode") or "draft"),
            )
        except Exception as exc:
            app.logger.exception("report generation failed")
            set_report_status(
                running=False,
                ok=False,
                message=f"\u62a5\u544a\u751f\u6210\u5931\u8d25\uff1a{exc}",
                report_text=load_report_text(),
                report_mode=str(REPORT_STATUS.get("report_mode") or "draft"),
            )

    threading.Thread(target=worker, name="report-generator", daemon=True).start()
    return True, get_report_status()


def clear_dashboard_storage() -> Dict[str, Any]:
    if get_report_status().get("running"):
        raise RuntimeError("\u62a5\u544a\u6b63\u5728\u751f\u6210\u4e2d\uff0c\u8bf7\u7a0d\u540e\u518d\u6e05\u7a7a\u3002")

    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM violations").fetchone()
        deleted_events = int(row["cnt"] or 0)
        conn.execute("DELETE FROM violations")
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'violations'")
        except Exception:
            pass

    deleted_images = 0
    if IMAGE_DIR.exists():
        for child in sorted(IMAGE_DIR.iterdir()):
            if child.is_file():
                child.unlink()
                deleted_images += 1
            elif child.is_dir():
                for nested in child.rglob("*"):
                    if nested.is_file():
                        deleted_images += 1
                shutil.rmtree(child, ignore_errors=True)

    report_cleared = False
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()
        report_cleared = True

    report_text = default_report_text()
    set_report_status(
        running=False,
        ok=True,
        message="\u5df2\u6e05\u7a7a\u5f53\u524d\u8fdd\u89c4\u8bb0\u5f55\u3001\u622a\u56fe\u548c\u62a5\u544a\u3002",
        report_text=report_text,
        report_mode="draft",
    )
    live_status = MONITOR.reset_runtime_state()
    return {
        "deleted_events": deleted_events,
        "deleted_images": deleted_images,
        "report_cleared": report_cleared,
        "report_text": report_text,
        "report_mode": "draft",
        "live_status": live_status,
    }


def parse_upload_payload() -> Tuple[Dict[str, Any], Optional[bytes]]:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        image_bytes = None
        image_base64 = payload.get("image_base64", "")
        if image_base64:
            try:
                image_bytes = base64.b64decode(image_base64)
            except (TypeError, ValueError):
                image_bytes = None
        return payload, image_bytes

    payload = dict(request.form.items())
    image_file = request.files.get("image")
    image_bytes = image_file.read() if image_file is not None else None
    return payload, image_bytes


def build_video_transform_style() -> str:
    transforms: List[str] = []
    if LIVE_VIEW_HFLIP:
        transforms.append("scaleX(-1)")
    if LIVE_VIEW_VFLIP:
        transforms.append("scaleY(-1)")
    if not transforms:
        return ""
    return "transform: " + " ".join(transforms) + "; transform-origin: center center;"


def apply_view_flips(frame: Any) -> Any:
    if cv2 is None:
        return frame
    if LIVE_VIEW_HFLIP and LIVE_VIEW_VFLIP:
        return cv2.flip(frame, -1)
    if LIVE_VIEW_HFLIP:
        return cv2.flip(frame, 1)
    if LIVE_VIEW_VFLIP:
        return cv2.flip(frame, 0)
    return frame


def default_live_roi_config(frame_width: int, frame_height: int) -> Dict[str, Any]:
    light_w = max(24, int(round(frame_width * 0.10)))
    light_h = max(40, int(round(frame_height * 0.22)))
    light_x = max(0, int(round(frame_width * 0.72)))
    light_y = max(0, int(round(frame_height * 0.08)))
    crosswalk_top = int(round(frame_height * 0.68))
    return {
        "traffic_light_roi": [light_x, light_y, light_w, light_h],
        "crosswalk_polygon": [
            [int(round(frame_width * 0.08)), crosswalk_top],
            [int(round(frame_width * 0.92)), crosswalk_top],
            [frame_width - 1, frame_height - 1],
            [0, frame_height - 1],
        ],
    }


def normalize_light_roi(light_roi: Any, frame_width: int, frame_height: int) -> List[int]:
    if not isinstance(light_roi, (list, tuple)) or len(light_roi) != 4:
        return default_live_roi_config(frame_width, frame_height)["traffic_light_roi"]
    try:
        x, y, w, h = [float(value) for value in light_roi]
    except (TypeError, ValueError):
        return default_live_roi_config(frame_width, frame_height)["traffic_light_roi"]

    x1 = max(0, min(frame_width - 1, int(round(x))))
    y1 = max(0, min(frame_height - 1, int(round(y))))
    x2 = max(x1 + 1, min(frame_width, int(round(x + w))))
    y2 = max(y1 + 1, min(frame_height, int(round(y + h))))
    return [x1, y1, x2 - x1, y2 - y1]


def normalize_crosswalk_polygon(points: Any, frame_width: int, frame_height: int) -> List[List[int]]:
    normalized: List[List[int]] = []
    if isinstance(points, (list, tuple)):
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                continue
            try:
                x = int(round(float(point[0])))
                y = int(round(float(point[1])))
            except (TypeError, ValueError):
                continue
            x = max(0, min(frame_width - 1, x))
            y = max(0, min(frame_height - 1, y))
            normalized.append([x, y])
    if len(normalized) < 3:
        return default_live_roi_config(frame_width, frame_height)["crosswalk_polygon"]
    return normalized


def load_live_roi_config(frame_width: int, frame_height: int) -> Dict[str, Any]:
    if not Path(LIVE_ROI_JSON).exists():
        return default_live_roi_config(frame_width, frame_height)
    try:
        payload = json.loads(Path(LIVE_ROI_JSON).read_text(encoding="utf-8"))
    except Exception:
        return default_live_roi_config(frame_width, frame_height)
    return {
        "traffic_light_roi": normalize_light_roi(payload.get("traffic_light_roi"), frame_width, frame_height),
        "crosswalk_polygon": normalize_crosswalk_polygon(payload.get("crosswalk_polygon"), frame_width, frame_height),
    }


def transform_point_from_raw_to_view(x: float, y: float, frame_width: int, frame_height: int) -> Tuple[float, float]:
    view_x = float(x)
    view_y = float(y)
    if LIVE_VIEW_HFLIP:
        view_x = (frame_width - 1) - view_x
    if LIVE_VIEW_VFLIP:
        view_y = (frame_height - 1) - view_y
    return view_x, view_y


def transform_bbox_from_raw_to_view(light_roi: List[int], frame_width: int, frame_height: int) -> List[int]:
    x, y, w, h = light_roi
    x1 = float(x)
    y1 = float(y)
    x2 = float(x + w)
    y2 = float(y + h)
    if LIVE_VIEW_HFLIP:
        x1, x2 = frame_width - x2, frame_width - x1
    if LIVE_VIEW_VFLIP:
        y1, y2 = frame_height - y2, frame_height - y1
    return normalize_light_roi([x1, y1, x2 - x1, y2 - y1], frame_width, frame_height)


def transform_bbox_from_view_to_raw(light_roi: List[int], frame_width: int, frame_height: int) -> List[int]:
    x, y, w, h = light_roi
    x1 = float(x)
    y1 = float(y)
    x2 = float(x + w)
    y2 = float(y + h)
    if LIVE_VIEW_HFLIP:
        x1, x2 = frame_width - x2, frame_width - x1
    if LIVE_VIEW_VFLIP:
        y1, y2 = frame_height - y2, frame_height - y1
    return normalize_light_roi([x1, y1, x2 - x1, y2 - y1], frame_width, frame_height)


def roi_config_raw_to_view(config: Dict[str, Any], frame_width: int, frame_height: int) -> Dict[str, Any]:
    polygon = [
        [int(round(view_x)), int(round(view_y))]
        for view_x, view_y in (
            transform_point_from_raw_to_view(point[0], point[1], frame_width, frame_height)
            for point in config["crosswalk_polygon"]
        )
    ]
    return {
        "traffic_light_roi": transform_bbox_from_raw_to_view(config["traffic_light_roi"], frame_width, frame_height),
        "crosswalk_polygon": normalize_crosswalk_polygon(polygon, frame_width, frame_height),
    }


def roi_config_view_to_raw(config: Dict[str, Any], frame_width: int, frame_height: int) -> Dict[str, Any]:
    polygon = [
        [int(round(raw_x)), int(round(raw_y))]
        for raw_x, raw_y in (
            transform_point_from_raw_to_view(point[0], point[1], frame_width, frame_height)
            for point in config["crosswalk_polygon"]
        )
    ]
    return {
        "traffic_light_roi": transform_bbox_from_view_to_raw(config["traffic_light_roi"], frame_width, frame_height),
        "crosswalk_polygon": normalize_crosswalk_polygon(polygon, frame_width, frame_height),
    }


def save_live_roi_config(view_config: Dict[str, Any], frame_width: int, frame_height: int) -> Dict[str, Any]:
    raw_config = roi_config_view_to_raw(view_config, frame_width, frame_height)
    Path(LIVE_ROI_JSON).parent.mkdir(parents=True, exist_ok=True)
    Path(LIVE_ROI_JSON).write_text(json.dumps(raw_config, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_config


def capture_single_stream_jpeg(timeout: float = 5.0) -> bytes:
    cached = MONITOR.get_latest_raw_jpeg()
    if cached:
        return cached

    deadline = time.time() + max(1.0, timeout)
    with urllib.request.urlopen(STREAM_URL, timeout=timeout) as response:
        buffer = b""
        while time.time() < deadline:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk
            start = buffer.find(b"\xff\xd8")
            end = buffer.find(b"\xff\xd9")
            if start != -1 and end != -1 and end > start:
                return buffer[start:end + 2]
    raise RuntimeError("Unable to capture snapshot from live stream")


def build_roi_editor_payload() -> Dict[str, Any]:
    if cv2 is None or np is None:
        raise RuntimeError("cv2/numpy is required for ROI editor")
    raw_jpeg = capture_single_stream_jpeg()
    frame = cv2.imdecode(np.frombuffer(raw_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("Failed to decode snapshot frame")
    frame_height, frame_width = frame.shape[:2]
    editor_frame = apply_view_flips(frame.copy())
    ok, encoded = cv2.imencode(".jpg", editor_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise RuntimeError("Failed to encode snapshot frame")

    raw_config = load_live_roi_config(frame_width, frame_height)
    view_config = roi_config_raw_to_view(raw_config, frame_width, frame_height)
    return {
        "image_width": frame_width,
        "image_height": frame_height,
        "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
        "config": view_config,
        "roi_path": LIVE_ROI_JSON,
        "view_hflip": LIVE_VIEW_HFLIP,
        "view_vflip": LIVE_VIEW_VFLIP,
    }


def normalize_text_token(name: object) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def text_forms(name: object) -> set[str]:
    text = str(name).strip().lower()
    forms = set()
    if not text:
        return forms
    forms.add(normalize_text_token(text))
    for piece in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text):
        token = normalize_text_token(piece)
        if token:
            forms.add(token)
    return forms


def label_matches(name: object, aliases: set[str]) -> bool:
    forms = text_forms(name)
    return any(token in aliases for token in forms)


def vehicle_family(name: str) -> str:
    if label_matches(name, MOTORCYCLE_ALIASES):
        return "two_wheeler"
    if label_matches(name, BUS_ALIASES):
        return "bus"
    if label_matches(name, TRUCK_ALIASES):
        return "truck"
    return "light_vehicle"


def compatible_family(a: str, b: str) -> bool:
    fa = vehicle_family(a)
    fb = vehicle_family(b)
    if fa == fb:
        return True
    return {fa, fb} <= {"light_vehicle", "two_wheeler"}


def traffic_flow_level(vehicle_count: int) -> Tuple[str, str]:
    if vehicle_count >= TRAFFIC_FLOW_JAM_THRESHOLD:
        return "jam", "拥堵"
    if vehicle_count >= TRAFFIC_FLOW_SLOW_THRESHOLD:
        return "slow", "缓行"
    return "smooth", "畅通"


def summarize_traffic_flow(tracks: Dict[int, "Track"], frame_index: int, source: str) -> Dict[str, Any]:
    counts = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0}
    active_tracks = [track for track in tracks.values() if track.missed_frames == 0]
    for track in active_tracks:
        key = track.cls_name if track.cls_name in counts else "other"
        counts[key] += 1
    vehicle_count = len(active_tracks)
    status, status_label = traffic_flow_level(vehicle_count)
    return {
        "source": source,
        "vehicle_count": vehicle_count,
        "status": status,
        "status_label": status_label,
        "counts": counts,
        "updated_at": now_text(),
        "frame_index": frame_index,
        "slow_threshold": TRAFFIC_FLOW_SLOW_THRESHOLD,
        "jam_threshold": TRAFFIC_FLOW_JAM_THRESHOLD,
    }


def update_traffic_flow_status(payload: Dict[str, Any]) -> Dict[str, Any]:
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


def get_traffic_flow_status() -> Dict[str, Any]:
    with traffic_flow_lock:
        return dict(TRAFFIC_FLOW_STATUS)


def model_name_items(model: Any) -> List[Tuple[int, object]]:
    if isinstance(model.names, dict):
        return [(int(k), v) for k, v in model.names.items()]
    return list(enumerate(model.names))


def resolve_vehicle_class_names(model: Any) -> Dict[int, str]:
    resolved: Dict[int, str] = {}
    names = {int(idx): normalize_text_token(name) for idx, name in model_name_items(model)}
    if all(names.get(cls_id) == expected for cls_id, expected in DEFAULT_CLASS_NAMES.items()):
        return dict(DEFAULT_CLASS_NAMES)

    for idx, name in model_name_items(model):
        cls_id = int(idx)
        if label_matches(name, CAR_ALIASES):
            resolved[cls_id] = "car"
        elif label_matches(name, MOTORCYCLE_ALIASES):
            resolved[cls_id] = "motorcycle"
        elif label_matches(name, BUS_ALIASES):
            resolved[cls_id] = "bus"
        elif label_matches(name, TRUCK_ALIASES):
            resolved[cls_id] = "truck"
    return resolved


def resolve_helmet_class_ids(model: Any) -> Tuple[Optional[int], Optional[int]]:
    helmet_cls = None
    no_helmet_cls = None
    for idx, name in model_name_items(model):
        cls_id = int(idx)
        if label_matches(name, NO_HELMET_ALIASES):
            no_helmet_cls = cls_id
        elif label_matches(name, HELMET_ALIASES):
            helmet_cls = cls_id
    return helmet_cls, no_helmet_cls


@dataclass
class Detection:
    bbox: Tuple[int, int, int, int]
    conf: float
    cls_id: int
    cls_name: str

    @property
    def bottom_center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)


@dataclass
class HelmetObservation:
    bbox: Tuple[int, int, int, int]
    status: str
    score: float


@dataclass
class Track:
    track_id: int
    bbox: Tuple[int, int, int, int]
    cls_id: int
    cls_name: str
    conf: float
    bottom_center: Tuple[int, int]
    missed_frames: int = 0
    hits: int = 1
    inside_crosswalk: bool = False
    seen_outside_crosswalk: bool = False
    violation_logged: bool = False
    helmet_status: str = "unknown"
    helmet_conf: float = 0.0
    last_frame_index: int = 0
    velocity: Tuple[float, float] = (0.0, 0.0)


def bbox_iou(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = float(inter_w * inter_h)
    if inter_area <= 0:
        return 0.0
    area_a = float(max(0, ax2 - ax1) * max(0, ay2 - ay1))
    area_b = float(max(0, bx2 - bx1) * max(0, by2 - by1))
    denom = area_a + area_b - inter_area
    return inter_area / denom if denom > 0 else 0.0


class LightStateFilter:
    def __init__(self, stable_frames: int, red_force_score: float = 0.07) -> None:
        self.stable_frames = stable_frames
        self.red_force_score = red_force_score
        self.displayed_state = "unknown"
        self.candidate_state = "unknown"
        self.candidate_count = 0

    def update(self, raw_state: str, red_score: float, green_score: float) -> str:
        if red_score >= self.red_force_score and red_score >= green_score:
            self.displayed_state = "red"
            self.candidate_state = "red"
            self.candidate_count = self.stable_frames
            return self.displayed_state

        if raw_state == "unknown":
            return self.displayed_state

        if raw_state != self.candidate_state:
            self.candidate_state = raw_state
            self.candidate_count = 1
            return self.displayed_state

        self.candidate_count += 1
        if self.candidate_count >= self.stable_frames:
            self.displayed_state = self.candidate_state
        return self.displayed_state


class CentroidTracker:
    def __init__(self, max_distance: float = 90.0, max_missed_frames: int = 8) -> None:
        self.max_distance = max_distance
        self.max_missed_frames = max_missed_frames
        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, detections: List[Detection], frame_index: int) -> Dict[int, Track]:
        detection_points = [det.bottom_center for det in detections]
        unmatched_track_ids = set(self.tracks.keys())
        unmatched_det_ids = set(range(len(detections)))
        pairs: List[Tuple[float, int, int]] = []

        for track_id, track in self.tracks.items():
            frame_gap = max(1, frame_index - track.last_frame_index)
            px = track.bottom_center[0] + track.velocity[0] * frame_gap
            py = track.bottom_center[1] + track.velocity[1] * frame_gap
            for det_id, point in enumerate(detection_points):
                detection = detections[det_id]
                if not compatible_family(track.cls_name, detection.cls_name):
                    continue
                dist = ((px - point[0]) ** 2 + (py - point[1]) ** 2) ** 0.5
                iou = bbox_iou(track.bbox, detection.bbox)
                if dist > self.max_distance and iou < 0.05:
                    continue
                score = dist - iou * self.max_distance * 0.45
                pairs.append((score, track_id, det_id))

        for _, track_id, det_id in sorted(pairs, key=lambda item: item[0]):
            if track_id not in unmatched_track_ids or det_id not in unmatched_det_ids:
                continue
            self._update_track(track_id, detections[det_id], frame_index)
            unmatched_track_ids.remove(track_id)
            unmatched_det_ids.remove(det_id)

        for track_id in list(unmatched_track_ids):
            track = self.tracks[track_id]
            track.missed_frames += 1
            if track.missed_frames > self.max_missed_frames:
                del self.tracks[track_id]

        for det_id in unmatched_det_ids:
            self._create_track(detections[det_id], frame_index)

        return self.tracks

    def _create_track(self, det: Detection, frame_index: int) -> None:
        self.tracks[self.next_track_id] = Track(
            track_id=self.next_track_id,
            bbox=det.bbox,
            cls_id=det.cls_id,
            cls_name=det.cls_name,
            conf=det.conf,
            bottom_center=det.bottom_center,
            last_frame_index=frame_index,
        )
        self.next_track_id += 1

    def _update_track(self, track_id: int, det: Detection, frame_index: int) -> None:
        track = self.tracks[track_id]
        frame_gap = max(1, frame_index - track.last_frame_index)
        track.velocity = (
            (det.bottom_center[0] - track.bottom_center[0]) / float(frame_gap),
            (det.bottom_center[1] - track.bottom_center[1]) / float(frame_gap),
        )
        track.bbox = det.bbox
        track.cls_id = det.cls_id
        track.cls_name = det.cls_name
        track.conf = det.conf
        track.bottom_center = det.bottom_center
        track.missed_frames = 0
        track.hits += 1
        track.last_frame_index = frame_index


def run_vehicle_detector(
    model: Any,
    frame: Any,
    conf: float,
    imgsz: int,
    vehicle_class_names: Dict[int, str],
) -> List[Detection]:
    class_ids = sorted(vehicle_class_names.keys())
    if not class_ids:
        return []
    results = model(
        frame,
        conf=conf,
        imgsz=imgsz,
        classes=class_ids,
        max_det=40,
        verbose=False,
    )
    boxes = results[0].boxes
    detections: List[Detection] = []
    if boxes is None:
        return detections
    for box in boxes:
        cls_id = int(box.cls[0])
        cls_name = vehicle_class_names.get(cls_id)
        if cls_name is None:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        detections.append(
            Detection(
                bbox=(x1, y1, x2, y2),
                conf=float(box.conf[0]),
                cls_id=cls_id,
                cls_name=cls_name,
            )
        )
    return detections


def run_helmet_detector(
    helmet_model: Any,
    frame: Any,
    conf: float,
    imgsz: int,
    helmet_cls: Optional[int],
    no_helmet_cls: Optional[int],
) -> List[HelmetObservation]:
    results = helmet_model(
        frame,
        conf=conf,
        imgsz=imgsz,
        max_det=24,
        verbose=False,
    )
    boxes = results[0].boxes
    observations: List[HelmetObservation] = []
    if boxes is None:
        return observations
    names = results[0].names
    for box in boxes:
        cls_id = int(box.cls[0])
        score = float(box.conf[0])
        status = "unknown"
        if no_helmet_cls is not None and cls_id == no_helmet_cls:
            status = "no_helmet"
        elif helmet_cls is not None and cls_id == helmet_cls:
            status = "helmet"
        else:
            raw_name = names.get(cls_id, cls_id) if isinstance(names, dict) else names[cls_id]
            if label_matches(raw_name, NO_HELMET_ALIASES):
                status = "no_helmet"
            elif label_matches(raw_name, HELMET_ALIASES):
                status = "helmet"
        if status == "unknown":
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        observations.append(HelmetObservation(bbox=(x1, y1, x2, y2), status=status, score=score))
    return observations


def match_helmet_observations(
    tracks: Dict[int, Track],
    observations: List[HelmetObservation],
) -> Dict[int, HelmetObservation]:
    matched: Dict[int, HelmetObservation] = {}
    for track_id, track in tracks.items():
        if track.missed_frames > 0 or track.cls_name != "motorcycle":
            continue
        x1, y1, x2, y2 = track.bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        head_x1 = x1 - int(width * 0.18)
        head_x2 = x2 + int(width * 0.18)
        head_y1 = y1 - int(height * 0.45)
        head_y2 = y1 + int(height * 0.60)

        best_obs = None
        best_score = -1.0
        center_x = (x1 + x2) / 2.0
        center_y = y1 + height * 0.20

        for obs in observations:
            ox1, oy1, ox2, oy2 = obs.bbox
            obs_cx = (ox1 + ox2) / 2.0
            obs_cy = (oy1 + oy2) / 2.0
            if not (head_x1 <= obs_cx <= head_x2 and head_y1 <= obs_cy <= head_y2):
                continue
            penalty = abs(obs_cx - center_x) / float(width) + abs(obs_cy - center_y) / float(height)
            score = obs.score - penalty * 0.18
            if score > best_score:
                best_score = score
                best_obs = obs

        if best_obs is not None:
            matched[track_id] = best_obs
    return matched


def build_clean_mask(hsv: Any, lower: Any, upper: Any) -> Any:
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def compute_light_score(mask: Any, value_channel: Any) -> Tuple[float, float, float]:
    total_pixels = float(mask.shape[0] * mask.shape[1])
    active_pixels = float(np.count_nonzero(mask))
    if active_pixels <= 0:
        return 0.0, 0.0, 0.0
    ratio = active_pixels / total_pixels
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    max_blob_ratio = 0.0
    if contours:
        max_blob_ratio = max(cv2.contourArea(cnt) for cnt in contours) / total_pixels
    brightness = float(cv2.mean(value_channel, mask=mask)[0]) / 255.0
    score = ratio * 0.45 + max_blob_ratio * 0.35 + brightness * 0.20
    return ratio, brightness, score


def detect_light_state(
    frame: Any,
    roi: Tuple[int, int, int, int],
    red_thresh: float,
    green_thresh: float,
) -> Tuple[str, float, float]:
    x, y, w, h = roi
    crop = frame[y:y + h, x:x + w]
    if crop.size == 0:
        return "unknown", 0.0, 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    value_channel = hsv[:, :, 2]
    red_mask = cv2.bitwise_or(
        build_clean_mask(hsv, RED_RANGE_1_LOWER, RED_RANGE_1_UPPER),
        build_clean_mask(hsv, RED_RANGE_2_LOWER, RED_RANGE_2_UPPER),
    )
    green_mask = build_clean_mask(hsv, GREEN_RANGE_LOWER, GREEN_RANGE_UPPER)

    _, red_brightness, red_score = compute_light_score(red_mask, value_channel)
    _, green_brightness, green_score = compute_light_score(green_mask, value_channel)
    red_score += red_brightness * 0.05
    green_score += green_brightness * 0.05

    if red_score >= red_thresh and red_score > green_score * 0.92:
        return "red", red_score, green_score
    if green_score >= green_thresh and green_score > red_score * 1.05:
        return "green", red_score, green_score
    return "unknown", red_score, green_score


def point_in_polygon(point: Tuple[int, int], polygon: Any) -> bool:
    return cv2.pointPolygonTest(polygon, point, False) >= 0


def draw_overlay(
    frame: Any,
    tracks: Dict[int, Track],
    helmet_observations: List[HelmetObservation],
    crosswalk_polygon: Any,
    light_roi: Tuple[int, int, int, int],
    light_state: str,
    red_score: float,
    green_score: float,
    violation_count: int,
    traffic_flow: Optional[Dict[str, Any]] = None,
) -> Any:
    annotated = frame.copy()
    cv2.polylines(annotated, [crosswalk_polygon], True, (255, 255, 0), 2)
    x, y, w, h = light_roi
    cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 255, 0), 2)

    for track in tracks.values():
        if track.missed_frames > 0:
            continue
        x1, y1, x2, y2 = track.bbox
        color = (0, 0, 255) if track.violation_logged else (0, 255, 0)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"ID {track.track_id} {track.cls_name}"
        cv2.putText(annotated, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 2)
        if track.cls_name == "motorcycle" and track.helmet_status != "unknown":
            helmet_text = "Helmet" if track.helmet_status == "helmet" else "NoHelmet"
            helmet_color = (0, 255, 0) if track.helmet_status == "helmet" else (0, 165, 255)
            cv2.putText(
                annotated,
                f"{helmet_text} {track.helmet_conf:.2f}",
                (x1, max(44, y1 - 28)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                helmet_color,
                2,
            )
        cv2.circle(annotated, track.bottom_center, 4, color, -1)

    for obs in helmet_observations:
        x1, y1, x2, y2 = obs.bbox
        color = (0, 255, 0) if obs.status == "helmet" else (0, 165, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

    panel_overlay = annotated.copy()
    panel_x1, panel_y1 = 10, 10
    panel_x2, panel_y2 = min(250, annotated.shape[1] - 10), min(82, annotated.shape[0] - 10)
    cv2.rectangle(panel_overlay, (panel_x1, panel_y1), (panel_x2, panel_y2), (0, 0, 0), -1)
    cv2.addWeighted(panel_overlay, 0.38, annotated, 0.62, 0, annotated)
    state_color = (0, 0, 255) if light_state == "red" else (0, 255, 0) if light_state == "green" else (255, 255, 255)
    cv2.putText(annotated, f"Light: {light_state}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.70, state_color, 2)
    cv2.putText(
        annotated,
        f"R:{red_score:.3f}  G:{green_score:.3f}  V:{violation_count}",
        (20, 63),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        2,
    )
    if traffic_flow:
        cv2.putText(
            annotated,
            f"Flow:{traffic_flow.get('vehicle_count', 0)} {traffic_flow.get('status_label', '')}",
            (20, 78),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (80, 220, 255),
            2,
        )
    return annotated


def iter_mjpeg_frames(url: str, stop_event: threading.Event) -> Iterable[bytes]:
    while not stop_event.is_set():
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                buffer = b""
                while not stop_event.is_set():
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        end = buffer.find(b"\xff\xd9")
                        if start == -1 or end == -1 or end <= start:
                            break
                        jpg = buffer[start:end + 2]
                        buffer = buffer[end + 2:]
                        yield jpg
        except Exception:
            time.sleep(1.0)


class LiveAiMonitor:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.last_error = ""
        self.last_frame_at = ""
        self.frames_processed = 0
        self.events_created = 0
        self.latest_ai_jpeg = b""
        self.latest_raw_jpeg = b""
        self.recent_event_times: Dict[str, float] = {}
        self.enabled = self._compute_enabled()

    def _compute_enabled(self) -> bool:
        return bool(
            LIVE_ENABLE_AI
            and cv2 is not None
            and np is not None
            and YOLO is not None
            and Path(LIVE_BASE_MODEL).exists()
            and Path(LIVE_ROI_JSON).exists()
        )

    def _make_thread(self) -> threading.Thread:
        return threading.Thread(target=self._run, name="rk-live-ai-monitor", daemon=True)

    def start(self) -> None:
        self.enabled = self._compute_enabled()
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event = threading.Event()
        self.thread = self._make_thread()
        self.thread.start()

    def reload(self) -> Dict[str, Any]:
        if self.thread is not None and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=3.0)
        self.stop_event = threading.Event()
        self.thread = None
        self.running = False
        self.enabled = self._compute_enabled()
        self.last_error = ""
        if LIVE_ENABLE_AI:
            self.thread = self._make_thread()
            self.thread.start()
        return self.status()

    def reset_runtime_state(self) -> Dict[str, Any]:
        with self.lock:
            self.events_created = 0
            self.recent_event_times.clear()
        return self.status()

    def status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "enabled": self.enabled,
                "running": self.running,
                "has_frame": bool(self.latest_ai_jpeg or self.latest_raw_jpeg),
                "ai_has_frame": bool(self.latest_ai_jpeg),
                "raw_proxy_has_frame": bool(self.latest_raw_jpeg),
                "frames_processed": self.frames_processed,
                "events_created": self.events_created,
                "last_frame_at": self.last_frame_at,
                "last_error": self.last_error,
                "stream_url": STREAM_URL,
            }

    def get_latest_ai_jpeg(self) -> bytes:
        with self.lock:
            return self.latest_ai_jpeg

    def get_latest_raw_jpeg(self) -> bytes:
        with self.lock:
            return self.latest_raw_jpeg

    def _set_error(self, message: str) -> None:
        with self.lock:
            self.last_error = message

    def _store_frame(self, ai_frame: Any, raw_jpeg: bytes) -> None:
        ok, buf = cv2.imencode(".jpg", ai_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return
        with self.lock:
            self.latest_ai_jpeg = buf.tobytes()
            self.latest_raw_jpeg = raw_jpeg
            self.last_frame_at = now_text()

    def _allow_event(self, signature: str) -> bool:
        now_ts = time.time()
        last_ts = self.recent_event_times.get(signature, 0.0)
        if now_ts - last_ts < LIVE_EVENT_COOLDOWN_SECONDS:
            return False
        self.recent_event_times[signature] = now_ts
        if len(self.recent_event_times) > 256:
            stale_before = now_ts - LIVE_EVENT_COOLDOWN_SECONDS * 3.0
            self.recent_event_times = {
                key: value for key, value in self.recent_event_times.items() if value >= stale_before
            }
        return True

    def _emit_event(
        self,
        reason_code: str,
        reason_label: str,
        confidence: float,
        annotated_frame: Any,
        metadata: Dict[str, Any],
    ) -> None:
        ok, buf = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return
        insert_event(
            source=LIVE_SOURCE_NAME,
            reason_code=reason_code,
            reason_label=reason_label,
            confidence=confidence,
            event_time=now_text(),
            image_bytes=buf.tobytes(),
            metadata=metadata,
        )
        with self.lock:
            self.events_created += 1

    def _run(self) -> None:
        if not self.enabled:
            reason = "\u5b9e\u65f6 AI \u672a\u542f\u7528\uff1a\u8bf7\u786e\u8ba4\u5df2\u5b89\u88c5 cv2 / numpy / ultralytics\uff0c\u4e14\u6a21\u578b\u4e0e ROI \u6587\u4ef6\u8def\u5f84\u5b58\u5728\u3002"
            self._set_error(reason)
            return

        try:
            roi_config = json.loads(Path(LIVE_ROI_JSON).read_text(encoding="utf-8"))
            light_roi = tuple(roi_config["traffic_light_roi"])
            crosswalk_polygon = np.array(roi_config["crosswalk_polygon"], dtype=np.int32)
        except Exception as exc:
            self._set_error(f"ROI \u914d\u7f6e\u52a0\u8f7d\u5931\u8d25\uff1a{exc}")
            return

        try:
            base_model = YOLO(LIVE_BASE_MODEL)
            vehicle_class_names = resolve_vehicle_class_names(base_model)
            if not vehicle_class_names:
                vehicle_class_names = dict(DEFAULT_CLASS_NAMES)
            helmet_model = YOLO(LIVE_HELMET_MODEL) if LIVE_HELMET_MODEL and Path(LIVE_HELMET_MODEL).exists() else None
            if helmet_model is not None:
                helmet_cls, no_helmet_cls = resolve_helmet_class_ids(helmet_model)
            else:
                helmet_cls, no_helmet_cls = None, None
        except Exception as exc:
            self._set_error(f"YOLO \u6a21\u578b\u52a0\u8f7d\u5931\u8d25\uff1a{exc}")
            return

        tracker = CentroidTracker(max_distance=120.0, max_missed_frames=18)
        light_filter = LightStateFilter(LIVE_STABLE_FRAMES)
        frame_index = 0
        violation_count = 0
        latest_tracks: Dict[int, Track] = {}
        latest_helmet_obs: List[HelmetObservation] = []
        latest_red_score = 0.0
        latest_green_score = 0.0
        latest_light_state = "unknown"
        latest_traffic_flow = summarize_traffic_flow({}, 0, LIVE_SOURCE_NAME)
        last_helmet_eval_at = 0.0
        last_motorcycle_seen_at = 0.0

        with self.lock:
            self.running = True
            self.last_error = ""

        try:
            for raw_jpeg in iter_mjpeg_frames(STREAM_URL, self.stop_event):
                raw = np.frombuffer(raw_jpeg, dtype=np.uint8)
                frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                frame_index += 1
                if frame_index % LIVE_FRAME_STRIDE == 0:
                    raw_state, latest_red_score, latest_green_score = detect_light_state(
                        frame,
                        light_roi,
                        LIVE_RED_THRESH,
                        LIVE_GREEN_THRESH,
                    )
                    latest_light_state = light_filter.update(raw_state, latest_red_score, latest_green_score)

                    detections = run_vehicle_detector(
                        base_model,
                        frame,
                        LIVE_CONF,
                        LIVE_IMGSZ,
                        vehicle_class_names,
                    )
                    latest_tracks = tracker.update(detections, frame_index)
                    latest_traffic_flow = summarize_traffic_flow(latest_tracks, frame_index, LIVE_SOURCE_NAME)
                    update_traffic_flow_status(latest_traffic_flow)

                    has_motorcycle = any(det.cls_name == "motorcycle" for det in detections)
                    now_ts = time.time()
                    if has_motorcycle:
                        last_motorcycle_seen_at = now_ts

                    if (
                        helmet_model is not None
                        and has_motorcycle
                        and (now_ts - last_helmet_eval_at) >= LIVE_HELMET_INTERVAL_SECONDS
                    ):
                        try:
                            latest_helmet_obs = run_helmet_detector(
                                helmet_model,
                                frame,
                                LIVE_HELMET_CONF,
                                min(LIVE_IMGSZ, 384),
                                helmet_cls,
                                no_helmet_cls,
                            )
                        except Exception:
                            latest_helmet_obs = []
                        last_helmet_eval_at = now_ts
                    elif not has_motorcycle and (now_ts - last_motorcycle_seen_at) > LIVE_HELMET_INTERVAL_SECONDS * 2.0:
                        latest_helmet_obs = []

                    matched = match_helmet_observations(latest_tracks, latest_helmet_obs)
                    for track_id, obs in matched.items():
                        track = latest_tracks.get(track_id)
                        if track is None:
                            continue
                        if obs.score >= track.helmet_conf or track.helmet_status == "unknown":
                            track.helmet_status = obs.status
                            track.helmet_conf = obs.score

                    for track in latest_tracks.values():
                        if track.missed_frames > 0:
                            continue

                        inside_now = point_in_polygon(track.bottom_center, crosswalk_polygon)
                        was_inside = track.inside_crosswalk
                        if not inside_now:
                            track.seen_outside_crosswalk = True

                        if (
                            latest_light_state == "red"
                            and inside_now
                            and not was_inside
                            and track.seen_outside_crosswalk
                            and track.hits >= 2
                            and not track.violation_logged
                        ):
                            signature = f"red:{track.track_id}"
                            if self._allow_event(signature):
                                track.violation_logged = True
                                violation_count += 1
                                annotated = draw_overlay(
                                    frame,
                                    latest_tracks,
                                    latest_helmet_obs,
                                    crosswalk_polygon,
                                    light_roi,
                                    latest_light_state,
                                    latest_red_score,
                                    latest_green_score,
                                    violation_count,
                                    latest_traffic_flow,
                                )
                                self._emit_event(
                                    reason_code="red_light_violation",
                                    reason_label="\u95ef\u7ea2\u706f",
                                    confidence=max(track.conf, latest_red_score),
                                    annotated_frame=annotated,
                                    metadata={
                                        "track_id": track.track_id,
                                        "class_name": track.cls_name,
                                        "bbox": list(track.bbox),
                                        "helmet_status": track.helmet_status,
                                        "helmet_conf": round(track.helmet_conf, 3),
                                        "red_score": round(latest_red_score, 3),
                                        "green_score": round(latest_green_score, 3),
                                        "traffic_flow": latest_traffic_flow,
                                    },
                                )

                        if (
                            track.cls_name == "motorcycle"
                            and track.helmet_status == "no_helmet"
                            and track.helmet_conf >= 0.20
                        ):
                            signature = f"no_helmet:{track.track_id}"
                            if self._allow_event(signature):
                                annotated = draw_overlay(
                                    frame,
                                    latest_tracks,
                                    latest_helmet_obs,
                                    crosswalk_polygon,
                                    light_roi,
                                    latest_light_state,
                                    latest_red_score,
                                    latest_green_score,
                                    violation_count,
                                    latest_traffic_flow,
                                )
                                self._emit_event(
                                    reason_code="no_helmet",
                                    reason_label="\u672a\u6234\u5934\u76d4",
                                    confidence=track.helmet_conf,
                                    annotated_frame=annotated,
                                    metadata={
                                        "track_id": track.track_id,
                                        "class_name": track.cls_name,
                                        "bbox": list(track.bbox),
                                        "helmet_status": track.helmet_status,
                                        "helmet_conf": round(track.helmet_conf, 3),
                                        "traffic_flow": latest_traffic_flow,
                                    },
                                )

                        track.inside_crosswalk = inside_now

                annotated_frame = draw_overlay(
                    frame,
                    latest_tracks,
                    latest_helmet_obs,
                    crosswalk_polygon,
                    light_roi,
                    latest_light_state,
                    latest_red_score,
                    latest_green_score,
                    violation_count,
                    latest_traffic_flow,
                )
                self._store_frame(annotated_frame, raw_jpeg)
                with self.lock:
                    self.frames_processed += 1
                    self.last_frame_at = now_text()
        except Exception as exc:
            self._set_error(f"\u5b9e\u65f6 AI \u7ebf\u7a0b\u5f02\u5e38\uff1a{exc}")
        finally:
            with self.lock:
                self.running = False


MONITOR = LiveAiMonitor()


DASHBOARD_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>\u667a\u80fd\u4ea4\u901a\u53cc\u7aef\u6267\u6cd5\u4e2d\u5fc3</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;background:
radial-gradient(circle at top left,rgba(31,111,255,.18),transparent 28%),
radial-gradient(circle at top right,rgba(12,201,169,.14),transparent 24%),
linear-gradient(180deg,#eef5ff 0%,#f7fbff 40%,#fffdf8 100%);color:#16324f}
.top{position:relative;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:20px 24px;background:linear-gradient(135deg,#0f4ec9 0%,#167dff 52%,#0fc9a7 100%);color:#fff;box-shadow:0 18px 40px rgba(25,90,214,.28);overflow:hidden}
.top::before{content:"";position:absolute;inset:auto -120px -120px auto;width:320px;height:320px;background:radial-gradient(circle,rgba(255,255,255,.22),transparent 62%);pointer-events:none}
.top::after{content:"";position:absolute;left:-80px;top:-120px;width:240px;height:240px;background:radial-gradient(circle,rgba(255,255,255,.16),transparent 68%);pointer-events:none}
.top h1{margin:0;font-size:24px;letter-spacing:.5px}
.sub{margin-top:6px;font-size:13px;color:#d9f6ff}
.actions{display:flex;gap:10px;flex-wrap:wrap;position:relative;z-index:1}
.actions a,.actions button{position:relative;border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:10px 16px;background:rgba(255,255,255,.14);backdrop-filter:blur(10px);color:#fff;text-decoration:none;font-weight:700;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease,background .18s ease}
.actions a:hover,.actions button:hover{transform:translateY(-1px);background:rgba(255,255,255,.22);box-shadow:0 10px 20px rgba(6,28,73,.18)}
.actions button.danger{background:rgba(255,112,97,.24)}
.actions button:disabled,.tool-buttons button:disabled{opacity:.58;cursor:not-allowed}
.btn-loader{display:inline-flex;align-items:center;gap:8px}
.btn-loader::before{content:"";width:12px;height:12px;border-radius:50%;border:2px solid rgba(255,255,255,.32);border-top-color:#fff;animation:spinLoader .8s linear infinite}
.wrap{width:min(1680px,calc(100% - 24px));margin:18px auto 24px auto}
.stats{display:grid;grid-template-columns:repeat(8,1fr);gap:12px;margin-bottom:14px}
.card{background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(247,251,255,.94));border:1px solid #d9e7ff;border-radius:18px;box-shadow:0 12px 30px rgba(58,104,182,.12)}
.stat{padding:16px 18px}
.stat label{display:block;font-size:13px;color:#6882a8}
.stat b{display:block;font-size:30px;margin-top:8px;color:#1159d7}
.stat.warn b{color:#ea5a44}
.stat.ok b{color:#17824f}
.stat.flow b{font-size:24px;color:#0f8f8d}
.stat.flow.jam b{color:#d64141}
.stat.flow.slow b{color:#d88612}
.main{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(340px,420px);gap:16px;align-items:start}
.section{padding:18px}
.section h2{margin:0 0 12px;font-size:18px;color:#0f4ec9}
.video-shell{background:#0a1322;border-radius:16px;overflow:hidden;display:flex;align-items:center;justify-content:center;aspect-ratio:4/3;width:100%;max-height:72vh}
.video-shell img{display:block;width:100%;height:100%;object-fit:contain;background:#0a1322}
.video-tools{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;background:#0f1c2f;color:#d6e5ff}
.live-diagnostics{width:100%;font-size:13px;color:#8da7c5;line-height:1.6}
.pill{display:inline-flex;align-items:center;padding:6px 12px;border-radius:999px;background:#e6f4ea;color:#16763a;font-size:13px;font-weight:700}
.pill.waiting{background:#fff2d7;color:#ab6800}
.pill.offline{background:#ffe8e8;color:#b64040}
.tool-buttons{display:flex;gap:8px;flex-wrap:wrap}
.tool-buttons button{border:0;border-radius:10px;background:#1e6fff;color:#fff;padding:8px 12px;font-weight:700;cursor:pointer}
.review-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.event-card{display:flex;flex-direction:column;border:1px solid #dce8ff;border-radius:16px;overflow:hidden;background:#fff}
.event-card img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover;background:#e8eef9}
.event-body{padding:12px 14px}
.event-title{font-size:16px;font-weight:700;color:#18334f;margin-bottom:6px}
.event-meta{font-size:13px;color:#607996;line-height:1.7}
.status-tag{display:inline-block;margin-top:8px;padding:5px 10px;border-radius:999px;background:#eef4ff;color:#1652bf;font-weight:700;font-size:12px}
.event-note{margin-top:8px;width:100%;min-height:74px;padding:10px 12px;border-radius:10px;border:1px solid #d3dff4;background:#f8fbff;resize:vertical}
.event-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.event-actions button{border:0;border-radius:10px;padding:9px 12px;font-weight:700;cursor:pointer}
.approve{background:#1f9d55;color:#fff}
.reject{background:#e45151;color:#fff}
.duplicate{background:#ffb020;color:#1d2635}
.report-panel{position:relative;overflow:hidden}
.report-panel::before{content:"";position:absolute;right:-40px;top:-40px;width:180px;height:180px;background:radial-gradient(circle,rgba(23,125,255,.15),transparent 65%);pointer-events:none}
.report-panel::after{content:"";position:absolute;left:-50px;bottom:-70px;width:180px;height:180px;background:radial-gradient(circle,rgba(15,201,167,.14),transparent 65%);pointer-events:none}
.report-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px;position:relative;z-index:1}
.report-title-wrap{display:grid;gap:6px}
.report-kicker{font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#0f74d6}
.report-mode-badge{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:linear-gradient(135deg,#edf6ff,#f5fffc);border:1px solid #d7e8ff;color:#0f4ec9;font-size:12px;font-weight:800;box-shadow:0 8px 18px rgba(23,92,194,.08)}
.report-mode-badge::before{content:"";width:8px;height:8px;border-radius:50%;background:#1e6fff;box-shadow:0 0 0 5px rgba(30,111,255,.12)}
.report-mode-badge.ai::before{background:#17b978;box-shadow:0 0 0 5px rgba(23,185,120,.12)}
.report-mode-badge.legacy::before{background:#ff9d00;box-shadow:0 0 0 5px rgba(255,157,0,.12)}
.report-mode-badge.generating::before{background:#7a5cff;box-shadow:0 0 0 5px rgba(122,92,255,.12);animation:pulseBadge 1.2s ease infinite}
.report-box{position:relative;white-space:pre-wrap;line-height:1.8;min-height:220px;max-height:380px;overflow:auto;background:linear-gradient(180deg,#fbfdff,#f3f8ff);border:1px solid #dce8ff;border-radius:16px;padding:16px 16px 18px 16px;box-shadow:inset 0 1px 0 rgba(255,255,255,.7)}
.report-box.generating{color:#527196}
.report-box.generating::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 0%,rgba(255,255,255,.68) 42%,transparent 72%);transform:translateX(-110%);animation:reportShimmer 1.35s ease-in-out infinite}
.report-box.ai{border-color:#caece4;background:linear-gradient(180deg,#fbfffd,#f1fffb)}
.report-box.legacy{border-color:#ffe4bf;background:linear-gradient(180deg,#fffdf8,#fff7ea)}
.report-hint{margin-top:10px}
.sources{display:grid;gap:8px}
.source-row{display:flex;justify-content:space-between;padding:10px 12px;border-radius:12px;background:#f6f9ff;border:1px solid #dce8ff}
.muted{color:#7087a4;font-size:13px;line-height:1.8}
.helper{display:grid;gap:10px}
.helper code{background:#edf4ff;border-radius:8px;padding:2px 6px}
.toast-wrap{position:fixed;right:18px;bottom:18px;display:grid;gap:10px;z-index:1200;pointer-events:none}
.toast{min-width:220px;max-width:min(420px,calc(100vw - 36px));padding:12px 14px;border-radius:14px;color:#fff;box-shadow:0 16px 36px rgba(12,30,65,.28);opacity:0;transform:translateY(10px);transition:opacity .2s ease,transform .2s ease}
.toast.show{opacity:1;transform:translateY(0)}
.toast.info{background:linear-gradient(135deg,#1c69f3,#23a2ff)}
.toast.success{background:linear-gradient(135deg,#17985a,#39b971)}
.toast.error{background:linear-gradient(135deg,#d24a4a,#ef6a5f)}
@keyframes reportShimmer{0%{transform:translateX(-110%)}100%{transform:translateX(110%)}}
@keyframes pulseBadge{0%{transform:scale(1);opacity:.9}50%{transform:scale(1.12);opacity:1}100%{transform:scale(1);opacity:.9}}
@keyframes spinLoader{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.roi-modal{position:fixed;inset:0;background:rgba(7,16,32,.68);display:none;align-items:center;justify-content:center;padding:18px;z-index:1000}
.roi-modal.open{display:flex}
.roi-card{width:min(1180px,calc(100vw - 24px));max-height:calc(100vh - 24px);background:#fff;border:1px solid #d9e7ff;border-radius:20px;box-shadow:0 20px 50px rgba(14,36,84,.35);display:flex;flex-direction:column;overflow:hidden}
.roi-head,.roi-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 18px;background:#f7faff}
.roi-head{border-bottom:1px solid #dce8ff}.roi-foot{border-top:1px solid #dce8ff}
.roi-title{font-size:18px;font-weight:700;color:#0f4ec9}.roi-close{border:0;border-radius:999px;background:#e7efff;color:#124ebf;padding:8px 14px;font-weight:700;cursor:pointer}
.roi-body{padding:16px 18px;display:grid;gap:14px;overflow:auto}
.roi-toolbar{display:flex;gap:8px;flex-wrap:wrap}.roi-toolbar button{border:0;border-radius:10px;background:#1e6fff;color:#fff;padding:8px 12px;font-weight:700;cursor:pointer}
.roi-toolbar button.alt{background:#eef4ff;color:#154fbf}.roi-toolbar button.warn{background:#ffe3e3;color:#b73d3d}
.roi-toolbar button.active{box-shadow:0 0 0 3px rgba(30,111,255,.18)}
.roi-canvas-shell{background:#08101b;border-radius:16px;padding:12px;overflow:auto;max-height:68vh}
#roiCanvas{display:block;max-width:100%;height:auto;margin:0 auto;background:#0a1322;border-radius:12px;cursor:crosshair}
.roi-status{display:grid;gap:6px;font-size:13px;color:#5c7695}
.roi-status strong{color:#173b64}
.roi-foot button{border:0;border-radius:10px;padding:10px 14px;font-weight:700;cursor:pointer}
.roi-save{background:#1f9d55;color:#fff}.roi-cancel{background:#eef4ff;color:#124ebf}
@media(max-width:1360px){.main{grid-template-columns:minmax(0,1fr)}}
@media(max-width:1120px){.stats{grid-template-columns:repeat(4,1fr)}.review-grid{grid-template-columns:1fr}.video-shell{max-height:56vh}}
@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="top">
  <div>
    <h1>\u667a\u80fd\u4ea4\u901a\u53cc\u7aef\u6267\u6cd5\u4e2d\u5fc3</h1>
    <div class="sub">K230 \u5b9e\u65f6\u6d41 + RK3588 \u7f51\u9875\u5ba1\u6838 + \u5ba2\u6237\u7aef\u5f55\u50cf\u6279\u5904\u7406\u7ed3\u679c\u6c47\u805a</div>
  </div>
  <div class="actions">
    <a href="/">\u4eea\u8868\u76d8</a>
    <a href="/chat">AI \u95ee\u7b54</a>
    <button onclick="refreshAll()">\u5237\u65b0</button>
    <button onclick="toggleFeed('ai')">AI \u753b\u9762</button>
    <button onclick="toggleFeed('raw')">\u539f\u59cb\u753b\u9762</button>
    <button onclick="openRoiEditor()">\u6807\u5b9a ROI</button>
    <button id="generateReportBtn" onclick="generateReport()">\u751f\u6210\u62a5\u544a</button>
    <button id="clearDataBtn" class="danger" onclick="clearStoredData()">\u6e05\u7a7a\u8bb0\u5f55</button>
  </div>
</div>

<main class="wrap">
  <section class="stats">
    <div class="card stat"><label>\u603b\u4e8b\u4ef6\u6570</label><b id="totalCount">0</b></div>
    <div class="card stat"><label>\u5f85\u5ba1\u6838</label><b id="pendingCount">0</b></div>
    <div class="card stat ok"><label>\u5df2\u786e\u8ba4</label><b id="approvedCount">0</b></div>
    <div class="card stat warn"><label>\u95ef\u7ea2\u706f</label><b id="redCount">0</b></div>
    <div class="card stat warn"><label>\u672a\u6234\u5934\u76d4</label><b id="helmetCount">0</b></div>
    <div class="card stat"><label>\u91cd\u590d\u4e8b\u4ef6</label><b id="duplicateCount">0</b></div>
    <div id="trafficFlowStatusCard" class="card stat flow"><label>\u8f66\u6d41\u72b6\u6001</label><b id="trafficFlowStatus">\u7b49\u5f85\u6570\u636e</b></div>
    <div class="card stat flow"><label>\u5f53\u524d\u8f66\u8f86\u6570</label><b id="trafficFlowCount">0</b></div>
  </section>

  <section class="main">
    <div>
      <div class="card section">
        <h2>K230 \u5b9e\u65f6\u8f85\u52a9\u753b\u9762</h2>
        <div class="video-shell">
          <img id="liveFeed" src="/video_proxy?t={{ cache_bust }}" alt="\u5b9e\u65f6\u753b\u9762" style="{{ video_transform_style }}">
        </div>
        <div class="video-tools">
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <span id="liveState" class="pill waiting">\u7b49\u5f85\u753b\u9762</span>
            <span class="pill" style="background:#eef5ff;color:#1259d6">\u539f\u59cb\u6d41\uff1a/video_proxy</span>
          </div>
          <div class="tool-buttons">
            <button onclick="toggleFeed('ai')">\u663e\u793a AI \u53e0\u52a0</button>
            <button onclick="toggleFeed('raw')">\u663e\u793a\u539f\u59cb\u753b\u9762</button>
          </div>
          <div id="streamDiag" class="live-diagnostics">\u6b63\u5728\u7b49\u5f85\u5b9e\u65f6\u6d41...</div>
        </div>
      </div>

      <div class="card section">
        <h2>\u4eba\u5de5\u5ba1\u6838\u961f\u5217</h2>
        <div class="muted">\u8fd9\u91cc\u4f1a\u6c47\u603b\u4e24\u8def\u7ed3\u679c\uff1a\u4e00\u662f RK3588 \u672c\u5730\u5728\u7ebf\u5206\u6790\u5f97\u5230\u7684\u4e8b\u4ef6\uff0c\u4e8c\u662f\u684c\u9762\u7aef\u89c6\u9891\u6279\u5904\u7406\u540e\u4e0a\u4f20\u5230\u7f51\u9875\u7684\u4e8b\u4ef6\u3002\u4f60\u53ef\u4ee5\u4eba\u5de5\u786e\u8ba4\u3001\u9a73\u56de\uff0c\u6216\u8005\u6807\u8bb0\u4e3a\u91cd\u590d\u3002</div>
        <div id="reviewGrid" class="review-grid" style="margin-top:12px"></div>
      </div>
    </div>

    <aside>
      <div class="card section report-panel">
        <div class="report-head">
          <div class="report-title-wrap">
            <div class="report-kicker">AI Report Studio</div>
            <h2>\u62a5\u544a\u8f93\u51fa</h2>
          </div>
          <span id="reportModeBadge" class="report-mode-badge">\u7ed3\u6784\u5316\u5e95\u7a3f</span>
        </div>
        <div id="reportBox" class="report-box">{{ report_text }}</div>
        <div id="reportHint" class="report-hint muted">\u62a5\u544a\u4f1a\u5148\u751f\u6210\u7ed3\u6784\u5316\u5e95\u7a3f\uff0c\u518d\u5c1d\u8bd5\u7531 AI \u6da6\u8272\u4e3a\u6b63\u5f0f\u7b80\u62a5\uff0c\u5931\u8d25\u65f6\u4f1a\u81ea\u52a8\u56de\u9000\u3002</div>
      </div>

      <div class="card section">
        <h2>\u6765\u6e90\u5206\u5e03</h2>
        <div id="sourceList" class="sources"></div>
      </div>

      <div class="card section">
        <h2>\u63a5\u5165\u8bf4\u660e</h2>
        <div class="helper muted">
          <div>1. \u684c\u9762\u7aef GUI \u91cc\u7684\u201c\u7f51\u9875\u63a5\u53e3\u5730\u5740\u201d\u586b\u5199\u4e3a\uff1a<code>http://RK3588_IP:5000</code></div>
          <div>2. \u5ba2\u6237\u7aef\u4f1a\u5411 <code>/api/upload_violation</code> \u4e0a\u4f20\u8fdd\u89c4\u622a\u56fe\u3001\u7f6e\u4fe1\u5ea6\u3001\u539f\u56e0\u548c\u5143\u6570\u636e\u3002</div>
          <div>3. \u5982\u679c RK3588 \u5df2\u7ecf\u88c5\u597d <code>ultralytics</code>\u3001<code>opencv-python</code>\u3001<code>numpy</code>\uff0c\u5e76\u4e14\u6a21\u578b\u548c ROI \u8def\u5f84\u6709\u6548\uff0c\u5c31\u4f1a\u81ea\u52a8\u542f\u7528\u7f51\u9875\u4fa7 AI \u53e0\u52a0\u6d41\u3002</div>
          <div>4. \u5982\u672a\u542f\u7528\u7f51\u9875\u4fa7 AI\uff0c\u4e5f\u4e0d\u5f71\u54cd\u539f\u59cb K230 \u76f4\u64ad\u548c\u684c\u9762\u7aef\u4e0a\u4f20\u5ba1\u6838\u94fe\u8def\u3002</div>
        </div>
      </div>
    </aside>
  </section>
</main>

<div id="toastRoot" class="toast-wrap"></div>

<div id="roiModal" class="roi-modal">
  <div class="roi-card">
    <div class="roi-head">
      <div>
        <div class="roi-title">\u7f51\u9875\u6807\u5b9a ROI</div>
        <div class="muted">\u5148\u6846\u7ea2\u7eff\u706f\uff0c\u518d\u70b9\u6591\u9a6c\u7ebf\u591a\u8fb9\u5f62\u3002\u4fdd\u5b58\u540e\u4f1a\u81ea\u52a8\u5199\u5165 live_roi.json\uff0c\u5e76\u5c1d\u8bd5\u91cd\u8f7d\u7f51\u9875\u4fa7 AI\u3002</div>
      </div>
      <button class="roi-close" onclick="closeRoiEditor()">\u5173\u95ed</button>
    </div>
    <div class="roi-body">
      <div class="roi-toolbar">
        <button id="roiModeLightBtn" onclick="setRoiMode('light')">\u7ea2\u7eff\u706f\u6846</button>
        <button id="roiModeCrosswalkBtn" class="alt" onclick="setRoiMode('crosswalk')">\u6591\u9a6c\u7ebf\u591a\u8fb9\u5f62</button>
        <button class="alt" onclick="refreshRoiSnapshot()">\u91cd\u65b0\u6293\u5e27</button>
        <button class="alt" onclick="undoCrosswalkPoint()">\u64a4\u9500\u70b9\u4f4d</button>
        <button class="warn" onclick="clearLightRoi()">\u6e05\u7a7a\u7ea2\u7eff\u706f\u6846</button>
        <button class="warn" onclick="clearCrosswalkRoi()">\u6e05\u7a7a\u6591\u9a6c\u7ebf</button>
      </div>
      <div id="roiStatus" class="roi-status"></div>
      <div class="roi-canvas-shell">
        <canvas id="roiCanvas"></canvas>
      </div>
    </div>
    <div class="roi-foot">
      <div class="muted">\u6a21\u5f0f\u63d0\u793a\uff1a\u7ea2\u7eff\u706f\u6a21\u5f0f\u7528\u9f20\u6807\u62d6\u51fa\u77e9\u5f62\uff1b\u6591\u9a6c\u7ebf\u6a21\u5f0f\u6309\u987a\u5e8f\u70b9\u51fb\u591a\u4e2a\u70b9\uff0c\u81f3\u5c11 3 \u4e2a\u70b9\u3002</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="roi-cancel" onclick="closeRoiEditor()">\u53d6\u6d88</button>
        <button class="roi-save" onclick="saveRoiConfig()">\u4fdd\u5b58\u5e76\u91cd\u8f7d</button>
      </div>
    </div>
  </div>
</div>

<script>
let currentFeed = 'raw';
let reportBusy = false;
let clearBusy = false;
const roiState = {
  image: null,
  imageWidth: 0,
  imageHeight: 0,
  config: null,
  roiPath: '',
  mode: 'light',
  dragging: false,
  dragStart: null,
  dragCurrent: null,
  loading: false,
};

function normalizeLightRect(start, end){
  const x1 = Math.max(0, Math.min(start.x, end.x));
  const y1 = Math.max(0, Math.min(start.y, end.y));
  const x2 = Math.min(roiState.imageWidth, Math.max(start.x, end.x));
  const y2 = Math.min(roiState.imageHeight, Math.max(start.y, end.y));
  return [Math.round(x1), Math.round(y1), Math.max(1, Math.round(x2 - x1)), Math.max(1, Math.round(y2 - y1))];
}

function getCanvasPoint(event){
  const canvas = document.getElementById('roiCanvas');
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: Math.max(0, Math.min(canvas.width, (event.clientX - rect.left) * scaleX)),
    y: Math.max(0, Math.min(canvas.height, (event.clientY - rect.top) * scaleY)),
  };
}

function updateRoiButtons(){
  document.getElementById('roiModeLightBtn').classList.toggle('active', roiState.mode === 'light');
  document.getElementById('roiModeCrosswalkBtn').classList.toggle('active', roiState.mode === 'crosswalk');
}

function updateRoiStatus(message=''){
  const root = document.getElementById('roiStatus');
  if(!root) return;
  const light = roiState.config?.traffic_light_roi || [];
  const crosswalk = roiState.config?.crosswalk_polygon || [];
  const lightText = light.length === 4 ? `${light[0]}, ${light[1]}, ${light[2]}, ${light[3]}` : '\u672a\u8bbe\u7f6e';
  root.innerHTML = `
    <div><strong>\u5f53\u524d\u6a21\u5f0f\uff1a</strong>${roiState.mode === 'light' ? '\u7ea2\u7eff\u706f\u6846\u9009' : '\u6591\u9a6c\u7ebf\u70b9\u9009'}</div>
    <div><strong>\u7ea2\u7eff\u706f ROI\uff1a</strong>${lightText}</div>
    <div><strong>\u6591\u9a6c\u7ebf\u70b9\u6570\uff1a</strong>${crosswalk.length}</div>
    <div><strong>\u4fdd\u5b58\u8def\u5f84\uff1a</strong>${roiState.roiPath || '-'}</div>
    ${message ? `<div><strong>\u72b6\u6001\uff1a</strong>${message}</div>` : ''}
  `;
}

function drawLightRect(ctx, rect, color){
  if(!rect || rect.length !== 4) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.fillStyle = color === '#ff5252' ? 'rgba(255,82,82,.18)' : 'rgba(30,111,255,.18)';
  ctx.strokeRect(rect[0], rect[1], rect[2], rect[3]);
  ctx.fillRect(rect[0], rect[1], rect[2], rect[3]);
  ctx.restore();
}

function drawCrosswalk(ctx, points){
  if(!points || !points.length) return;
  ctx.save();
  ctx.strokeStyle = '#00d4ff';
  ctx.fillStyle = 'rgba(0,212,255,.16)';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for(let i = 1; i < points.length; i += 1){
    ctx.lineTo(points[i][0], points[i][1]);
  }
  if(points.length >= 3){
    ctx.closePath();
    ctx.fill();
  }
  ctx.stroke();
  points.forEach((point, index) => {
    ctx.beginPath();
    ctx.arc(point[0], point[1], 6, 0, Math.PI * 2);
    ctx.fillStyle = '#0b57d0';
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = '12px sans-serif';
    ctx.fillText(String(index + 1), point[0] + 8, point[1] - 8);
  });
  ctx.restore();
}

function drawRoiCanvas(){
  const canvas = document.getElementById('roiCanvas');
  const ctx = canvas.getContext('2d');
  if(!roiState.image){
    canvas.width = 960;
    canvas.height = 540;
    ctx.fillStyle = '#09111b';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#d6e5ff';
    ctx.font = '18px sans-serif';
    ctx.fillText('\u6b63\u5728\u52a0\u8f7d\u5b9e\u65f6\u753b\u9762...', 24, 36);
    return;
  }

  canvas.width = roiState.imageWidth;
  canvas.height = roiState.imageHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(roiState.image, 0, 0, canvas.width, canvas.height);

  drawLightRect(ctx, roiState.config?.traffic_light_roi, '#ff5252');
  drawCrosswalk(ctx, roiState.config?.crosswalk_polygon || []);

  if(roiState.mode === 'light' && roiState.dragging && roiState.dragStart && roiState.dragCurrent){
    drawLightRect(ctx, normalizeLightRect(roiState.dragStart, roiState.dragCurrent), '#1e6fff');
  }

  updateRoiButtons();
  updateRoiStatus();
}

function setRoiMode(mode){
  roiState.mode = mode;
  drawRoiCanvas();
}

function openRoiEditor(){
  document.getElementById('roiModal').classList.add('open');
  loadRoiEditorState(false);
}

function closeRoiEditor(){
  document.getElementById('roiModal').classList.remove('open');
  roiState.dragging = false;
}

function loadRoiEditorState(keepConfig){
  roiState.loading = true;
  updateRoiStatus('\u6b63\u5728\u6293\u53d6\u5b9e\u65f6\u753b\u9762...');
  fetch('/api/roi/editor_state?t=' + Date.now())
    .then(r => r.json())
    .then(data => {
      if(!data.ok){
        throw new Error(data.message || '\u52a0\u8f7d ROI \u6570\u636e\u5931\u8d25');
      }
      const image = new Image();
      image.onload = () => {
        roiState.image = image;
        roiState.imageWidth = data.image_width;
        roiState.imageHeight = data.image_height;
        roiState.roiPath = data.roi_path || '';
        if(!keepConfig || !roiState.config){
          roiState.config = data.config || {traffic_light_roi: [], crosswalk_polygon: []};
        }
        roiState.dragging = false;
        roiState.dragStart = null;
        roiState.dragCurrent = null;
        roiState.loading = false;
        drawRoiCanvas();
      };
      image.onerror = () => {
        roiState.loading = false;
        updateRoiStatus('\u5b9e\u65f6\u753b\u9762\u52a0\u8f7d\u5931\u8d25');
      };
      image.src = 'data:image/jpeg;base64,' + data.image_base64;
    })
    .catch(err => {
      roiState.loading = false;
      updateRoiStatus('\u6293\u53d6\u753b\u9762\u5931\u8d25\uff1a' + err.message);
      alert('\u6253\u5f00 ROI \u6807\u5b9a\u5931\u8d25\uff1a' + err.message);
    });
}

function refreshRoiSnapshot(){
  loadRoiEditorState(true);
}

function clearLightRoi(){
  if(!roiState.config) return;
  roiState.config.traffic_light_roi = [];
  drawRoiCanvas();
}

function clearCrosswalkRoi(){
  if(!roiState.config) return;
  roiState.config.crosswalk_polygon = [];
  drawRoiCanvas();
}

function undoCrosswalkPoint(){
  if(!roiState.config || !roiState.config.crosswalk_polygon?.length) return;
  roiState.config.crosswalk_polygon.pop();
  drawRoiCanvas();
}

function saveRoiConfig(){
  if(!roiState.config){
    alert('ROI \u6570\u636e\u5c1a\u672a\u51c6\u5907\u597d');
    return;
  }
  if(!roiState.config.traffic_light_roi || roiState.config.traffic_light_roi.length !== 4){
    alert('\u8bf7\u5148\u6846\u51fa\u7ea2\u7eff\u706f\u533a\u57df');
    return;
  }
  if(!roiState.config.crosswalk_polygon || roiState.config.crosswalk_polygon.length < 3){
    alert('\u8bf7\u81f3\u5c11\u70b9\u51fb 3 \u4e2a\u70b9\u5f62\u6210\u6591\u9a6c\u7ebf\u533a\u57df');
    return;
  }

  updateRoiStatus('\u6b63\u5728\u4fdd\u5b58\u5e76\u91cd\u8f7d\u7f51\u9875\u4fa7 AI...');
  fetch('/api/roi/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      image_width: roiState.imageWidth,
      image_height: roiState.imageHeight,
      traffic_light_roi: roiState.config.traffic_light_roi,
      crosswalk_polygon: roiState.config.crosswalk_polygon,
    }),
  })
    .then(r => r.json())
    .then(data => {
      if(!data.ok){
        throw new Error(data.message || 'ROI \u4fdd\u5b58\u5931\u8d25');
      }
      updateRoiStatus(data.message || '\u4fdd\u5b58\u6210\u529f');
      alert(data.message || 'ROI \u4fdd\u5b58\u6210\u529f');
      closeRoiEditor();
      refreshAll();
    })
    .catch(err => {
      updateRoiStatus('\u4fdd\u5b58\u5931\u8d25\uff1a' + err.message);
      alert('\u4fdd\u5b58 ROI \u5931\u8d25\uff1a' + err.message);
    });
}

function bindRoiCanvasEvents(){
  const canvas = document.getElementById('roiCanvas');
  canvas.addEventListener('mousedown', (event) => {
    if(!roiState.image || roiState.mode !== 'light') return;
    roiState.dragging = true;
    roiState.dragStart = getCanvasPoint(event);
    roiState.dragCurrent = roiState.dragStart;
    drawRoiCanvas();
  });

  canvas.addEventListener('mousemove', (event) => {
    if(!roiState.image || !roiState.dragging || roiState.mode !== 'light') return;
    roiState.dragCurrent = getCanvasPoint(event);
    drawRoiCanvas();
  });

  window.addEventListener('mouseup', (event) => {
    if(!roiState.image || !roiState.dragging || roiState.mode !== 'light') return;
    roiState.dragCurrent = getCanvasPoint(event);
    roiState.config.traffic_light_roi = normalizeLightRect(roiState.dragStart, roiState.dragCurrent);
    roiState.dragging = false;
    drawRoiCanvas();
  });

  canvas.addEventListener('click', (event) => {
    if(!roiState.image || roiState.mode !== 'crosswalk') return;
    const point = getCanvasPoint(event);
    if(!roiState.config){
      roiState.config = {traffic_light_roi: [], crosswalk_polygon: []};
    }
    roiState.config.crosswalk_polygon = roiState.config.crosswalk_polygon || [];
    roiState.config.crosswalk_polygon.push([Math.round(point.x), Math.round(point.y)]);
    drawRoiCanvas();
  });

  canvas.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    undoCrosswalkPoint();
  });
}

function confidenceText(value){
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toFixed(2) : '0.00';
}

function showToast(message, kind='info', duration=2600){
  const root = document.getElementById('toastRoot');
  if(!root) return;
  const toast = document.createElement('div');
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  root.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  window.setTimeout(() => {
    toast.classList.remove('show');
    window.setTimeout(() => toast.remove(), 220);
  }, duration);
}

function setReportModeBadge(mode='draft'){
  const badge = document.getElementById('reportModeBadge');
  const box = document.getElementById('reportBox');
  if(!badge || !box) return;

  badge.className = 'report-mode-badge';
  box.classList.remove('ai', 'legacy', 'generating');

  if(mode === 'ai'){
    badge.textContent = 'AI 润色报告';
    badge.classList.add('ai');
    box.classList.add('ai');
    return;
  }
  if(mode === 'legacy'){
    badge.textContent = '旧脚本报告';
    badge.classList.add('legacy');
    box.classList.add('legacy');
    return;
  }
  if(mode === 'generating'){
    badge.textContent = 'AI 生成中';
    badge.classList.add('generating');
    box.classList.add('generating');
    return;
  }
  badge.textContent = '结构化底稿';
}

function setReportBusy(isBusy, hint=''){
  reportBusy = isBusy;
  const btn = document.getElementById('generateReportBtn');
  const reportHint = document.getElementById('reportHint');
  if(btn){
    btn.disabled = isBusy;
    btn.innerHTML = isBusy ? '<span class="btn-loader">AI 生成中</span>' : '\u751f\u6210\u62a5\u544a';
  }
  if(reportHint && hint){
    reportHint.textContent = hint;
  }
  if(isBusy){
    setReportModeBadge('generating');
  }
}

function setClearBusy(isBusy){
  clearBusy = isBusy;
  const btn = document.getElementById('clearDataBtn');
  if(btn){
    btn.disabled = isBusy;
    btn.innerHTML = isBusy ? '<span class="btn-loader">清空中</span>' : '\u6e05\u7a7a\u8bb0\u5f55';
  }
}

function setLiveState(live){
  const tag = document.getElementById('liveState');
  const diag = document.getElementById('streamDiag');
  const aiHasFrame = Boolean(live.ai_has_frame);
  const rawHasFrame = Boolean(live.raw_has_frame || live.raw_proxy_has_frame || live.has_frame);
  const parts = [];
  if(live.frames_processed){
    parts.push(`\u5df2\u5206\u6790 ${live.frames_processed} \u5e27`);
  }
  if(live.events_created){
    parts.push(`\u5df2\u4ea7\u751f ${live.events_created} \u6761\u4e8b\u4ef6`);
  }
  if(live.source_frames_received){
    parts.push(`\u4e32\u6d41\u5df2\u6536 ${live.source_frames_received} \u5e27`);
  }
  if(live.last_frame_at){
    parts.push(`\u6700\u8fd1\u5e27 ${live.last_frame_at}`);
  }
  if(live.reader_online){
    parts.push('\u4e32\u53e3\u89c6\u9891\u670d\u52a1\u5df2\u8fde\u63a5');
  }
  if(live.last_error){
    parts.push(`\u63d0\u793a\uff1a${live.last_error}`);
  }else if(live.source_last_error && !rawHasFrame){
    parts.push(`\u63d0\u793a\uff1a${live.source_last_error}`);
  }
  if(!live.enabled && rawHasFrame){
    tag.textContent = '\u539f\u59cb\u753b\u9762\u5728\u7ebf';
    tag.className = 'pill waiting';
    if(diag){
      diag.textContent = parts.join(' | ') || '\u539f\u59cb K230 \u76f4\u64ad\u5df2\u8fde\u5165\uff0c\u4f46\u7f51\u9875\u4fa7 AI \u8fd8\u6ca1\u542f\u7528\u3002';
    }
    return;
  }
  if(!live.enabled){
    tag.textContent = '\u7f51\u9875\u4fa7 AI \u672a\u542f\u7528';
    tag.className = 'pill waiting';
    if(diag){
      diag.textContent = parts.join(' | ') || '\u7f51\u9875\u4fa7 AI \u672a\u542f\u7528\uff0c\u5f53\u524d\u4ecd\u53ef\u76f4\u63a5\u67e5\u770b K230 \u539f\u59cb\u6d41\u3002';
    }
    return;
  }
  if(live.running && aiHasFrame){
    tag.textContent = 'AI \u5728\u7ebf\u5206\u6790\u4e2d';
    tag.className = 'pill';
    if(diag){
      diag.textContent = parts.join(' | ') || '\u5b9e\u65f6\u68c0\u6d4b\u6b63\u5728\u8fd0\u884c\u3002';
    }
    return;
  }
  if(rawHasFrame){
    tag.textContent = '\u753b\u9762\u5df2\u8fde\u63a5\uff0cAI \u9884\u70ed\u4e2d';
    tag.className = 'pill waiting';
    if(diag){
      diag.textContent = parts.join(' | ') || '\u76f4\u64ad\u5df2\u8fde\u5165\uff0c\u7b49\u5f85 AI \u751f\u6210\u9996\u5e27\u53e0\u52a0\u3002';
    }
    return;
  }
  tag.textContent = '\u5b9e\u65f6\u6d41\u79bb\u7ebf';
  tag.className = 'pill offline';
  if(diag){
    diag.textContent = parts.join(' | ') || '\u8bf7\u68c0\u67e5 K230 \u7535\u6e90\u3001CH340 \u4e32\u53e3\u548c 5001 \u89c6\u9891\u670d\u52a1\u3002';
  }
}

function renderSources(items){
  const root = document.getElementById('sourceList');
  if(!items.length){
    root.innerHTML = '<div class="muted">\u6682\u65e0\u6765\u6e90\u6570\u636e</div>';
    return;
  }
  root.innerHTML = items.map(item => `
    <div class="source-row">
      <span>${item.source}</span>
      <b>${item.count}</b>
    </div>
  `).join('');
}

function updateTrafficFlow(flow){
  flow = flow || {};
  const statusEl = document.getElementById('trafficFlowStatus');
  const countEl = document.getElementById('trafficFlowCount');
  const card = document.getElementById('trafficFlowStatusCard');
  if(statusEl){
    statusEl.textContent = flow.status_label || '\u7b49\u5f85\u6570\u636e';
  }
  if(countEl){
    countEl.textContent = Number(flow.vehicle_count || 0);
  }
  if(card){
    card.classList.remove('smooth', 'slow', 'jam');
    card.classList.add(flow.status || 'smooth');
  }
}

function renderEvents(events){
  const root = document.getElementById('reviewGrid');
  if(!events.length){
    root.innerHTML = '<div class="muted">\u5f53\u524d\u6ca1\u6709\u5f85\u5ba1\u6838\u4e8b\u4ef6\u3002</div>';
    return;
  }
  root.innerHTML = events.map(event => {
    const meta = event.metadata || {};
    const extra = [
      meta.class_name ? `\u76ee\u6807\u7c7b\u578b\uff1a${meta.class_name}` : '',
      meta.helmet_status ? `\u5934\u76d4\u72b6\u6001\uff1a${meta.helmet_status}` : '',
      meta.track_id ? `\u8f68\u8ff9 ID\uff1a${meta.track_id}` : '',
      meta.traffic_flow ? `\u6293\u62cd\u65f6\u8f66\u6d41\uff1a${meta.traffic_flow.vehicle_count || 0}\u8f86 / ${meta.traffic_flow.status_label || ''}` : '',
    ].filter(Boolean).join('<br>');

    return `
      <div class="event-card">
        <img src="${event.image_url || '/video_proxy'}" alt="event">
        <div class="event-body">
          <div class="event-title">${event.reason_label}</div>
          <div class="event-meta">
            \u65f6\u95f4\uff1a${event.created_at}<br>
            \u6765\u6e90\uff1a${event.source}<br>
            \u7f6e\u4fe1\u5ea6\uff1a${confidenceText(event.confidence)}<br>
            ${extra || '\u6682\u65e0\u9644\u52a0\u5143\u6570\u636e'}
          </div>
          <span class="status-tag">${event.status_label}</span>
          <textarea id="note-${event.id}" class="event-note" placeholder="\u586b\u5199\u5907\u6ce8\u3001\u9a73\u56de\u539f\u56e0\u6216\u53bb\u91cd\u8bf4\u660e...">${event.review_note || ''}</textarea>
          <div class="event-actions">
            <button class="approve" onclick="reviewEvent(${event.id}, 'approved')">\u786e\u8ba4\u8fdd\u89c4</button>
            <button class="reject" onclick="reviewEvent(${event.id}, 'rejected')">\u9a73\u56de</button>
            <button class="duplicate" onclick="reviewEvent(${event.id}, 'duplicate')">\u6807\u8bb0\u91cd\u590d</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function toggleFeed(mode){
  currentFeed = mode;
  const img = document.getElementById('liveFeed');
  img.src = (mode === 'ai' ? '/live_overlay_feed' : '/video_proxy') + '?t=' + Date.now();
}

function reviewEvent(id, status){
  const note = document.getElementById(`note-${id}`)?.value || '';
  fetch(`/api/events/${id}/review`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status, note}),
  })
  .then(async r => {
    const data = await r.json();
    if(!r.ok || !data.ok){
      throw new Error(data.message || '\u63d0\u4ea4\u5ba1\u6838\u5931\u8d25');
    }
    return data;
  })
  .then(() => {
    showToast('\u5ba1\u6838\u7ed3\u679c\u5df2\u4fdd\u5b58', 'success');
    refreshAll();
  })
  .catch(err => showToast('\u63d0\u4ea4\u5ba1\u6838\u5931\u8d25\uff1a' + err.message, 'error', 4200));
}

function pollReportStatus(maxAttempts = 60){
  let attempts = 0;
  const timer = window.setInterval(() => {
    attempts += 1;
    fetch('/api/report/status')
      .then(r => r.json())
      .then(status => {
        if(status.report_text){
          document.getElementById('reportBox').textContent = status.report_text;
        }
        if(status.message){
          const reportHint = document.getElementById('reportHint');
          if(reportHint){
            reportHint.textContent = status.message;
          }
        }
        if(status.running){
          setReportModeBadge('generating');
          return;
        }
        window.clearInterval(timer);
        setReportBusy(false, status.message || '\u62a5\u544a\u5df2\u751f\u6210\u3002');
        setReportModeBadge(status.report_mode || 'draft');
        if(status.ok){
          showToast(status.message || '\u62a5\u544a\u5df2\u751f\u6210', 'success');
          refreshOverview();
          refreshEvents();
        }else{
          showToast(status.message || '\u62a5\u544a\u751f\u6210\u5931\u8d25', 'error', 4800);
        }
      })
      .catch(err => {
        if(attempts >= maxAttempts){
          window.clearInterval(timer);
          setReportBusy(false, '\u62a5\u544a\u72b6\u6001\u8f6e\u8be2\u5931\u8d25\uff0c\u8bf7\u67e5\u770b RK3588 \u540e\u7aef\u65e5\u5fd7\u3002');
          showToast('\u62a5\u544a\u72b6\u6001\u83b7\u53d6\u5931\u8d25\uff1a' + err.message, 'error', 4800);
        }
      });
  }, 800);
}

async function generateReport(){
  if(reportBusy){
    return;
  }
  setReportBusy(true, '\u6b63\u5728\u540e\u53f0\u751f\u6210\u62a5\u544a\uff0c\u671f\u95f4\u76f4\u64ad\u4f1a\u7ee7\u7eed\u4fdd\u6301...');
  showToast('\u5df2\u542f\u52a8\u62a5\u544a\u751f\u6210\u4efb\u52a1', 'info', 1800);

  try{
    const response = await fetch('/api/report/generate', {method: 'POST'});
    let data = null;
    try{
      data = await response.json();
    }catch(err){
      throw new Error(`\u63a5\u53e3\u8fd4\u56de\u5f02\u5e38\uff08HTTP ${response.status}\uff09`);
    }
    if(!response.ok || !data.ok){
      throw new Error(data.message || `\u62a5\u544a\u4efb\u52a1\u542f\u52a8\u5931\u8d25\uff08HTTP ${response.status}\uff09`);
    }
    if(data.report_text){
      document.getElementById('reportBox').textContent = data.report_text;
    }
    setReportModeBadge(data.running ? 'generating' : (data.report_mode || 'draft'));
    if(data.started === false){
      showToast(data.message || '\u62a5\u544a\u4efb\u52a1\u5df2\u5728\u8fd0\u884c\u4e2d', 'info', 2200);
    }
    pollReportStatus();
  }catch(err){
    setReportBusy(false, '\u62a5\u544a\u4efb\u52a1\u542f\u52a8\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002');
    showToast('\u751f\u6210\u62a5\u544a\u5931\u8d25\uff1a' + err.message, 'error', 4800);
  }
}

async function clearStoredData(){
  if(clearBusy){
    return;
  }
  const confirmed = window.confirm('\u786e\u5b9a\u8981\u6e05\u7a7a\u5f53\u524d\u8fdd\u89c4\u8bb0\u5f55\u3001\u622a\u56fe\u548c\u62a5\u544a\u5417\uff1f\\n\\nROI \u914d\u7f6e\u3001\u6a21\u578b\u8def\u5f84\u548c\u76f4\u64ad\u8bbe\u7f6e\u4e0d\u4f1a\u88ab\u5220\u9664\u3002');
  if(!confirmed){
    return;
  }

  setClearBusy(true);
  try{
    const response = await fetch('/api/admin/clear_data', {method: 'POST'});
    let data = null;
    try{
      data = await response.json();
    }catch(err){
      throw new Error(`\u63a5\u53e3\u8fd4\u56de\u5f02\u5e38\uff08HTTP ${response.status}\uff09`);
    }
    if(!response.ok || !data.ok){
      throw new Error(data.message || `\u6e05\u7a7a\u5931\u8d25\uff08HTTP ${response.status}\uff09`);
    }
    document.getElementById('reportBox').textContent = data.report_text || '\u6682\u65e0\u62a5\u544a';
    const reportHint = document.getElementById('reportHint');
    if(reportHint){
      reportHint.textContent = data.message || '\u5f53\u524d\u8bb0\u5f55\u5df2\u6e05\u7a7a\u3002';
    }
    showToast(data.message || '\u5df2\u6e05\u7a7a\u8bb0\u5f55', 'success', 3200);
    setReportModeBadge(data.report_mode || 'draft');
    refreshAll();
  }catch(err){
    showToast('\u6e05\u7a7a\u8bb0\u5f55\u5931\u8d25\uff1a' + err.message, 'error', 4800);
  }finally{
    setClearBusy(false);
  }
}

function refreshOverview(){
  fetch('/api/overview')
    .then(r => r.json())
    .then(data => {
      const stats = data.stats || {};
      document.getElementById('totalCount').textContent = stats.total_count || 0;
      document.getElementById('pendingCount').textContent = stats.pending_count || 0;
      document.getElementById('approvedCount').textContent = stats.approved_count || 0;
      document.getElementById('redCount').textContent = stats.red_light_count || 0;
      document.getElementById('helmetCount').textContent = stats.no_helmet_count || 0;
      document.getElementById('duplicateCount').textContent = stats.duplicate_count || 0;
      setLiveState(data.live_status || {});
      updateTrafficFlow(data.traffic_flow || data.live_status?.traffic_flow || {});
      renderSources(stats.sources || []);
    })
    .catch(err => {
      setLiveState({enabled: true, has_frame: false, running: false, last_error: err.message});
    });
}

function refreshEvents(){
  fetch('/api/events?status=pending&limit=12')
    .then(r => r.json())
    .then(data => renderEvents(data.events || []))
    .catch(() => renderEvents([]));
}

function refreshReport(){
  fetch('/api/report/status')
    .then(r => r.json())
    .then(status => {
      document.getElementById('reportBox').textContent = status.report_text || '\u6682\u65e0\u62a5\u544a';
      setReportBusy(Boolean(status.running), status.message || '\u62a5\u544a\u5c31\u7eea');
      if(!status.running){
        setReportModeBadge(status.report_mode || 'draft');
      }
    })
    .catch(err => {
      const reportHint = document.getElementById('reportHint');
      if(reportHint){
        reportHint.textContent = '\u62a5\u544a\u8bfb\u53d6\u5931\u8d25\uff1a' + err.message;
      }
    });
}

function refreshAll(){
  refreshOverview();
  refreshEvents();
  refreshReport();
  const img = document.getElementById('liveFeed');
  img.src = (currentFeed === 'ai' ? '/live_overlay_feed' : '/video_proxy') + '?t=' + Date.now();
}

window.addEventListener('load', () => {
  bindRoiCanvasEvents();
  refreshAll();
  setInterval(refreshOverview, 5000);
  setInterval(refreshEvents, 7000);
  document.getElementById('roiModal').addEventListener('click', (event) => {
    if(event.target.id === 'roiModal'){
      closeRoiEditor();
    }
  });
});
</script>
</body>
</html>
"""


CHAT_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI \u4ea4\u901a\u95ee\u7b54</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;background:#eef5ff;color:#16324f}
.top{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;background:linear-gradient(135deg,#0b57d0,#1488ff);color:#fff}
.top a{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:9px 14px;color:#fff;text-decoration:none;font-weight:700}
.wrap{width:min(980px,calc(100% - 24px));margin:18px auto}
.card{background:#fff;border:1px solid #d9e6ff;border-radius:18px;box-shadow:0 12px 28px rgba(48,93,170,.12);padding:18px}
.msgs{height:520px;overflow:auto;border:1px solid #dce8ff;border-radius:14px;background:#f8fbff;padding:12px}
.msg{margin-bottom:12px;line-height:1.7}
.user{text-align:right;color:#0b57d0}
.row{display:flex;gap:8px;margin-top:12px}
.row input{flex:1;padding:12px;border-radius:12px;border:1px solid #d3e1f7}
.row button{border:0;border-radius:12px;background:#1268ec;color:#fff;padding:0 18px;font-weight:700;cursor:pointer}
</style>
</head>
<body>
<div class="top">
  <h1 style="margin:0;font-size:22px">AI \u4ea4\u901a\u95ee\u7b54\u52a9\u624b</h1>
  <div><a href="/">\u8fd4\u56de\u4eea\u8868\u76d8</a></div>
</div>
<main class="wrap">
  <div class="card">
    <div class="msgs" id="chatMessages"><div class="msg">\u4f60\u597d\uff0c\u8bf7\u8f93\u5165\u4f60\u60f3\u54a8\u8be2\u7684\u4ea4\u901a\u6267\u6cd5\u3001\u5ba1\u6838\u6216\u53d6\u8bc1\u95ee\u9898\u3002</div></div>
    <div class="row">
      <input id="userInput" placeholder="\u8bf7\u8f93\u5165\u95ee\u9898..." onkeypress="if(event.key==='Enter')sendMessage()">
      <button onclick="sendMessage()">\u53d1\u9001</button>
    </div>
  </div>
</main>
<script>
function sendMessage(){
  const input = document.getElementById('userInput');
  const q = input.value.trim();
  if(!q) return;
  const root = document.getElementById('chatMessages');
  root.innerHTML += `<div class="msg user"><b>\u4f60\uff1a</b>${q}</div>`;
  input.value = '';
  const loading = document.createElement('div');
  loading.className = 'msg';
  loading.innerHTML = '<b>AI\uff1a</b>\u601d\u8003\u4e2d...';
  root.appendChild(loading);
  root.scrollTop = root.scrollHeight;
  fetch('/chat_ask', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question: q})
  })
  .then(r => r.json())
  .then(data => {
    loading.remove();
    root.innerHTML += `<div class="msg"><b>AI\uff1a</b>${data.answer}</div>`;
    root.scrollTop = root.scrollHeight;
  })
  .catch(err => {
    loading.remove();
    root.innerHTML += `<div class="msg"><b>AI\uff1a</b>\u8bf7\u6c42\u5931\u8d25\uff1a${err}</div>`;
    root.scrollTop = root.scrollHeight;
  });
}
</script>
</body>
</html>
"""


@app.route("/")
def dashboard() -> str:
    return render_template_string(
        DASHBOARD_HTML,
        report_text=load_report_text(),
        cache_bust=int(time.time()),
        video_transform_style=build_video_transform_style(),
    )


@app.route("/chat")
def chat() -> str:
    return render_template_string(CHAT_HTML)


@app.route("/chat_ask", methods=["POST"])
def chat_ask() -> Response:
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    return jsonify({"answer": ask_deepseek(question)})


@app.route("/images/<path:filename>")
def images(filename: str) -> Response:
    return send_from_directory(IMAGE_DIR, filename)


@app.route("/api/stats")
def api_stats() -> Response:
    return jsonify(compute_stats())


def fetch_stream_source_status() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            if isinstance(payload, dict):
                return payload
    except Exception as exc:
        return {"has_frame": False, "reader_online": False, "last_error": str(exc)}
    return {"has_frame": False, "reader_online": False, "last_error": "invalid stream status payload"}


def build_live_status_payload() -> Dict[str, Any]:
    live_status = MONITOR.status()
    source_status = fetch_stream_source_status()
    raw_has_frame = bool(source_status.get("has_frame"))
    raw_reader_online = bool(source_status.get("reader_online"))
    ai_has_frame = bool(live_status.get("ai_has_frame"))
    proxy_has_frame = bool(live_status.get("raw_proxy_has_frame"))
    source_error = str(source_status.get("last_error") or "")
    source_last_frame_at = str(source_status.get("last_frame_at") or "")

    merged = dict(live_status)
    merged.update(
        {
            "ai_has_frame": ai_has_frame,
            "raw_proxy_has_frame": proxy_has_frame,
            "raw_has_frame": raw_has_frame,
            "reader_online": raw_reader_online,
            "source_frames_received": int(source_status.get("frames_received") or 0),
            "source_last_frame_at": source_last_frame_at,
            "source_last_error": source_error,
            "has_frame": bool(ai_has_frame or proxy_has_frame or raw_has_frame),
            "traffic_flow": get_traffic_flow_status(),
        }
    )

    if not merged.get("last_frame_at") and source_last_frame_at:
        merged["last_frame_at"] = source_last_frame_at
    if not merged.get("last_error") and source_error and not merged["has_frame"]:
        merged["last_error"] = source_error
    return merged


@app.route("/api/overview")
def api_overview() -> Response:
    return jsonify({
        "stats": compute_stats(),
        "live_status": build_live_status_payload(),
        "traffic_flow": get_traffic_flow_status(),
    })


@app.route("/api/roi/editor_state")
def api_roi_editor_state() -> Response:
    try:
        payload = build_roi_editor_payload()
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 500


@app.route("/api/roi/save", methods=["POST"])
def api_roi_save() -> Response:
    payload = request.get_json(silent=True) or {}
    frame_width = int(payload.get("image_width", 0) or 0)
    frame_height = int(payload.get("image_height", 0) or 0)
    if frame_width <= 1 or frame_height <= 1:
        return jsonify({"ok": False, "message": "Invalid image size"}), 400

    view_config = {
        "traffic_light_roi": normalize_light_roi(payload.get("traffic_light_roi"), frame_width, frame_height),
        "crosswalk_polygon": normalize_crosswalk_polygon(payload.get("crosswalk_polygon"), frame_width, frame_height),
    }
    raw_config = save_live_roi_config(view_config, frame_width, frame_height)
    live_status = MONITOR.reload()
    return jsonify({
        "ok": True,
        "message": "ROI saved and live monitor reloaded",
        "config": raw_config,
        "live_status": live_status,
    })


@app.route("/api/events")
def api_events() -> Response:
    status = request.args.get("status", "").strip()
    limit = int(request.args.get("limit", "24"))
    return jsonify({"events": list_events(status=status, limit=limit)})


@app.route("/api/events/<int:event_id>/review", methods=["POST"])
def api_review_event(event_id: int) -> Response:
    payload = request.get_json(silent=True) or {}
    update_review(event_id, payload.get("status", "pending"), payload.get("note", ""))
    return jsonify({"ok": True})


@app.route("/api/traffic_flow")
def api_traffic_flow() -> Response:
    return jsonify({"ok": True, "traffic_flow": get_traffic_flow_status()})


@app.route("/api/upload_traffic_flow", methods=["POST"])
def api_upload_traffic_flow() -> Response:
    payload = request.get_json(silent=True) or {}
    status = update_traffic_flow_status(payload)
    return jsonify({"ok": True, "traffic_flow": status})


@app.route("/api/upload_violation", methods=["POST"])
def api_upload_violation() -> Response:
    payload, image_bytes = parse_upload_payload()
    metadata = payload.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {"raw_metadata": metadata}

    event_id = insert_event(
        source=str(payload.get("source", "desktop_batch")),
        reason_code=str(payload.get("reason_code", "unknown")),
        reason_label=str(payload.get("reason_label", "")),
        confidence=safe_float(payload.get("confidence", 0.0), 0.0),
        event_time=str(payload.get("event_time", now_text())),
        image_bytes=image_bytes,
        metadata={
            "frame_index": payload.get("frame_index"),
            "track_id": payload.get("track_id"),
            "class_name": payload.get("class_name"),
            "helmet_status": payload.get("helmet_status"),
            "helmet_conf": payload.get("helmet_conf"),
            "bbox": payload.get("bbox"),
            "video_path": payload.get("video_path"),
            "violation_id": payload.get("violation_id"),
            "light_state": payload.get("light_state"),
            **(metadata if isinstance(metadata, dict) else {}),
        },
    )
    return jsonify({"ok": True, "event_id": event_id})


@app.route("/api/admin/clear_data", methods=["POST"])
def api_clear_data() -> Response:
    try:
        result = clear_dashboard_storage()
        return jsonify({
            "ok": True,
            "message": "\u5df2\u6e05\u7a7a\u5f53\u524d\u8bb0\u5f55\u3001\u622a\u56fe\u548c\u62a5\u544a\u3002",
            **result,
        })
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 500


@app.route("/api/report")
def api_report() -> Response:
    return jsonify({"report_text": load_report_text()})


@app.route("/api/report/status")
def api_report_status() -> Response:
    return jsonify(get_report_status())


@app.route("/api/report/generate", methods=["POST"])
@app.route("/generate_report", methods=["POST"])
def api_generate_report() -> Response:
    started, status = start_report_generation()
    status_code = 202 if started else 200
    payload = {
        "ok": True,
        "started": started,
        "message": status.get("message") or ("\u6b63\u5728\u751f\u6210\u62a5\u544a..." if started else "\u62a5\u544a\u4efb\u52a1\u5df2\u5728\u8fd0\u884c\u4e2d\u3002"),
        "report_text": status.get("report_text") or load_report_text(),
        "running": bool(status.get("running")),
        "report_mode": status.get("report_mode") or "draft",
    }
    return jsonify(payload), status_code


@app.route("/video_status")
def video_status() -> Response:
    return jsonify(fetch_stream_source_status())


@app.route("/video_proxy")
def video_proxy() -> Response:
    def generate() -> Iterable[bytes]:
        try:
            with urllib.request.urlopen(STREAM_URL, timeout=10) as response:
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    yield chunk
        except Exception as exc:
            print("video proxy error:", exc, flush=True)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/live_overlay_feed")
def live_overlay_feed() -> Response:
    def generate() -> Iterable[bytes]:
        while True:
            frame = MONITOR.get_latest_ai_jpeg()
            if not frame:
                time.sleep(0.12)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.08)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/live_raw_feed")
def live_raw_feed() -> Response:
    def generate() -> Iterable[bytes]:
        while True:
            frame = MONITOR.get_latest_raw_jpeg()
            if not frame:
                time.sleep(0.12)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.08)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/live_status")
def api_live_status() -> Response:
    return jsonify(build_live_status_payload())


def main() -> None:
    init_db()
    if LIVE_ENABLE_AI:
        MONITOR.start()
    ip = get_local_ip()
    print(f"\u4eea\u8868\u76d8\u542f\u52a8\uff1ahttp://0.0.0.0:{PORT}  |  \u5c40\u57df\u7f51\uff1ahttp://{ip}:{PORT}", flush=True)
    ai_status = "\u5df2\u5f00\u542f" if MONITOR.enabled else "\u672a\u542f\u7528"
    print("\u7f51\u9875\u4fa7 AI\uff1a" + ai_status, flush=True)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
