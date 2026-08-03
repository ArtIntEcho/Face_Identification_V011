from face_access.liveness import (
    ChallengeStatus,
    LivenessChallenge,
    MotionObservation,
    TurnDirection,
)
from face_access.model_backends import BackendUnavailableError, UnavailableBackend


def test_challenge_requires_blink_before_requested_turn() -> None:
    challenge = LivenessChallenge(TurnDirection.LEFT, started_at_seconds=10.0)

    turn_first = challenge.observe(MotionObservation(False, TurnDirection.LEFT, 11.0))
    blink = challenge.observe(MotionObservation(True, None, 12.0))
    wrong_turn = challenge.observe(MotionObservation(False, TurnDirection.RIGHT, 13.0))
    requested_turn = challenge.observe(MotionObservation(False, TurnDirection.LEFT, 14.0))

    assert turn_first == ChallengeStatus.WAITING_FOR_BLINK
    assert blink == ChallengeStatus.WAITING_FOR_TURN
    assert wrong_turn == ChallengeStatus.WAITING_FOR_TURN
    assert requested_turn == ChallengeStatus.PASSED


def test_challenge_reports_blink_timeout_after_configured_limit() -> None:
    challenge = LivenessChallenge(
        TurnDirection.RIGHT, started_at_seconds=1.0, timeout_seconds=15.0
    )

    result = challenge.observe(MotionObservation(False, None, 16.01))

    assert result == ChallengeStatus.FAILED
    assert challenge.failure_reason == "blink_timeout"


def test_challenge_reports_turn_timeout_after_blink() -> None:
    challenge = LivenessChallenge(
        TurnDirection.RIGHT, started_at_seconds=1.0, timeout_seconds=15.0
    )
    challenge.observe(MotionObservation(True, None, 2.0))

    result = challenge.observe(MotionObservation(False, None, 16.01))

    assert result == ChallengeStatus.FAILED
    assert challenge.failure_reason == "turn_timeout"


def test_unavailable_backend_never_silently_falls_back() -> None:
    backend = UnavailableBackend()

    assert backend.available is False
    try:
        backend.detect_faces(b"image")
    except BackendUnavailableError as error:
        assert "No face model backend" in str(error)
    else:
        raise AssertionError("Unavailable backend unexpectedly accepted inference")