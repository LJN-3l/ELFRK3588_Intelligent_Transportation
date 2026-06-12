import argparse
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple


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

import cv2
import numpy as np

if TYPE_CHECKING:
    from ultralytics import YOLO


DEFAULT_VEHICLE_CLASS_IDS = {2, 3, 5, 7}
DEFAULT_CLASS_NAMES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

TRAFFIC_FLOW_SLOW_THRESHOLD = 5
TRAFFIC_FLOW_JAM_THRESHOLD = 10
TRAFFIC_FLOW_UPLOAD_INTERVAL_SECONDS = 3.0

PREVIEW_MAX_WIDTH = 854
PREVIEW_MAX_HEIGHT = 480
PREVIEW_MAX_FPS = 12.0
TRACK_RECOVERY_SECONDS = 1.5
HELMET_EVAL_INTERVAL_SECONDS = 0.30
HELMET_MODEL_IMGSZ = 384
BASE_MODEL_MAX_DETECTIONS = 40
HELMET_MODEL_MAX_DETECTIONS = 24
RED_FORCE_LOCK_SCORE = 0.07

RED_RANGE_1_LOWER = np.array([0, 25, 35], dtype=np.uint8)
RED_RANGE_1_UPPER = np.array([20, 255, 255], dtype=np.uint8)
RED_RANGE_2_LOWER = np.array([140, 25, 35], dtype=np.uint8)
RED_RANGE_2_UPPER = np.array([180, 255, 255], dtype=np.uint8)
GREEN_RANGE_LOWER = np.array([35, 45, 45], dtype=np.uint8)
GREEN_RANGE_UPPER = np.array([100, 255, 255], dtype=np.uint8)

CAR_ALIASES = {
    "car",
    "vehicle",
    "auto",
    "sedan",
    "van",
    "机动车",
    "汽车",
    "小汽车",
    "轿车",
}
MOTORCYCLE_ALIASES = {
    "motorcycle",
    "motorbike",
    "motor",
    "moto",
    "bike",
    "scooter",
    "moped",
    "riderbike",
    "摩托车",
    "机车",
    "电动车",
    "电瓶车",
    "摩托",
}
BUS_ALIASES = {
    "bus",
    "coach",
    "minibus",
    "公交车",
    "客车",
    "巴士",
}
TRUCK_ALIASES = {
    "truck",
    "lorry",
    "pickup",
    "货车",
    "卡车",
    "工程车",
}
HELMET_ALIASES = {
    "helmet",
    "withhelmet",
    "wearhelmet",
    "riderhelmet",
    "safetyhelmet",
    "头盔",
    "戴头盔",
    "安全帽",
}
NO_HELMET_ALIASES = {
    "nohelmet",
    "withouthelmet",
    "unhelmeted",
    "noheadgear",
    "withoutsafetyhelmet",
    "未戴头盔",
    "无头盔",
    "不戴头盔",
}

CORE_TEXT = {
    "zh": {
        "loaded_roi": "已加载 ROI 配置: {name}",
        "loaded_model": "已加载基础模型: {name}",
        "loaded_helmet_model": "已加载头盔模型: {name}",
        "helmet_model_disabled": "未配置头盔模型，本次将跳过头盔检测",
        "saving_video": "将保存标注视频到: {path}",
        "detection_started": "检测已开始",
        "stop_requested": "已收到停止请求",
        "video_completed": "视频处理完成",
        "stopped_preview": "已从预览窗口停止",
        "violation_saved": "已保存违章 {count}，目标 ID {track_id}，头盔状态 {helmet_status} -> {path}",
        "run_finished": "本次运行结束，共识别 {count} 次违章",
    },
    "en": {
        "loaded_roi": "Loaded ROI config: {name}",
        "loaded_model": "Loaded base model: {name}",
        "loaded_helmet_model": "Loaded helmet model: {name}",
        "helmet_model_disabled": "No helmet model configured; helmet detection will be skipped",
        "saving_video": "Saving annotated video to: {path}",
        "detection_started": "Detection started",
        "stop_requested": "Stop requested by user",
        "video_completed": "Video processing completed",
        "stopped_preview": "Stopped from preview window",
        "violation_saved": "Saved violation {count} for track {track_id}, helmet status {helmet_status} -> {path}",
        "run_finished": "Run finished with {count} violation(s)",
    },
}


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
    helmet_violation_logged: bool = False
    helmet_status: str = "unknown"
    helmet_conf: float = 0.0
    last_frame_index: int = 0
    velocity: Tuple[float, float] = (0.0, 0.0)


@dataclass
class RuntimeConfig:
    video: str
    model: str = "yolo11n.pt"
    helmet_model: str = ""
    config: str = ""
    output_dir: str = "outputs/violation_run"
    conf: float = 0.25
    helmet_conf: float = 0.10
    imgsz: int = 320
    frame_skip: int = 1
    stable_frames: int = 5
    red_thresh: float = 0.015
    green_thresh: float = 0.02
    save_video: bool = False
    reconfigure: bool = False
    show_window: bool = True
    window_name: str = "Red Light Violation Prototype"
    language: str = "zh"
    preview_max_width: int = PREVIEW_MAX_WIDTH
    preview_max_height: int = PREVIEW_MAX_HEIGHT
    violation_api_url: str = ""
    source_name: str = "desktop_batch"
    log_callback: Optional[Callable[[str], None]] = None
    should_stop: Optional[Callable[[], bool]] = None


