from face_access.liveness import (
    ChallengeStatus,
    LivenessChallenge,
    MotionObservation,
    TurnDirection,
)
from face_access.model_backends import BackendUnavailableError, UnavailableBackend
from face_access.motion import FaceMotion, matches_required_head_action, relative_head_action


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


def test_challenge_accepts_vertical_action_after_blink() -> None:
    challenge = LivenessChallenge(TurnDirection.UP, started_at_seconds=10.0)

    action_first = challenge.observe(MotionObservation(False, TurnDirection.UP, 11.0))
    blink = challenge.observe(MotionObservation(True, None, 12.0))
    requested_action = challenge.observe(MotionObservation(False, TurnDirection.UP, 13.0))

    assert action_first == ChallengeStatus.WAITING_FOR_BLINK
    assert blink == ChallengeStatus.WAITING_FOR_ACTION
    assert requested_action == ChallengeStatus.PASSED


def test_blink_frame_cannot_complete_head_action() -> None:
    challenge = LivenessChallenge(TurnDirection.DOWN, started_at_seconds=10.0)

    blink_with_action = challenge.observe(
        MotionObservation(True, TurnDirection.DOWN, 11.0)
    )

    assert blink_with_action == ChallengeStatus.WAITING_FOR_ACTION


def test_blink_only_challenge_passes_before_identity_matching() -> None:
    challenge = LivenessChallenge(
        TurnDirection.LEFT,
        started_at_seconds=10.0,
        require_head_action=False,
    )

    result = challenge.observe(MotionObservation(True, TurnDirection.LEFT, 11.0))

    assert result == ChallengeStatus.PASSED


def test_head_actions_are_relative_to_neutral_pose() -> None:
    neutral_yaw = 0.09
    neutral_pitch = 0.61

    assert relative_head_action(
        FaceMotion(0.25, None, yaw_ratio=0.09, pitch_ratio=0.61),
        neutral_yaw,
        neutral_pitch,
    ) is None
    assert relative_head_action(
        FaceMotion(0.25, None, yaw_ratio=0.02, pitch_ratio=0.61),
        neutral_yaw,
        neutral_pitch,
    ) == TurnDirection.LEFT
    assert relative_head_action(
        FaceMotion(0.25, None, yaw_ratio=0.16, pitch_ratio=0.61),
        neutral_yaw,
        neutral_pitch,
    ) == TurnDirection.RIGHT
    assert relative_head_action(
        FaceMotion(0.25, None, yaw_ratio=0.09, pitch_ratio=0.55),
        neutral_yaw,
        neutral_pitch,
    ) == TurnDirection.UP
    assert relative_head_action(
        FaceMotion(0.25, None, yaw_ratio=0.09, pitch_ratio=0.67),
        neutral_yaw,
        neutral_pitch,
    ) == TurnDirection.DOWN


def test_required_action_uses_only_its_own_pose_axis() -> None:
    noisy_left_turn = FaceMotion(0.25, None, yaw_ratio=0.02, pitch_ratio=0.68)

    assert matches_required_head_action(
        noisy_left_turn, 0.09, 0.61, TurnDirection.LEFT
    )
    assert not matches_required_head_action(
        noisy_left_turn, 0.09, 0.61, TurnDirection.RIGHT
    )
    assert matches_required_head_action(
        noisy_left_turn, 0.09, 0.61, TurnDirection.DOWN
    )


def test_challenge_reports_blink_timeout_after_configured_limit() -> None:
    challenge = LivenessChallenge(
        TurnDirection.RIGHT, started_at_seconds=1.0, timeout_seconds=15.0
    )

    result = challenge.observe(MotionObservation(False, None, 16.01))

    assert result == ChallengeStatus.FAILED
    assert challenge.failure_reason == "blink_timeout"


def test_challenge_reports_action_timeout_after_blink() -> None:
    challenge = LivenessChallenge(
        TurnDirection.RIGHT, started_at_seconds=1.0, timeout_seconds=15.0
    )
    challenge.observe(MotionObservation(True, None, 2.0))

    result = challenge.observe(MotionObservation(False, None, 16.01))

    assert result == ChallengeStatus.FAILED
    assert challenge.failure_reason == "action_timeout"


def test_unavailable_backend_never_silently_falls_back() -> None:
    backend = UnavailableBackend()

    assert backend.available is False
    try:
        backend.detect_faces(b"image")
    except BackendUnavailableError as error:
        assert "No face model backend" in str(error)
    else:
        raise AssertionError("Unavailable backend unexpectedly accepted inference")