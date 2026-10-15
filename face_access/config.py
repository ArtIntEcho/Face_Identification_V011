from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Face Access"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    model_backend: str = "onnxruntime"
    model_dir: Path = Path("models/hailo8-face")
    passive_liveness_threshold: float = 0.80
    similarity_threshold: float = 0.70
    active_liveness_timeout_seconds: float = 15.0
    camera_mode: str = "browser"
    camera_device: str = "/dev/video0"
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 15

    @property
    def database_path(self) -> Path:
        return self.data_dir / "face_access.sqlite3"

    @property
    def registration_dir(self) -> Path:
        return self.data_dir / "registrations"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"


settings = Settings(
    camera_mode=os.getenv("FACE_ACCESS_CAMERA_MODE", "browser").lower(),
    camera_device=os.getenv("FACE_ACCESS_CAMERA_DEVICE", "/dev/video0"),
    camera_width=int(os.getenv("FACE_ACCESS_CAMERA_WIDTH", "1280")),
    camera_height=int(os.getenv("FACE_ACCESS_CAMERA_HEIGHT", "720")),
    camera_fps=int(os.getenv("FACE_ACCESS_CAMERA_FPS", "15")),
)