class LightStateFilter:
    def __init__(self, stable_frames: int, red_force_lock_score: float = RED_FORCE_LOCK_SCORE) -> None:
        self.stable_frames = stable_frames
        self.red_force_lock_score = red_force_lock_score
        self.displayed_state = "unknown"
        self.candidate_state = "unknown"
        self.candidate_count = 0

    def update(self, raw_state: str, red_score: float, green_score: float) -> str:
        if red_score >= self.red_force_lock_score and red_score >= green_score:
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


def traffic_flow_level(vehicle_count: int) -> Tuple[str, str]:
    if vehicle_count >= TRAFFIC_FLOW_JAM_THRESHOLD:
        return "jam", "拥堵"
    if vehicle_count >= TRAFFIC_FLOW_SLOW_THRESHOLD:
        return "slow", "缓行"
    return "smooth", "畅通"


def summarize_traffic_flow(tracks: Dict[int, "Track"], frame_index: int) -> Dict[str, object]:
    counts = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0, "other": 0}
    active_tracks = [track for track in tracks.values() if track.missed_frames == 0]
    for track in active_tracks:
        key = track.cls_name if track.cls_name in counts else "other"
        counts[key] += 1

    vehicle_count = len(active_tracks)
    level, label = traffic_flow_level(vehicle_count)
    return {
        "vehicle_count": vehicle_count,
        "status": level,
        "status_label": label,
        "counts": counts,
        "frame_index": frame_index,
        "slow_threshold": TRAFFIC_FLOW_SLOW_THRESHOLD,
        "jam_threshold": TRAFFIC_FLOW_JAM_THRESHOLD,
    }


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
        candidate_pairs: List[Tuple[float, float, int, int]] = []

        for track_id, track in self.tracks.items():
            frame_gap = max(1, frame_index - track.last_frame_index)
            tx = track.bottom_center[0] + track.velocity[0] * frame_gap
            ty = track.bottom_center[1] + track.velocity[1] * frame_gap
            for det_id, (dx, dy) in enumerate(detection_points):
                detection = detections[det_id]
                if not is_track_detection_compatible(track.cls_name, detection.cls_name):
                    continue
                dist = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
                iou = bbox_iou(track.bbox, detection.bbox)
                if dist > self.max_distance and iou < 0.05:
                    continue
                score = dist - iou * self.max_distance * 0.45
                candidate_pairs.append((score, dist, track_id, det_id))

        for _, distance, track_id, det_id in sorted(candidate_pairs, key=lambda item: item[0]):
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
        velocity = (
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
        track.velocity = velocity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Desktop prototype for red-light violation detection.")
    parser.add_argument("--video", required=True, help="Path to input video.")
    parser.add_argument("--model", default="yolo11n.pt", help="YOLO model path.")
    parser.add_argument("--helmet-model", default="", help="Optional helmet-detection YOLO model path.")
    parser.add_argument("--config", default="", help="ROI config JSON path.")
    parser.add_argument("--output-dir", default="outputs/violation_run", help="Directory for captures and logs.")
    parser.add_argument("--conf", type=float, default=0.25, help="Detection confidence threshold.")
    parser.add_argument("--helmet-conf", type=float, default=0.10, help="Helmet-detection confidence threshold.")
    parser.add_argument("--imgsz", type=int, default=320, help="Model input size.")
    parser.add_argument("--frame-skip", type=int, default=1, help="Run detection every Nth frame.")
    parser.add_argument("--stable-frames", type=int, default=5, help="Frames required before light state changes.")
    parser.add_argument("--red-thresh", type=float, default=0.015, help="Red pixel ratio threshold.")
    parser.add_argument("--green-thresh", type=float, default=0.03, help="Green pixel ratio threshold.")
    parser.add_argument("--save-video", action="store_true", help="Write an annotated mp4 to the output folder.")
    parser.add_argument("--reconfigure", action="store_true", help="Ignore existing ROI config and redraw.")
    parser.add_argument("--violation-api-url", default="", help="Optional dashboard API base URL, for example http://192.168.137.82:5000.")
    parser.add_argument("--source-name", default="desktop_batch", help="Source name used when pushing violation events.")
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    return RuntimeConfig(
        video=args.video,
        model=args.model,
        helmet_model=args.helmet_model,
        config=args.config,
        output_dir=args.output_dir,
        conf=args.conf,
        helmet_conf=args.helmet_conf,
        imgsz=args.imgsz,
        frame_skip=args.frame_skip,
        stable_frames=args.stable_frames,
        red_thresh=args.red_thresh,
        green_thresh=args.green_thresh,
        save_video=args.save_video,
        reconfigure=args.reconfigure,
        violation_api_url=args.violation_api_url,
        source_name=args.source_name,
    )


def emit_log(config: RuntimeConfig, message: str) -> None:
    print(message)
    if config.log_callback is not None:
        config.log_callback(message)


def tr(config: RuntimeConfig, key: str, **kwargs: object) -> str:
    language = config.language if config.language in CORE_TEXT else "zh"
    template = CORE_TEXT[language][key]
    return template.format(**kwargs)


@lru_cache(maxsize=1)
def get_yolo_class() -> Any:
    from ultralytics import YOLO

    return YOLO


def warmup_ml_runtime() -> Any:
    return get_yolo_class()


def fit_preview_shape(width: int, height: int, max_width: int, max_height: int) -> Tuple[int, int, float]:
    if width <= 0 or height <= 0:
        return max_width, max_height, 1.0

    scale = min(max_width / float(width), max_height / float(height), 1.0)
    preview_width = max(1, int(round(width * scale)))
    preview_height = max(1, int(round(height * scale)))
    return preview_width, preview_height, scale


def resize_for_preview(frame: np.ndarray, max_width: int, max_height: int) -> Tuple[np.ndarray, float]:
    height, width = frame.shape[:2]
    preview_width, preview_height, scale = fit_preview_shape(width, height, max_width, max_height)
    if scale >= 1.0:
        return frame.copy(), 1.0
    resized = cv2.resize(frame, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
    return resized, scale


def render_preview(frame: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    preview_frame, _ = resize_for_preview(frame, max_width, max_height)
    return preview_frame


def normalize_label(name: object) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def label_forms(name: object) -> set[str]:
    text = str(name).strip().lower()
    normalized = normalize_label(text)
    forms = {normalized} if normalized else set()
    pieces = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text)
    for piece in pieces:
        normalized_piece = normalize_label(piece)
        if normalized_piece:
            forms.add(normalized_piece)
    return forms


def label_matches_aliases(name: object, aliases: set[str]) -> bool:
    forms = label_forms(name)
    if not forms:
        return False
    return any(form in aliases for form in forms)


def model_name_items(model: Any) -> List[Tuple[int, object]]:
    return list(model.names.items()) if isinstance(model.names, dict) else list(enumerate(model.names))


def has_standard_coco_vehicle_layout(model: Any) -> bool:
    model_names = {int(idx): normalize_label(name) for idx, name in model_name_items(model)}
    return all(model_names.get(cls_id) == expected for cls_id, expected in DEFAULT_CLASS_NAMES.items())


def resolve_vehicle_class_names(model: Any) -> Dict[int, str]:
    if has_standard_coco_vehicle_layout(model):
        return dict(DEFAULT_CLASS_NAMES)

    resolved: Dict[int, str] = {}

    for idx, name in model_name_items(model):
        cls_id = int(idx)
        if label_matches_aliases(name, CAR_ALIASES):
            resolved[cls_id] = "car"
        elif label_matches_aliases(name, MOTORCYCLE_ALIASES):
            resolved[cls_id] = "motorcycle"
        elif label_matches_aliases(name, BUS_ALIASES):
            resolved[cls_id] = "bus"
        elif label_matches_aliases(name, TRUCK_ALIASES):
            resolved[cls_id] = "truck"

    return resolved


def is_motorcycle_label(name: str) -> bool:
    return label_matches_aliases(name, MOTORCYCLE_ALIASES)

def vehicle_family(name: str) -> str:
    if label_matches_aliases(name, MOTORCYCLE_ALIASES):
        return "two_wheeler"
    if label_matches_aliases(name, BUS_ALIASES):
        return "bus"
    if label_matches_aliases(name, TRUCK_ALIASES):
        return "truck"
    return "light_vehicle"


def is_track_detection_compatible(track_name: str, det_name: str) -> bool:
    track_family = vehicle_family(track_name)
    det_family = vehicle_family(det_name)
    if track_family == det_family:
        return True
    return {track_family, det_family} <= {"light_vehicle", "two_wheeler"}


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
    if inter_area <= 0.0:
        return 0.0

    area_a = float(max(0, ax2 - ax1) * max(0, ay2 - ay1))
    area_b = float(max(0, bx2 - bx1) * max(0, by2 - by1))
    denom = area_a + area_b - inter_area
    if denom <= 0.0:
        return 0.0
    return inter_area / denom


def resolve_helmet_class_ids(model: Any) -> Tuple[Optional[int], Optional[int]]:
    helmet_cls: Optional[int] = None
    no_helmet_cls: Optional[int] = None

    for idx, name in model_name_items(model):
        if label_matches_aliases(name, NO_HELMET_ALIASES):
            no_helmet_cls = int(idx)
        elif label_matches_aliases(name, HELMET_ALIASES):
            helmet_cls = int(idx)

    return helmet_cls, no_helmet_cls


def load_first_frame(video_path: Path) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"Failed to read first frame from {video_path}")
    return frame


def resolve_config_path(video_path: Path, config_arg: str) -> Path:
    return Path(config_arg) if config_arg else video_path.with_name(f"{video_path.stem}_roi.json")


def select_polygon(
    frame: np.ndarray,
    window_name: str,
    max_width: int = PREVIEW_MAX_WIDTH,
    max_height: int = PREVIEW_MAX_HEIGHT,
) -> List[Tuple[int, int]]:
    points: List[Tuple[int, int]] = []
    preview, scale = resize_for_preview(frame, max_width, max_height)

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, preview.shape[1], preview.shape[0])
    cv2.setMouseCallback(window_name, on_mouse)

    while True:
        canvas = preview.copy()
        guide = "Left click:add  Right click:undo  Enter/Space:finish  C:clear  Esc:cancel"
        cv2.putText(canvas, guide, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

        for idx, point in enumerate(points):
            cv2.circle(canvas, point, 5, (0, 255, 255), -1)
            cv2.putText(canvas, str(idx + 1), (point[0] + 6, point[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        if len(points) >= 2:
            cv2.polylines(canvas, [np.array(points, dtype=np.int32)], False, (255, 255, 0), 2)
        if len(points) >= 3:
            cv2.polylines(canvas, [np.array(points, dtype=np.int32)], True, (0, 255, 0), 2)

        cv2.imshow(window_name, canvas)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 32) and len(points) >= 3:
            break
        if key in (ord("c"), ord("C")):
            points.clear()
        if key == 27:
            cv2.destroyWindow(window_name)
            raise RuntimeError("Polygon selection cancelled.")

    cv2.destroyWindow(window_name)
    if scale == 1.0:
        return points

    return [(int(round(x / scale)), int(round(y / scale))) for x, y in points]


def select_rois(
    frame: np.ndarray,
    config_path: Path,
    max_width: int = PREVIEW_MAX_WIDTH,
    max_height: int = PREVIEW_MAX_HEIGHT,
) -> Dict[str, object]:
    preview_frame, scale = resize_for_preview(frame, max_width, max_height)
    light_roi = cv2.selectROI(
        "Select traffic light ROI and press Enter",
        preview_frame,
        showCrosshair=True,
        fromCenter=False,
    )
    cv2.destroyAllWindows()
    if light_roi[2] == 0 or light_roi[3] == 0:
        raise RuntimeError("Traffic light ROI was not selected.")

    if scale != 1.0:
        light_roi = tuple(int(round(v / scale)) for v in light_roi)

    crosswalk_polygon = select_polygon(frame, "Select crosswalk polygon", max_width=max_width, max_height=max_height)
    config = {
        "traffic_light_roi": [int(v) for v in light_roi],
        "crosswalk_polygon": [[int(x), int(y)] for x, y in crosswalk_polygon],
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def ensure_roi_config(
    video_path: Path,
    config_arg: str,
    reconfigure: bool,
    max_width: int = PREVIEW_MAX_WIDTH,
    max_height: int = PREVIEW_MAX_HEIGHT,
) -> Path:
    config_path = resolve_config_path(video_path, config_arg)

    if config_path.exists() and not reconfigure:
        return config_path

    frame = load_first_frame(video_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    select_rois(frame, config_path, max_width=max_width, max_height=max_height)
    return config_path


def load_or_create_config(
    video_path: Path,
    config_arg: str,
    reconfigure: bool,
    max_width: int = PREVIEW_MAX_WIDTH,
    max_height: int = PREVIEW_MAX_HEIGHT,
) -> Dict[str, object]:
    config_path = ensure_roi_config(
        video_path,
        config_arg,
        reconfigure,
        max_width=max_width,
        max_height=max_height,
    )
    return json.loads(config_path.read_text(encoding="utf-8"))


def build_clean_mask(hsv: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def compute_light_score(mask: np.ndarray, value_channel: np.ndarray) -> Tuple[float, float, float]:
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
    frame: np.ndarray,
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

    red_ratio, red_brightness, red_score = compute_light_score(red_mask, value_channel)
    green_ratio, green_brightness, green_score = compute_light_score(green_mask, value_channel)

    red_score += red_brightness * 0.05
    green_score += green_brightness * 0.05

    if red_score >= red_thresh and red_score > green_score * 0.92:
        return "red", red_score, green_score
    if green_score >= green_thresh and green_score > red_score * 1.05:
        return "green", red_score, green_score
    return "unknown", red_score, green_score


def run_detector(
    model: Any,
    frame: np.ndarray,
    conf: float,
    imgsz: int,
    vehicle_class_names: Dict[int, str],
    vehicle_class_ids: List[int],
) -> List[Detection]:
    results = model(
        frame,
        conf=conf,
        imgsz=imgsz,
        classes=vehicle_class_ids,
        max_det=BASE_MODEL_MAX_DETECTIONS,
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
    frame: np.ndarray,
    helmet_cls: Optional[int],
    no_helmet_cls: Optional[int],
    conf: float,
) -> List[HelmetObservation]:
    results = helmet_model(
        frame,
        conf=conf,
        imgsz=HELMET_MODEL_IMGSZ,
        max_det=HELMET_MODEL_MAX_DETECTIONS,
        verbose=False,
    )
    boxes = results[0].boxes
    observations: List[HelmetObservation] = []

    if boxes is None:
        return observations

    for box in boxes:
        cls_id = int(box.cls[0])
        score = float(box.conf[0])
        status = "unknown"

        if no_helmet_cls is not None and cls_id == no_helmet_cls:
            status = "no_helmet"
        elif helmet_cls is not None and cls_id == helmet_cls:
            status = "helmet"
        else:
            if isinstance(results[0].names, dict):
                raw_name = results[0].names.get(cls_id, cls_id)
            else:
                raw_name = results[0].names[cls_id] if cls_id < len(results[0].names) else cls_id
            if label_matches_aliases(raw_name, NO_HELMET_ALIASES):
                status = "no_helmet"
            elif label_matches_aliases(raw_name, HELMET_ALIASES):
                status = "helmet"

        if status == "unknown":
            continue

        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        observations.append(
            HelmetObservation(
                bbox=(x1, y1, x2, y2),
                status=status,
                score=score,
            )
        )

    return observations


class AsyncHelmetDetector:
    def __init__(
        self,
        helmet_model: Any,
        helmet_cls: Optional[int],
        no_helmet_cls: Optional[int],
        conf: float,
    ) -> None:
        self.helmet_model = helmet_model
        self.helmet_cls = helmet_cls
        self.no_helmet_cls = no_helmet_cls
        self.conf = conf
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending_frame: Optional[np.ndarray] = None
        self._pending_frame_index = -1
        self._latest_observations: List[HelmetObservation] = []
        self._latest_frame_index = -1
        self._running = False
        self._worker = threading.Thread(target=self._worker_loop, name="helmet-detector", daemon=True)
        self._worker.start()

    def submit(self, frame_index: int, frame: np.ndarray) -> None:
        with self._lock:
            self._pending_frame = frame.copy()
            self._pending_frame_index = frame_index
        self._wake_event.set()

    def latest(self) -> Tuple[int, List[HelmetObservation]]:
        with self._lock:
            return self._latest_frame_index, list(self._latest_observations)

    def is_busy(self) -> bool:
        with self._lock:
            return self._running or self._pending_frame is not None

    def close(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._worker.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.wait(0.1)
            if self._stop_event.is_set():
                break

            with self._lock:
                frame = self._pending_frame
                frame_index = self._pending_frame_index
                self._pending_frame = None
                self._pending_frame_index = -1
                self._wake_event.clear()
                if frame is not None:
                    self._running = True

            if frame is None:
                continue

            try:
                observations = run_helmet_detector(
                    self.helmet_model,
                    frame,
                    self.helmet_cls,
                    self.no_helmet_cls,
                    self.conf,
                )
            except Exception:
                observations = []

            with self._lock:
                self._latest_frame_index = frame_index
                self._latest_observations = observations
                self._running = False


def point_in_polygon(point: Tuple[int, int], polygon: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon, point, False) >= 0


def save_violation(
    output_dir: Path,
    annotated_frame: np.ndarray,
    track: Track,
    frame_index: int,
    timestamp_ms: float,
    total_violations: int,
    reason_code: str = "red_light_violation",
    reason_label: str = "",
) -> Path:
    captures_dir = output_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in reason_code).strip("_") or "event"
    image_path = captures_dir / f"{safe_reason}_{total_violations:04d}_track_{track.track_id:03d}_frame_{frame_index:06d}.jpg"
    cv2.imwrite(str(image_path), annotated_frame)

    log_path = output_dir / "violations.jsonl"
    record = {
        "violation_id": total_violations,
        "track_id": track.track_id,
        "frame_index": frame_index,
        "timestamp_ms": round(timestamp_ms, 2),
        "class_name": track.cls_name,
        "bbox": list(track.bbox),
        "reason_code": reason_code,
        "reason_label": reason_label,
        "helmet_status": track.helmet_status,
        "helmet_conf": round(track.helmet_conf, 3),
        "image_path": str(image_path),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return image_path


def push_violation_event(
    config: RuntimeConfig,
    image_path: Path,
    track: Track,
    frame_index: int,
    timestamp_ms: float,
    light_state: str,
    red_score: float,
    violation_id: int,
    reason_code: str = "red_light_violation",
    reason_label: str = "",
    confidence: Optional[float] = None,
    extra_metadata: Optional[Dict[str, object]] = None,
) -> Optional[str]:
    api_url = config.violation_api_url.strip()
    if not api_url:
        return None

    upload_url = api_url.rstrip("/") + "/api/upload_violation"
    try:
        image_bytes = image_path.read_bytes()
        if not reason_label:
            if config.language == "zh":
                reason_label = "未戴头盔" if reason_code == "no_helmet" else "闯红灯"
            else:
                reason_label = "No Helmet" if reason_code == "no_helmet" else "Red Light Violation"
        payload = {
            "source": config.source_name or "desktop_batch",
            "reason_code": reason_code,
            "reason_label": reason_label,
            "confidence": round(confidence if confidence is not None else max(track.conf, red_score), 3),
            "event_time": round(timestamp_ms / 1000.0, 3),
            "frame_index": frame_index,
            "light_state": light_state,
            "track_id": track.track_id,
            "class_name": track.cls_name,
            "helmet_status": track.helmet_status,
            "helmet_conf": round(track.helmet_conf, 3),
            "bbox": list(track.bbox),
            "video_path": config.video,
            "violation_id": violation_id,
            "image_name": image_path.name,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "metadata": {
                "red_score": round(red_score, 3),
                "model": config.model,
                "helmet_model": config.helmet_model,
                "output_dir": config.output_dir,
                **(extra_metadata or {}),
            },
        }
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            upload_url,
            data=request_data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
        return body
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        emit_log(config, f"事件上传失败: {exc}")
        return None


def push_traffic_flow_status(
    config: RuntimeConfig,
    flow: Dict[str, object],
    frame_index: int,
    timestamp_ms: float,
) -> Optional[str]:
    api_url = config.violation_api_url.strip()
    if not api_url:
        return None

    upload_url = api_url.rstrip("/") + "/api/upload_traffic_flow"
    payload = {
        "source": config.source_name or "desktop_batch",
        "video_path": config.video,
        "event_time": round(timestamp_ms / 1000.0, 3),
        "frame_index": frame_index,
        **flow,
    }
    try:
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            upload_url,
            data=request_data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        emit_log(config, f"车流量上报失败: {exc}")
        return None


def build_writer(path: Path, fps: float, frame_shape: Tuple[int, int, int]) -> cv2.VideoWriter:
    height, width = frame_shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    return cv2.VideoWriter(str(path), fourcc, fps, (width, height))


def draw_overlay(
    frame: np.ndarray,
    tracks: Dict[int, Track],
    helmet_observations: List[HelmetObservation],
    crosswalk_polygon: np.ndarray,
    light_roi: Tuple[int, int, int, int],
    light_state: str,
    red_ratio: float,
    green_ratio: float,
    violation_count: int,
    traffic_flow: Optional[Dict[str, object]] = None,
) -> np.ndarray:
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
        cv2.putText(annotated, label, (x1, max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        cv2.circle(annotated, track.bottom_center, 4, color, -1)

    for observation in helmet_observations:
        x1, y1, x2, y2 = observation.bbox
        color = (0, 255, 0) if observation.status == "helmet" else (0, 165, 255)
        label = f"{observation.status} {observation.score:.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, label, (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    cv2.rectangle(annotated, (0, 0), (460, 170), (0, 0, 0), -1)
    state_color = (0, 0, 255) if light_state == "red" else (0, 255, 0) if light_state == "green" else (255, 255, 255)
    cv2.putText(annotated, f"Light: {light_state}", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, state_color, 2)
    cv2.putText(annotated, f"Red score: {red_ratio:.3f}", (12, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.putText(annotated, f"Green score: {green_ratio:.3f}", (12, 94), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    cv2.putText(annotated, f"Violations: {violation_count}", (12, 126), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
    if traffic_flow:
        flow_text = f"Flow: {traffic_flow.get('vehicle_count', 0)} {traffic_flow.get('status_label', '')}"
        cv2.putText(annotated, flow_text, (12, 158), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (80, 220, 255), 2)
    return annotated


def run_pipeline(config: RuntimeConfig) -> Dict[str, object]:
    video_path = Path(config.video)
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_config_path = resolve_config_path(video_path, config.config)

    roi_config = load_or_create_config(
        video_path,
        config.config,
        config.reconfigure,
        max_width=config.preview_max_width,
        max_height=config.preview_max_height,
    )
    light_roi = tuple(roi_config["traffic_light_roi"])
    crosswalk_polygon = np.array(roi_config["crosswalk_polygon"], dtype=np.int32)
    emit_log(config, tr(config, "loaded_roi", name=resolved_config_path.name))

    YOLO = get_yolo_class()
    model = YOLO(config.model)
    emit_log(config, tr(config, "loaded_model", name=config.model))
    vehicle_class_names = resolve_vehicle_class_names(model)
    if not vehicle_class_names:
        vehicle_class_names = {
            cls_id: name for cls_id, name in DEFAULT_CLASS_NAMES.items() if cls_id in DEFAULT_VEHICLE_CLASS_IDS
        }
    vehicle_class_ids = sorted(vehicle_class_names.keys())
    emit_log(config, f"Base model vehicle mapping -> {vehicle_class_names}")

    helmet_model: Optional[Any] = None
    helmet_cls: Optional[int] = None
    no_helmet_cls: Optional[int] = None
    if config.helmet_model:
        try:
            helmet_model = YOLO(config.helmet_model)
        except Exception as exc:
            raise RuntimeError(f"Failed to load helmet model: {config.helmet_model}\nDetails: {exc}") from exc
        helmet_cls, no_helmet_cls = resolve_helmet_class_ids(helmet_model)
        emit_log(config, tr(config, "loaded_helmet_model", name=config.helmet_model))
        class_preview = ", ".join(f"{idx}:{name}" for idx, name in model_name_items(helmet_model)[:8])
        if class_preview:
            emit_log(config, f"Helmet model labels -> {class_preview}")
        emit_log(config, f"Helmet class mapping -> helmet={helmet_cls}, no_helmet={no_helmet_cls}")
    else:
        emit_log(config, tr(config, "helmet_model_disabled"))

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    ok, sample_frame = cap.read()
    if not ok:
        raise RuntimeError(f"Failed to read frames from: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    preview_width, preview_height, _ = fit_preview_shape(
        sample_frame.shape[1],
        sample_frame.shape[0],
        config.preview_max_width,
        config.preview_max_height,
    )
    if config.show_window:
        cv2.namedWindow(config.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(config.window_name, preview_width, preview_height)

    writer: Optional[cv2.VideoWriter] = None
    if config.save_video:
        writer = build_writer(output_dir / "annotated_output.mp4", fps, sample_frame.shape)
        emit_log(config, tr(config, "saving_video", path=output_dir / "annotated_output.mp4"))

    processed_frame_step = max(1, config.frame_skip)
    track_recovery_frames = max(10, int(round(TRACK_RECOVERY_SECONDS * fps / float(processed_frame_step))))
    tracker_distance = max(110.0, min(sample_frame.shape[0], sample_frame.shape[1]) * 0.16)
    tracker = CentroidTracker(max_distance=tracker_distance, max_missed_frames=track_recovery_frames)
    light_filter = LightStateFilter(stable_frames=config.stable_frames)
    helmet_eval_gap_frames = max(1, int(round(HELMET_EVAL_INTERVAL_SECONDS * fps)))
    preview_interval_seconds = 1.0 / PREVIEW_MAX_FPS
    last_preview_wall_time = 0.0
    helmet_worker: Optional[AsyncHelmetDetector] = None
    if helmet_model is not None:
        helmet_worker = AsyncHelmetDetector(
            helmet_model=helmet_model,
            helmet_cls=helmet_cls,
            no_helmet_cls=no_helmet_cls,
            conf=config.helmet_conf,
        )

    frame_index = 0
    violation_count = 0
    latest_tracks: Dict[int, Track] = {}
    latest_red_ratio = 0.0
    latest_green_ratio = 0.0
    latest_light_state = "unknown"
    latest_traffic_flow = summarize_traffic_flow({}, 0)
    last_flow_upload_wall_time = 0.0
    last_helmet_submit_frame = -1
    latest_helmet_frame_index = -1
    last_motorcycle_frame = -1
    latest_helmet_observations: List[HelmetObservation] = []

    emit_log(config, tr(config, "detection_started"))

    try:
        while True:
            if config.should_stop is not None and config.should_stop():
                emit_log(config, tr(config, "stop_requested"))
                break

            ok, frame = cap.read()
            if not ok:
                emit_log(config, tr(config, "video_completed"))
                break

            if helmet_worker is not None:
                helmet_frame_index, helmet_observations = helmet_worker.latest()
                if helmet_frame_index >= latest_helmet_frame_index:
                    latest_helmet_frame_index = helmet_frame_index
                    latest_helmet_observations = helmet_observations

            frame_index += 1
            if frame_index % config.frame_skip != 0:
                annotated = frame
                now = time.perf_counter()
                show_preview_now = config.show_window and (now - last_preview_wall_time >= preview_interval_seconds)
                need_overlay = writer is not None or show_preview_now
                if need_overlay:
                    annotated = draw_overlay(
                        frame,
                        latest_tracks,
                        latest_helmet_observations,
                        crosswalk_polygon,
                        light_roi,
                        latest_light_state,
                        latest_red_ratio,
                        latest_green_ratio,
                        violation_count,
                        latest_traffic_flow,
                    )
                if writer is not None:
                    writer.write(annotated)
                if show_preview_now:
                    cv2.imshow(
                        config.window_name,
                        render_preview(annotated, config.preview_max_width, config.preview_max_height),
                    )
                    last_preview_wall_time = now
                    if cv2.waitKey(1) & 0xFF == 27:
                        emit_log(config, tr(config, "stopped_preview"))
                        break
                continue

            raw_light_state, latest_red_ratio, latest_green_ratio = detect_light_state(
                frame,
                light_roi,
                config.red_thresh,
                config.green_thresh,
            )
            latest_light_state = light_filter.update(raw_light_state, latest_red_ratio, latest_green_ratio)

            detections = run_detector(model, frame, config.conf, config.imgsz, vehicle_class_names, vehicle_class_ids)
            latest_tracks = tracker.update(detections, frame_index)
            latest_traffic_flow = summarize_traffic_flow(latest_tracks, frame_index)
            now_flow_wall_time = time.perf_counter()
            if (
                config.violation_api_url.strip()
                and now_flow_wall_time - last_flow_upload_wall_time >= TRAFFIC_FLOW_UPLOAD_INTERVAL_SECONDS
            ):
                push_traffic_flow_status(
                    config=config,
                    flow=latest_traffic_flow,
                    frame_index=frame_index,
                    timestamp_ms=cap.get(cv2.CAP_PROP_POS_MSEC),
                )
                last_flow_upload_wall_time = now_flow_wall_time
            has_motorcycle = any(det.cls_name == "motorcycle" for det in detections)
            if has_motorcycle:
                last_motorcycle_frame = frame_index

            if (
                helmet_worker is not None
                and has_motorcycle
                and not helmet_worker.is_busy()
                and (
                    last_helmet_submit_frame < 0
                    or frame_index - last_helmet_submit_frame >= helmet_eval_gap_frames
                )
            ):
                helmet_worker.submit(frame_index, frame)
                last_helmet_submit_frame = frame_index
            elif not has_motorcycle and frame_index - last_motorcycle_frame > helmet_eval_gap_frames:
                latest_helmet_observations = []

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
                    track.violation_logged = True
                    violation_count += 1

                    annotated = draw_overlay(
                        frame,
                        latest_tracks,
                        latest_helmet_observations,
                        crosswalk_polygon,
                        light_roi,
                        latest_light_state,
                        latest_red_ratio,
                        latest_green_ratio,
                        violation_count,
                        latest_traffic_flow,
                    )
                    timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                    image_path = save_violation(
                        output_dir,
                        annotated,
                        track,
                        frame_index,
                        timestamp_ms,
                        violation_count,
                        reason_code="red_light_violation",
                        reason_label="闯红灯" if config.language == "zh" else "Red Light Violation",
                    )
                    push_violation_event(
                        config=config,
                        image_path=image_path,
                        track=track,
                        frame_index=frame_index,
                        timestamp_ms=timestamp_ms,
                        light_state=latest_light_state,
                        red_score=latest_red_ratio,
                        violation_id=violation_count,
                        reason_code="red_light_violation",
                        reason_label="闯红灯" if config.language == "zh" else "Red Light Violation",
                    )
                    emit_log(
                        config,
                        tr(
                            config,
                            "violation_saved",
                            count=violation_count,
                            track_id=track.track_id,
                            helmet_status=track.helmet_status,
                            path=image_path,
                        ),
                    )

                if (
                    track.cls_name == "motorcycle"
                    and track.helmet_status == "no_helmet"
                    and track.helmet_conf >= 0.20
                    and not track.helmet_violation_logged
                ):
                    track.helmet_violation_logged = True
                    violation_count += 1

                    annotated = draw_overlay(
                        frame,
                        latest_tracks,
                        latest_helmet_observations,
                        crosswalk_polygon,
                        light_roi,
                        latest_light_state,
                        latest_red_ratio,
                        latest_green_ratio,
                        violation_count,
                        latest_traffic_flow,
                    )
                    timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                    image_path = save_violation(
                        output_dir,
                        annotated,
                        track,
                        frame_index,
                        timestamp_ms,
                        violation_count,
                        reason_code="no_helmet",
                        reason_label="未戴头盔" if config.language == "zh" else "No Helmet",
                    )
                    push_violation_event(
                        config=config,
                        image_path=image_path,
                        track=track,
                        frame_index=frame_index,
                        timestamp_ms=timestamp_ms,
                        light_state=latest_light_state,
                        red_score=latest_red_ratio,
                        violation_id=violation_count,
                        reason_code="no_helmet",
                        reason_label="未戴头盔" if config.language == "zh" else "No Helmet",
                        confidence=track.helmet_conf,
                        extra_metadata={
                            "helmet_status": track.helmet_status,
                            "helmet_conf": round(track.helmet_conf, 3),
                            "traffic_flow": latest_traffic_flow,
                        },
                    )
                    emit_log(
                        config,
                        tr(
                            config,
                            "violation_saved",
                            count=violation_count,
                            track_id=track.track_id,
                            helmet_status=track.helmet_status,
                            path=image_path,
                        ),
                    )

                track.inside_crosswalk = inside_now

            now = time.perf_counter()
            show_preview_now = config.show_window and (now - last_preview_wall_time >= preview_interval_seconds)
            need_annotated_frame = writer is not None or show_preview_now

            if need_annotated_frame:
                annotated = draw_overlay(
                    frame,
                    latest_tracks,
                    latest_helmet_observations,
                    crosswalk_polygon,
                    light_roi,
                    latest_light_state,
                    latest_red_ratio,
                    latest_green_ratio,
                    violation_count,
                    latest_traffic_flow,
                )
            else:
                annotated = frame

            if writer is not None:
                writer.write(annotated)

            if show_preview_now:
                cv2.imshow(
                    config.window_name,
                    render_preview(annotated, config.preview_max_width, config.preview_max_height),
                )
                last_preview_wall_time = now
                if cv2.waitKey(1) & 0xFF == 27:
                    emit_log(config, tr(config, "stopped_preview"))
                    break
    finally:
        if helmet_worker is not None:
            helmet_worker.close()
        cap.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    result = {
        "output_dir": str(output_dir),
        "violation_count": violation_count,
        "video_path": str(video_path),
        "config_path": str(resolved_config_path),
    }
    emit_log(config, tr(config, "run_finished", count=violation_count))
    return result


def main() -> None:
    args = parse_args()
    run_pipeline(build_runtime_config(args))


if __name__ == "__main__":
    main()
