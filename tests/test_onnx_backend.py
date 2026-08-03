from pathlib import Path

import cv2
import numpy as np

from face_access.model_backends import FaceDetection, OnnxFaceBackend, _anchor_centers, _nms, _scaled_face_crop


MODEL_DIRECTORY = Path("models/hailo8-face")


def test_scrfd_anchor_layout_matches_model_outputs() -> None:
    assert _anchor_centers(640, 8).shape == (12800, 2)
    assert _anchor_centers(640, 16).shape == (3200, 2)
    assert _anchor_centers(640, 32).shape == (800, 2)


def test_nms_keeps_highest_scoring_overlapping_box() -> None:
    boxes = np.asarray([[0, 0, 10, 10], [1, 1, 11, 11], [30, 30, 40, 40]], dtype=np.float32)
    scores = np.asarray([0.9, 0.8, 0.7], dtype=np.float32)

    assert _nms(boxes, scores, 0.4) == [0, 2]


def test_onnx_backend_runs_on_blank_image_without_false_detection() -> None:
    backend = OnnxFaceBackend(MODEL_DIRECTORY)
    ok, encoded = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))

    assert ok
    assert backend.available
    assert backend.detect_faces(encoded.tobytes()) == []


def test_scaled_face_crop_stays_inside_image_at_edge() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)

    crop = _scaled_face_crop(image, FaceDetection(0, 0, 30, 40, 0.9), 4.0)

    assert crop.shape == (100, 75, 3)


def test_passive_liveness_fusion_returns_probability() -> None:
    backend = OnnxFaceBackend(MODEL_DIRECTORY)
    image = np.full((160, 160, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)

    assert ok
    score = backend.passive_liveness_score(encoded.tobytes(), FaceDetection(40, 40, 80, 80, 0.9))
    assert 0.0 <= score <= 1.0