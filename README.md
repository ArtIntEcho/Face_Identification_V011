# Face Access

Face Access is a local face-authentication and access-control prototype for Windows PCs. It combines SCRFD face detection, 512-dimensional ArcFace templates, MediaPipe active liveness, dual MiniFASNet passive liveness, 1:N identity search, audit logging, and a local web console.

## Features

- Local camera processing with ONNX Runtime; camera images are not sent to an external service.
- Guided enrollment using five complementary poses: front, slight left, slight right, slight up, and slight down.
- Randomized active liveness: blink first, followed by a random left, right, up, or down head action.
- Passive liveness scoring with two MiniFASNet models.
- Identity matching from a frontal pre-action frame, so the requested head direction does not bias the ArcFace comparison.
- Optional face box and detector confidence overlay.
- Chinese, English, and German web interfaces; the selected language is saved in the browser.
- Detailed audit records with the required action, observed action sequence, stage timings, liveness score, similarity, backend, and total duration.
- Filtered CSV audit export.

## Requirements

- Windows 10 or Windows 11
- Python 3.12
- A webcam
- The ONNX model files listed under [Models](#models)

## Installation

Create a virtual environment if one does not already exist, then install the application and development dependencies:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## Running

```powershell
.venv\Scripts\python.exe -m uvicorn face_access.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in Microsoft Edge or another modern browser. On first use, initialize the level-A administrator, log in, and add an authorized person.

## Enrollment

Open **People**, select **Enroll face**, and use camera capture whenever possible. Complete all five guided poses before creating the templates. Five varied, sharp images are preferable to a larger set of nearly identical images: pose coverage and image quality improve matching more reliably than duplicate samples and keep 1:N search costs predictable.

The upload fallback accepts 1-10 JPEG or PNG files and reports unusable files individually. Use one face per image with even lighting, no motion blur, and no severe occlusion.

## Authentication Flow

1. The application waits for exactly one face and retains the best open-eye frontal frame for identity matching.
2. The user blinks naturally.
3. The application randomly requests left, right, slightly up, or slightly down. Only the requested motion axis is evaluated against the pre-blink neutral pose, and two consecutive frames must confirm it.
4. The completed-action frame is checked for passive liveness.
5. Only after active and passive liveness pass does ArcFace compare the retained frontal frame against active templates.

The active challenge must finish within 15 seconds. A failed attempt can be retried without stopping the camera.

The camera panel includes a **Show box and confidence** checkbox. This changes only the visualization; detection and authentication continue when the overlay is hidden.

## Audit Logs

Administrators can filter logs by date, name, and result. Records include the randomly required action, observed action, blink and action timings, identified person, passive-liveness score, best similarity, backend, and total duration.

CSV exports include `stage_timings_json`, which contains fields such as:

```json
{
	"active_liveness_ms": 3969,
	"liveness_mode": "blink_and_random_head_action",
	"required_action": "down",
	"observed_actions": ["down"],
	"matching_frame": "best_open_eye_pre_blink",
	"blink_ms": 1700,
	"action_ms": 2300
}
```

## Tests

Run the complete test suite:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Run only the authentication and liveness tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_authentication_flow.py tests/test_liveness.py -q
```

## Models

Expected model artifacts under `models/hailo8-face`:

- `scrfd_500m/scrfd_500m_bnkps.onnx`: 640x640 face detection with five facial landmarks.
- `arcface_mobilefacenet/mbf.onnx`: 112x112 ArcFace MobileFaceNet with a 512-dimensional output.
- `minifasnet/2.7_80x80_MiniFASNetV2.onnx` and `minifasnet/4_0_0_80x80_MiniFASNetV1SE.onnx`: passive liveness models using 2.7x and 4.0x crops.
- `tools/export_minifasnet.py`: reproducible MiniFASNet export utility. Install `.[export]` before running it.

The default thresholds in `face_access/config.py` are `0.80` for passive liveness and `0.70` for identity similarity. The active-liveness timeout is 15 seconds.

## Data

Runtime data is stored locally:

- `data/face_access.sqlite3`: people, templates, sessions, and audit metadata.
- `data/registrations/`: enrollment images.
- `data/snapshots/`: authentication snapshots.

Protect and retain these files according to the applicable biometric-data policy. Do not commit runtime data or personal images to a public repository.

## Current Limitations

- The liveness and similarity thresholds require calibration with representative users, cameras, lighting, and print/screen/video attack samples. Current values do not establish a production FAR, FRR, or attack-detection claim.
- InsightFace pretrained-model licensing must receive legal review before commercial deployment.
- The included Windows path uses ONNX Runtime. Hailo-8 HEF compilation, INT8 accuracy, and end-to-end performance require testing on the target Hailo platform.
