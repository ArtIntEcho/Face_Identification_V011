from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import csv
from datetime import UTC, datetime, timedelta
from io import StringIO
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from face_access.camera import CameraManager, CameraUnavailableError
from face_access.config import Settings, settings
from face_access.database import Database
from face_access.liveness import ChallengeStatus, LivenessChallenge, MotionObservation
from face_access.matching import encode_embedding, find_best_candidate
from face_access.model_backends import (
    BackendUnavailableError,
    FaceModelBackend,
    UnavailableBackend,
    create_backend,
)
from face_access.motion import (
    MediaPipeMotionAnalyzer,
    MotionAnalyzer,
    matches_required_head_action,
)
from face_access.schemas import (
    AdminResponse,
    BootstrapRequest,
    LoginRequest,
    PersonCreate,
    PersonResponse,
    PersonUpdate,
)
from face_access.security import hash_password, hash_token, new_session_token, verify_password


def create_app(
    app_settings: Settings = settings,
    model_backend: FaceModelBackend | None = None,
    motion_analyzer: MotionAnalyzer | None = None,
    camera_manager: CameraManager | None = None,
) -> FastAPI:
    database = Database(app_settings.database_path)
    backend_error: str | None = None
    if model_backend is None:
        try:
            model_backend = create_backend(app_settings.model_backend, app_settings.model_dir)
        except BackendUnavailableError as error:
            model_backend = UnavailableBackend()
            backend_error = str(error)
    motion_analyzer = motion_analyzer or MediaPipeMotionAnalyzer()
    if app_settings.camera_mode not in {"browser", "server"}:
        raise ValueError("camera_mode must be 'browser' or 'server'")
    if app_settings.camera_mode == "server" and camera_manager is None:
        camera_manager = CameraManager(
            device=app_settings.camera_device,
            width=app_settings.camera_width,
            height=app_settings.camera_height,
            fps=app_settings.camera_fps,
        )
    attempts: dict[str, dict[str, object]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        if camera_manager is not None:
            camera_manager.start()
        yield
        if camera_manager is not None:
            camera_manager.stop()
        motion_analyzer.close()

    application = FastAPI(title=app_settings.app_name, lifespan=lifespan)

    def current_admin(session: str | None = Cookie(default=None)) -> AdminResponse:
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Administrator login required")
        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT username, person_id, role, operation_level
                FROM admins
                JOIN auth_sessions ON auth_sessions.admin_id = admins.id
                WHERE auth_sessions.token_hash = ?
                  AND auth_sessions.expires_at > ?
                  AND admins.is_active = 1
                """,
                (hash_token(session), datetime.now(UTC).isoformat()),
            ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is invalid or expired")
        return AdminResponse(**dict(row))

    @application.get("/api/health")
    def health() -> dict[str, object]:
        camera_status = camera_manager.status() if camera_manager is not None else None
        return {
            "status": "ok",
            "model_backend": model_backend.name,
            "model_backend_version": model_backend.version,
            "model_backend_available": model_backend.available,
            "model_backend_error": backend_error,
            "camera_mode": app_settings.camera_mode,
            "camera_available": (
                camera_status.frame_available if camera_status is not None else None
            ),
            "camera_error": camera_status.error if camera_status is not None else None,
        }

    @application.get("/api/camera/status")
    def camera_status() -> dict[str, object]:
        if camera_manager is None:
            return {"mode": "browser", "available": None}
        current = camera_manager.status()
        return {
            "mode": "server",
            "running": current.running,
            "available": current.frame_available,
            "device": current.device,
            "width": current.width,
            "height": current.height,
            "error": current.error,
        }

    @application.get("/api/camera/stream")
    def camera_stream() -> StreamingResponse:
        if camera_manager is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Server camera mode is not enabled")
        return StreamingResponse(
            camera_manager.mjpeg_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/api/camera/frame")
    def camera_frame() -> Response:
        if camera_manager is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Server camera mode is not enabled")
        try:
            image = camera_manager.read_jpeg()
        except CameraUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
        return Response(content=image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @application.post("/api/auth/bootstrap", response_model=AdminResponse, status_code=201)
    def bootstrap(payload: BootstrapRequest) -> AdminResponse:
        with database.connect() as connection:
            if connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
                raise HTTPException(status.HTTP_409_CONFLICT, "Administrator is already initialized")
            connection.execute(
                """
                INSERT INTO admins (username, password_hash, person_id, role, operation_level)
                VALUES (?, ?, ?, 'admin', 'A')
                """,
                (payload.username, hash_password(payload.password), payload.person_id),
            )
        return AdminResponse(
            username=payload.username,
            person_id=payload.person_id,
            role="admin",
            operation_level="A",
        )

    @application.post("/api/auth/login", response_model=AdminResponse)
    def login(payload: LoginRequest, response: Response) -> AdminResponse:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, person_id, role, operation_level "
                "FROM admins WHERE username = ? AND is_active = 1",
                (payload.username,),
            ).fetchone()
            if row is None or not verify_password(payload.password, row["password_hash"]):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
            token = new_session_token()
            expires_at = datetime.now(UTC) + timedelta(hours=8)
            connection.execute(
                "INSERT INTO auth_sessions (token_hash, admin_id, expires_at) VALUES (?, ?, ?)",
                (hash_token(token), row["id"], expires_at.isoformat()),
            )
        response.set_cookie(
            "session",
            token,
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=8 * 60 * 60,
        )
        return AdminResponse(**{key: row[key] for key in AdminResponse.model_fields})

    @application.get("/api/auth/me", response_model=AdminResponse)
    def me(admin: AdminResponse = Depends(current_admin)) -> AdminResponse:
        return admin

    @application.post("/api/auth/logout", status_code=204)
    def logout(response: Response, session: str | None = Cookie(default=None)) -> None:
        if session:
            with database.connect() as connection:
                connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hash_token(session),))
        response.delete_cookie("session")

    @application.get("/api/people", response_model=list[PersonResponse])
    def list_people(_: AdminResponse = Depends(current_admin)) -> list[PersonResponse]:
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM people WHERE deleted_at IS NULL ORDER BY registered_at DESC"
            ).fetchall()
        return [PersonResponse(**dict(row)) for row in rows]

    @application.post("/api/people", response_model=PersonResponse, status_code=201)
    def create_person(
        payload: PersonCreate, _: AdminResponse = Depends(current_admin)
    ) -> PersonResponse:
        try:
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO people
                        (person_id, name, department, position, operation_level, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.person_id,
                        payload.name,
                        payload.department,
                        payload.position,
                        payload.operation_level,
                        payload.notes,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM people WHERE person_id = ?", (payload.person_id,)
                ).fetchone()
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise HTTPException(status.HTTP_409_CONFLICT, "Person ID already exists") from error
            raise
        return PersonResponse(**dict(row))

    @application.patch("/api/people/{person_id}", response_model=PersonResponse)
    def update_person(
        person_id: str,
        payload: PersonUpdate,
        _: AdminResponse = Depends(current_admin),
    ) -> PersonResponse:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied")
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE people SET {assignments} WHERE person_id = ? AND deleted_at IS NULL",
                (*changes.values(), person_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
            row = connection.execute(
                "SELECT * FROM people WHERE person_id = ?", (person_id,)
            ).fetchone()
        return PersonResponse(**dict(row))

    @application.delete("/api/people/{person_id}", status_code=204)
    def soft_delete_person(
        person_id: str, _: AdminResponse = Depends(current_admin)
    ) -> None:
        deleted_at = datetime.now(UTC).isoformat()
        with database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE people SET status = 'inactive', deleted_at = ?
                WHERE person_id = ? AND deleted_at IS NULL
                """,
                (deleted_at, person_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
            connection.execute(
                "UPDATE face_templates SET is_active = 0 WHERE person_id = ?", (person_id,)
            )

    @application.post("/api/people/{person_id}/faces")
    async def enroll_faces(
        person_id: str,
        files: list[UploadFile] = File(...),
        _: AdminResponse = Depends(current_admin),
    ) -> dict[str, object]:
        if not model_backend.available:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Face model backend unavailable")
        if not 1 <= len(files) <= 10:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload between 1 and 10 photos")
        with database.connect() as connection:
            person = connection.execute(
                "SELECT status, deleted_at FROM people WHERE person_id = ?", (person_id,)
            ).fetchone()
        if person is None or person["deleted_at"] is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
        if person["status"] != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "Inactive person cannot enroll faces")

        target_directory = app_settings.registration_dir / person_id
        target_directory.mkdir(parents=True, exist_ok=True)
        successes: list[dict[str, object]] = []
        failures: list[dict[str, str]] = []
        for uploaded in files:
            filename = uploaded.filename or "photo"
            content = await uploaded.read()
            if not content or len(content) > 10 * 1024 * 1024:
                failures.append({"filename": filename, "reason": "Image is empty or exceeds 10 MB"})
                continue
            try:
                detections = model_backend.detect_faces(content)
                if len(detections) != 1:
                    reason = "No face detected" if not detections else "Multiple faces detected"
                    failures.append({"filename": filename, "reason": reason})
                    continue
                embedding = model_backend.extract_embedding(content, detections[0])
                image_path = target_directory / f"{uuid4().hex}.jpg"
                image_path.write_bytes(content)
                with database.connect() as connection:
                    cursor = connection.execute(
                        """
                        INSERT INTO face_templates
                            (person_id, image_path, embedding, model_version)
                        VALUES (?, ?, ?, ?)
                        """,
                        (person_id, str(image_path), encode_embedding(embedding), model_backend.version),
                    )
                successes.append(
                    {"filename": filename, "template_id": cursor.lastrowid, "confidence": detections[0].confidence}
                )
            except (ValueError, BackendUnavailableError) as error:
                failures.append({"filename": filename, "reason": str(error)})
        return {"success_count": len(successes), "failure_count": len(failures), "successes": successes, "failures": failures}

    @application.post("/api/authentication/challenges", status_code=201)
    def start_authentication() -> dict[str, object]:
        if not model_backend.available:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Face model backend unavailable")
        now = monotonic()
        for stale_id in [
            attempt_id
            for attempt_id, attempt in attempts.items()
            if now - float(attempt["created_at"]) > 300
        ]:
            del attempts[stale_id]
        challenge_id = uuid4().hex
        attempts[challenge_id] = {
            "challenge": None,
            "eye_closed": False,
            "blink_at": None,
            "observed_actions": [],
            "match_image": None,
            "match_quality": -1.0,
            "neutral_yaw": None,
            "neutral_pitch": None,
            "action_candidate": None,
            "action_candidate_frames": 0,
            "last_pose_delta": None,
            "created_at": now,
            "result": None,
        }
        return {
            "challenge_id": challenge_id,
            "status": "waiting_for_face",
            "timeout_seconds": app_settings.active_liveness_timeout_seconds,
        }

    @application.post("/api/authentication/challenges/{challenge_id}/frames")
    async def authenticate_frame(
        challenge_id: str, frame: UploadFile | None = File(default=None)
    ) -> dict[str, object]:
        attempt = attempts.get(challenge_id)
        if attempt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Authentication challenge not found")
        if attempt["result"] is not None:
            return attempt["result"]  # type: ignore[return-value]
        if camera_manager is not None:
            try:
                image = camera_manager.read_jpeg()
            except CameraUnavailableError as error:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
        elif frame is not None:
            image = await frame.read()
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A camera frame is required")
        detections = model_backend.detect_faces(image)
        if len(detections) != 1:
            return {
                "challenge_id": challenge_id,
                "status": "waiting_for_face",
                "message": "未检测到人脸" if not detections else "画面中只能有一张人脸",
                "detection_count": len(detections),
            }
        now = monotonic()
        challenge = attempt["challenge"]
        if challenge is None:
            challenge = LivenessChallenge.create(
                now,
                app_settings.active_liveness_timeout_seconds,
                require_head_action=True,
            )
            attempt["challenge"] = challenge
        motion = motion_analyzer.analyze(image)
        blink_detected = False
        turn_direction = None
        previous_status = challenge.status
        if motion is not None:
            if motion.eye_aspect_ratio <= 0.18:
                attempt["eye_closed"] = True
            elif attempt["eye_closed"] and motion.eye_aspect_ratio >= 0.21:
                blink_detected = True
                attempt["eye_closed"] = False
            if (
                previous_status == ChallengeStatus.WAITING_FOR_BLINK
                and motion.yaw_ratio is not None
                and motion.pitch_ratio is not None
            ):
                neutral_yaw = attempt["neutral_yaw"]
                neutral_pitch = attempt["neutral_pitch"]
                attempt["neutral_yaw"] = (
                    motion.yaw_ratio
                    if not isinstance(neutral_yaw, float)
                    else neutral_yaw * 0.8 + motion.yaw_ratio * 0.2
                )
                attempt["neutral_pitch"] = (
                    motion.pitch_ratio
                    if not isinstance(neutral_pitch, float)
                    else neutral_pitch * 0.8 + motion.pitch_ratio * 0.2
                )
            elif previous_status == ChallengeStatus.WAITING_FOR_ACTION:
                neutral_yaw = attempt["neutral_yaw"]
                neutral_pitch = attempt["neutral_pitch"]
                if isinstance(neutral_yaw, float) and isinstance(neutral_pitch, float):
                    candidate = (
                        challenge.required_turn
                        if matches_required_head_action(
                            motion,
                            neutral_yaw,
                            neutral_pitch,
                            challenge.required_turn,
                        )
                        else None
                    )
                    if motion.yaw_ratio is not None and motion.pitch_ratio is not None:
                        attempt["last_pose_delta"] = {
                            "yaw": round(motion.yaw_ratio - neutral_yaw, 4),
                            "pitch": round(motion.pitch_ratio - neutral_pitch, 4),
                        }
                else:
                    candidate = motion.turn_direction
                if candidate == attempt["action_candidate"]:
                    attempt["action_candidate_frames"] = int(attempt["action_candidate_frames"]) + 1
                else:
                    attempt["action_candidate"] = candidate
                    attempt["action_candidate_frames"] = 1 if candidate is not None else 0
                if candidate is not None:
                    observed_actions = attempt["observed_actions"]
                    if not observed_actions or observed_actions[-1] != candidate:
                        observed_actions.append(candidate)
                if int(attempt["action_candidate_frames"]) >= 2:
                    turn_direction = candidate
            if turn_direction is not None:
                observed_actions = attempt["observed_actions"]
                if not observed_actions or observed_actions[-1] != turn_direction:
                    observed_actions.append(turn_direction)
        if (
            previous_status == ChallengeStatus.WAITING_FOR_BLINK
            and motion is not None
            and motion.eye_aspect_ratio >= 0.21
        ):
            match_quality = detections[0].confidence + min(motion.eye_aspect_ratio, 0.3)
            if match_quality > float(attempt["match_quality"]):
                attempt["match_image"] = image
                attempt["match_quality"] = match_quality
        challenge_status = challenge.observe(
            MotionObservation(blink_detected, turn_direction, now)
        )
        if (
            previous_status == ChallengeStatus.WAITING_FOR_BLINK
            and challenge_status != ChallengeStatus.WAITING_FOR_BLINK
        ):
            attempt["blink_at"] = now
        elapsed_seconds = now - challenge.started_at_seconds
        response: dict[str, object] = {
            "challenge_id": challenge_id,
            "status": challenge_status,
            "required_turn": challenge.required_turn if challenge.require_head_action else None,
            "required_action": challenge.required_turn if challenge.require_head_action else None,
            "blink_detected": blink_detected,
            "timeout_seconds": challenge.timeout_seconds,
            "remaining_seconds": max(0.0, challenge.timeout_seconds - elapsed_seconds),
            "face_detection": {
                "x": detections[0].x,
                "y": detections[0].y,
                "width": detections[0].width,
                "height": detections[0].height,
                "confidence": detections[0].confidence,
            },
        }
        if challenge_status not in {ChallengeStatus.PASSED, ChallengeStatus.FAILED}:
            return response

        person = None
        similarity = None
        pad_score = None
        failure_reason = challenge.failure_reason
        if challenge_status == ChallengeStatus.PASSED:
            pad_score = model_backend.passive_liveness_score(image, detections[0])
            if pad_score < app_settings.passive_liveness_threshold:
                failure_reason = "passive_liveness_failed"
            else:
                match_image = attempt["match_image"]
                match_detections = (
                    model_backend.detect_faces(match_image)
                    if isinstance(match_image, bytes)
                    else detections
                )
                matching_image = match_image if len(match_detections) == 1 else image
                matching_face = match_detections[0] if len(match_detections) == 1 else detections[0]
                probe = model_backend.extract_embedding(matching_image, matching_face)
                with database.connect() as connection:
                    templates = connection.execute(
                        """
                        SELECT face_templates.person_id, face_templates.embedding
                        FROM face_templates JOIN people USING (person_id)
                        WHERE face_templates.is_active = 1 AND face_templates.embedding IS NOT NULL
                          AND people.status = 'active' AND people.deleted_at IS NULL
                        """
                    ).fetchall()
                match = find_best_candidate(
                    probe,
                    ((row["person_id"], row["embedding"]) for row in templates),
                )
                similarity = match.similarity if match is not None else None
                if match is None or match.similarity < app_settings.similarity_threshold:
                    failure_reason = "face_not_recognized"
                else:
                    with database.connect() as connection:
                        person = connection.execute(
                            "SELECT person_id, name, operation_level FROM people WHERE person_id = ?",
                            (match.person_id,),
                        ).fetchone()
        accepted = failure_reason is None and person is not None
        app_settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = app_settings.snapshot_dir / f"{uuid4().hex}.jpg"
        snapshot_path.write_bytes(image)
        duration_ms = round((now - challenge.started_at_seconds) * 1000)
        blink_at = attempt["blink_at"]
        stage_timings: dict[str, object] = {
            "active_liveness_ms": duration_ms,
            "liveness_mode": "blink_and_random_head_action",
            "required_action": challenge.required_turn,
            "observed_actions": attempt["observed_actions"],
            "matching_frame": "best_open_eye_pre_blink",
            "neutral_head_pose": {
                "yaw": attempt["neutral_yaw"],
                "pitch": attempt["neutral_pitch"],
            },
            "final_pose_delta": attempt["last_pose_delta"],
        }
        if isinstance(blink_at, float):
            stage_timings["blink_ms"] = round(
                (blink_at - challenge.started_at_seconds) * 1000
            )
            stage_timings["action_ms"] = round((now - blink_at) * 1000)
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO authentication_logs
                    (result, person_id, person_name, operation_level, failure_reason,
                     challenge_score, pad_score, similarity, duration_ms, stage_timings_json,
                     model_backend, model_version, snapshot_path)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "accepted" if accepted else "rejected",
                    person["person_id"] if person else None,
                    person["name"] if person else None,
                    person["operation_level"] if person else None,
                    failure_reason,
                    1.0 if challenge_status == ChallengeStatus.PASSED else 0.0,
                    pad_score,
                    similarity,
                    duration_ms,
                    json.dumps(stage_timings),
                    model_backend.name,
                    model_backend.version,
                    str(snapshot_path),
                ),
            )
        response.update(
            {
                "status": "accepted" if accepted else "rejected",
                "person_id": person["person_id"] if person else None,
                "person_name": person["name"] if person else None,
                "operation_level": person["operation_level"] if person else None,
                "failure_reason": failure_reason,
                "pad_score": pad_score,
                "similarity": similarity,
                "duration_ms": duration_ms,
            }
        )
        attempt["result"] = response
        return response

    def filtered_logs(
        date_from: str | None, date_to: str | None, name: str | None, result: str | None
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        values: list[str] = []
        if date_from:
            clauses.append("authenticated_at >= ?")
            values.append(date_from)
        if date_to:
            clauses.append("authenticated_at <= ?")
            values.append(date_to)
        if name:
            clauses.append("person_name LIKE ?")
            values.append(f"%{name}%")
        if result:
            clauses.append("result = ?")
            values.append(result)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM authentication_logs {where} ORDER BY authenticated_at DESC LIMIT 5000",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    @application.get("/api/logs")
    def list_logs(
        date_from: str | None = None,
        date_to: str | None = None,
        name: str | None = None,
        result: str | None = None,
        _: AdminResponse = Depends(current_admin),
    ) -> list[dict[str, object]]:
        return filtered_logs(date_from, date_to, name, result)

    @application.get("/api/logs/export")
    def export_logs(
        date_from: str | None = None,
        date_to: str | None = None,
        name: str | None = None,
        result: str | None = None,
        _: AdminResponse = Depends(current_admin),
    ) -> StreamingResponse:
        rows = filtered_logs(date_from, date_to, name, result)
        safe_fields = [
            "authenticated_at",
            "result",
            "person_id",
            "person_name",
            "operation_level",
            "failure_reason",
            "challenge_score",
            "pad_score",
            "similarity",
            "duration_ms",
            "stage_timings_json",
            "model_backend",
            "model_version",
        ]
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=safe_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=authentication-logs.csv"},
        )

    static_directory = Path(__file__).parent / "static"
    application.mount("/", StaticFiles(directory=static_directory, html=True), name="web")

    return application


app = create_app()
