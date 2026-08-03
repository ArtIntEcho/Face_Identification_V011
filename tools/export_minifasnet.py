from __future__ import annotations

import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch


ARCHIVE_URL = "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/archive/refs/heads/master.zip"
MODEL_NAMES = (
    "2.7_80x80_MiniFASNetV2.pth",
    "4_0_0_80x80_MiniFASNetV1SE.pth",
)


def export_models(output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary_directory:
        archive_path = Path(temporary_directory) / "source.zip"
        urllib.request.urlretrieve(ARCHIVE_URL, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temporary_directory)
        source_root = Path(temporary_directory) / "Silent-Face-Anti-Spoofing-master"
        sys.path.insert(0, str(source_root))
        from src.anti_spoof_predict import MODEL_MAPPING
        from src.utility import get_kernel, parse_model_name

        for model_name in MODEL_NAMES:
            height, width, model_type, _ = parse_model_name(model_name)
            model = MODEL_MAPPING[model_type](conv6_kernel=get_kernel(height, width))
            state = torch.load(
                source_root / "resources" / "anti_spoof_models" / model_name,
                map_location="cpu",
                weights_only=True,
            )
            if next(iter(state)).startswith("module."):
                state = {key.removeprefix("module."): value for key, value in state.items()}
            model.load_state_dict(state)
            model.eval()
            sample = torch.rand(1, 3, height, width)
            output_path = output_directory / model_name.replace(".pth", ".onnx")
            torch.onnx.export(
                model,
                sample,
                output_path,
                input_names=["image"],
                output_names=["logits"],
                opset_version=13,
            )
            with torch.no_grad():
                expected = model(sample).numpy()
            session = ort.InferenceSession(str(output_path), providers=["CPUExecutionProvider"])
            actual = session.run(None, {"image": sample.numpy()})[0]
            difference = float(np.max(np.abs(expected - actual)))
            if difference > 1e-4:
                raise RuntimeError(f"{model_name} ONNX parity failed: max difference {difference}")
            print(f"Exported {output_path} (max difference {difference:.8f})")


if __name__ == "__main__":
    export_models(Path("models/hailo8-face/minifasnet"))