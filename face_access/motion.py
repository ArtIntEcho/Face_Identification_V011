from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from threading import Lock
from typing import Protocol

import cv2
import mediapipe as mp
import numpy as np

from face_access.liveness import TurnDirection


@dataclass(frozen=True, slots=True)
class FaceMotion:
    eye_aspect_ratio: float
    turn_direction: TurnDirection | None
    yaw_ratio: float | None = None
    pitch_ratio: float | None = None


class MotionAnalyzer(Protocol):
    def analyze(self, image: bytes) -> FaceMotion | None: ...

    def close(self) -> None: ...


class MediaPipeMotionAnalyzer:
    def __init__(self) -> None:
        self._lock = Lock()
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def analyze(self, image: bytes) -> FaceMotion | None:
        frame = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Image is not a supported JPEG or PNG")
        with self._lock:
            result = self._mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.multi_face_landmarks:
            return None
        landmarks = result.multi_face_landmarks[0].landmark
        left_eye = _eye_aspect_ratio(landmarks, (33, 160, 158, 133, 153, 144))
        right_eye = _eye_aspect_ratio(landmarks, (362, 385, 387, 263, 373, 380))
        left_cheek_x = landmarks[234].x
        right_cheek_x = landmarks[454].x
        face_width = max(right_cheek_x - left_cheek_x, 1e-6)
        yaw_ratio = (landmarks[1].x - (left_cheek_x + right_cheek_x) / 2) / face_width
        face_height = max(landmarks[152].y - landmarks[10].y, 1e-6)
        pitch_ratio = (landmarks[1].y - landmarks[10].y) / face_height
        return FaceMotion((left_eye + right_eye) / 2, None, yaw_ratio, pitch_ratio)

    def close(self) -> None:
        self._mesh.close()


def _eye_aspect_ratio(landmarks: object, indices: tuple[int, int, int, int, int, int]) -> float:
    points = [landmarks[index] for index in indices]
    vertical = hypot(points[1].x - points[5].x, points[1].y - points[5].y) + hypot(
        points[2].x - points[4].x, points[2].y - points[4].y
    )
    horizontal = 2 * hypot(points[0].x - points[3].x, points[0].y - points[3].y)
    return vertical / max(horizontal, 1e-6)


def relative_head_action(
    motion: FaceMotion, neutral_yaw: float, neutral_pitch: float
) -> TurnDirection | None:
    if motion.yaw_ratio is None or motion.pitch_ratio is None:
        return motion.turn_direction
    yaw_delta = motion.yaw_ratio - neutral_yaw
    pitch_delta = motion.pitch_ratio - neutral_pitch
    yaw_strength = abs(yaw_delta) / 0.055
    pitch_strength = abs(pitch_delta) / 0.045
    if max(yaw_strength, pitch_strength) < 1.0:
        return None
    if yaw_strength >= pitch_strength:
        return TurnDirection.LEFT if yaw_delta < 0 else TurnDirection.RIGHT
    return TurnDirection.UP if pitch_delta < 0 else TurnDirection.DOWN


def matches_required_head_action(
    motion: FaceMotion,
    neutral_yaw: float,
    neutral_pitch: float,
    required_action: TurnDirection,
) -> bool:
    if motion.yaw_ratio is None or motion.pitch_ratio is None:
        return motion.turn_direction == required_action
    yaw_delta = motion.yaw_ratio - neutral_yaw
    pitch_delta = motion.pitch_ratio - neutral_pitch
    thresholds = {
        TurnDirection.LEFT: yaw_delta <= -0.05,
        TurnDirection.RIGHT: yaw_delta >= 0.05,
        TurnDirection.UP: pitch_delta <= -0.02,
        TurnDirection.DOWN: pitch_delta >= 0.02,
    }
    return thresholds[required_action]