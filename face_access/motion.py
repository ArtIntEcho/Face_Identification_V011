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
        turn = None
        if yaw_ratio < -0.08:
            turn = TurnDirection.LEFT
        elif yaw_ratio > 0.08:
            turn = TurnDirection.RIGHT
        return FaceMotion((left_eye + right_eye) / 2, turn)

    def close(self) -> None:
        self._mesh.close()


def _eye_aspect_ratio(landmarks: object, indices: tuple[int, int, int, int, int, int]) -> float:
    points = [landmarks[index] for index in indices]
    vertical = hypot(points[1].x - points[5].x, points[1].y - points[5].y) + hypot(
        points[2].x - points[4].x, points[2].y - points[4].y
    )
    horizontal = 2 * hypot(points[0].x - points[3].x, points[0].y - points[3].y)
    return vertical / max(horizontal, 1e-6)