from dataclasses import dataclass
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
    similarity_threshold: float = 0.75 # 0.45 -> 0.75
    active_liveness_timeout_seconds: float = 15.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "face_access.sqlite3"

    @property
    def registration_dir(self) -> Path:
        return self.data_dir / "registrations"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"


settings = Settings()
