from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import onnxruntime as ort

from face_access.matching import normalize_embedding


class BackendUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FaceDetection:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    landmarks: tuple[tuple[float, float], ...] = ()


class FaceModelBackend(Protocol):
    name: str
    version: str

    @property
    def available(self) -> bool: ...

    def detect_faces(self, image: bytes) -> list[FaceDetection]: ...

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]: ...

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float: ...


class UnavailableBackend:
    name = "unavailable"
    version = "none"

    @property
    def available(self) -> bool:
        return False

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        self._raise()

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        self._raise()

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        self._raise()

    @staticmethod
    def _raise() -> None:
        raise BackendUnavailableError(
            "No face model backend is configured. Install the PC model artifacts or use HailoRT on the Hailo-8 platform."
        )


class OnnxFaceBackend:
    name = "onnxruntime"
    version = "scrfd_500m+arcface_mobilefacenet+minifasnet_fusion"
    input_size = 640
    score_threshold = 0.5
    nms_threshold = 0.4

    def __init__(self, model_directory: Path) -> None:
        detection_path = model_directory / "scrfd_500m" / "scrfd_500m_bnkps.onnx"
        recognition_path = model_directory / "arcface_mobilefacenet" / "mbf.onnx"
        passive_liveness_paths = (
            model_directory / "minifasnet" / "2.7_80x80_MiniFASNetV2.onnx",
            model_directory / "minifasnet" / "4_0_0_80x80_MiniFASNetV1SE.onnx",
        )
        required_paths = (detection_path, recognition_path, *passive_liveness_paths)
        missing = [str(path) for path in required_paths if not path.is_file()]
        if missing:
            raise BackendUnavailableError(f"Missing ONNX model artifacts: {', '.join(missing)}")
        providers = ["CPUExecutionProvider"]
        self._detector = ort.InferenceSession(str(detection_path), providers=providers)
        self._recognizer = ort.InferenceSession(str(recognition_path), providers=providers)
        self._passive_liveness_models = tuple(
            (scale, ort.InferenceSession(str(path), providers=providers))
            for scale, path in zip((2.7, 4.0), passive_liveness_paths, strict=True)
        )
        self._detector_input = self._detector.get_inputs()[0].name
        self._recognizer_input = self._recognizer.get_inputs()[0].name

    @property
    def available(self) -> bool:
        return True

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        frame = _decode_image(image)
        height, width = frame.shape[:2]
        scale = min(self.input_size / width, self.input_size / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        resized = cv2.resize(frame, (resized_width, resized_height))
        canvas = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        canvas[:resized_height, :resized_width] = resized
        blob = cv2.dnn.blobFromImage(
            canvas,
            scalefactor=1.0 / 128.0,
            size=(self.input_size, self.input_size),
            mean=(127.5, 127.5, 127.5),
            swapRB=True,
        )
        values = self._detector.run(None, {self._detector_input: blob})
        outputs = {
            metadata.name: value for metadata, value in zip(self._detector.get_outputs(), values, strict=True)
        }
        boxes: list[np.ndarray] = []
        scores: list[np.ndarray] = []
        landmarks: list[np.ndarray] = []
        for stride in (8, 16, 32):
            stride_scores = outputs[f"score_{stride}"][0, :, 0]
            selected = np.where(stride_scores >= self.score_threshold)[0]
            if selected.size == 0:
                continue
            anchors = _anchor_centers(self.input_size, stride)
            selected_anchors = anchors[selected]
            distances = outputs[f"bbox_{stride}"][0, selected] * stride
            keypoint_offsets = outputs[f"kps_{stride}"][0, selected].reshape(-1, 5, 2) * stride
            stride_boxes = np.column_stack(
                (
                    selected_anchors[:, 0] - distances[:, 0],
                    selected_anchors[:, 1] - distances[:, 1],
                    selected_anchors[:, 0] + distances[:, 2],
                    selected_anchors[:, 1] + distances[:, 3],
                )
            )
            boxes.append(stride_boxes / scale)
            scores.append(stride_scores[selected])
            landmarks.append((selected_anchors[:, None, :] + keypoint_offsets) / scale)
        if not boxes:
            return []
        all_boxes = np.concatenate(boxes)
        all_scores = np.concatenate(scores)
        all_landmarks = np.concatenate(landmarks)
        kept = _nms(all_boxes, all_scores, self.nms_threshold)
        detections: list[FaceDetection] = []
        for index in kept:
            left, top, right, bottom = all_boxes[index]
            left = float(np.clip(left, 0, width - 1))
            top = float(np.clip(top, 0, height - 1))
            right = float(np.clip(right, left + 1, width))
            bottom = float(np.clip(bottom, top + 1, height))
            detections.append(
                FaceDetection(
                    x=round(left),
                    y=round(top),
                    width=round(right - left),
                    height=round(bottom - top),
                    confidence=float(all_scores[index]),
                    landmarks=tuple((float(x), float(y)) for x, y in all_landmarks[index]),
                )
            )
        return detections

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        if len(face.landmarks) != 5:
            raise ValueError("ArcFace alignment requires five facial landmarks")
        frame = _decode_image(image)
        source = np.asarray(face.landmarks, dtype=np.float32)
        target = np.asarray(
            [
                [38.2946, 51.6963],
                [73.5318, 51.5014],
                [56.0252, 71.7366],
                [41.5493, 92.3655],
                [70.7299, 92.2041],
            ],
            dtype=np.float32,
        )
        transform, _ = cv2.estimateAffinePartial2D(source, target, method=cv2.LMEDS)
        if transform is None:
            raise ValueError("Unable to align the detected face")
        aligned = cv2.warpAffine(frame, transform, (112, 112), borderValue=0)
        blob = cv2.dnn.blobFromImage(
            aligned,
            scalefactor=1.0 / 127.5,
            size=(112, 112),
            mean=(127.5, 127.5, 127.5),
            swapRB=True,
        )
        embedding = self._recognizer.run(None, {self._recognizer_input: blob})[0][0]
        return normalize_embedding(embedding.tolist())

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        frame = _decode_image(image)
        probabilities: list[float] = []
        for scale, session in self._passive_liveness_models:
            crop = _scaled_face_crop(frame, face, scale)
            resized = cv2.resize(crop, (80, 80))
            tensor = resized.transpose(2, 0, 1).astype(np.float32)[None, :]
            logits = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
            shifted = logits - np.max(logits)
            softmax = np.exp(shifted) / np.exp(shifted).sum()
            probabilities.append(float(softmax[1]))
        return float(np.mean(probabilities))


class HailoBackend:
    name = "hailort"

    def __init__(self, hef_path: Path, version: str = "unknown") -> None:
        self.hef_path = hef_path
        self.version = version
        self._runtime_error: str | None = None
        try:
            import hailo_platform  # noqa: F401
        except ImportError:
            self._runtime_error = "pyHailoRT is not installed"
        if not hef_path.is_file():
            self._runtime_error = f"HEF file does not exist: {hef_path}"

    @property
    def available(self) -> bool:
        return self._runtime_error is None

    def detect_faces(self, image: bytes) -> list[FaceDetection]:
        self._raise_until_runtime_adapter_is_configured()

    def extract_embedding(self, image: bytes, face: FaceDetection) -> list[float]:
        self._raise_until_runtime_adapter_is_configured()

    def passive_liveness_score(self, image: bytes, face: FaceDetection) -> float:
        self._raise_until_runtime_adapter_is_configured()

    def _raise_until_runtime_adapter_is_configured(self) -> None:
        detail = self._runtime_error or "HEF stream mappings are not configured"
        raise BackendUnavailableError(f"Hailo backend unavailable: {detail}")


def create_backend(name: str, model_directory: Path = Path("models/hailo8-face")) -> FaceModelBackend:
    if name == "unavailable":
        return UnavailableBackend()
    if name == "onnxruntime":
        return OnnxFaceBackend(model_directory)
    raise BackendUnavailableError(f"Unsupported model backend: {name}")


def _decode_image(image: bytes) -> np.ndarray:
    frame = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Image is not a supported JPEG or PNG")
    return frame


def _anchor_centers(input_size: int, stride: int) -> np.ndarray:
    grid_size = input_size // stride
    grid_x, grid_y = np.meshgrid(np.arange(grid_size), np.arange(grid_size))
    centers = np.column_stack((grid_x.reshape(-1), grid_y.reshape(-1))).astype(np.float32) * stride
    return np.repeat(centers, 2, axis=0)


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    left, top, right, bottom = boxes.T
    areas = np.maximum(0, right - left + 1) * np.maximum(0, bottom - top + 1)
    order = scores.argsort()[::-1]
    kept: list[int] = []
    while order.size:
        current = int(order[0])
        kept.append(current)
        intersection_left = np.maximum(left[current], left[order[1:]])
        intersection_top = np.maximum(top[current], top[order[1:]])
        intersection_right = np.minimum(right[current], right[order[1:]])
        intersection_bottom = np.minimum(bottom[current], bottom[order[1:]])
        intersection = np.maximum(0, intersection_right - intersection_left + 1) * np.maximum(
            0, intersection_bottom - intersection_top + 1
        )
        overlap = intersection / (areas[current] + areas[order[1:]] - intersection)
        order = order[np.where(overlap <= threshold)[0] + 1]
    return kept


def _scaled_face_crop(frame: np.ndarray, face: FaceDetection, scale: float) -> np.ndarray:
    source_height, source_width = frame.shape[:2]
    scale = min((source_height - 1) / face.height, (source_width - 1) / face.width, scale)
    new_width = face.width * scale
    new_height = face.height * scale
    center_x = face.x + face.width / 2
    center_y = face.y + face.height / 2
    left = center_x - new_width / 2
    top = center_y - new_height / 2
    right = center_x + new_width / 2
    bottom = center_y + new_height / 2
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > source_width - 1:
        left -= right - source_width + 1
        right = source_width - 1
    if bottom > source_height - 1:
        top -= bottom - source_height + 1
        bottom = source_height - 1
    return frame[int(top) : int(bottom) + 1, int(left) : int(right) + 1]
