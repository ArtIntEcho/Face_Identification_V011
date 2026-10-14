import random
from dataclasses import dataclass
from enum import StrEnum


class TurnDirection(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class ChallengeStatus(StrEnum):
    WAITING_FOR_BLINK = "waiting_for_blink"
    WAITING_FOR_ACTION = "waiting_for_action"
    WAITING_FOR_TURN = "waiting_for_action"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MotionObservation:
    blink_detected: bool
    turn_direction: TurnDirection | None
    observed_at_seconds: float


@dataclass(slots=True)
class LivenessChallenge:
    required_turn: TurnDirection
    started_at_seconds: float
    timeout_seconds: float = 15.0
    require_head_action: bool = True
    status: ChallengeStatus = ChallengeStatus.WAITING_FOR_BLINK
    failure_reason: str | None = None

    @classmethod
    def create(
        cls,
        started_at_seconds: float,
        timeout_seconds: float = 15.0,
        require_head_action: bool = True,
    ) -> "LivenessChallenge":
        return cls(
            required_turn=random.choice(list(TurnDirection)),
            started_at_seconds=started_at_seconds,
            timeout_seconds=timeout_seconds,
            require_head_action=require_head_action,
        )

    def observe(self, observation: MotionObservation) -> ChallengeStatus:
        if self.status in {ChallengeStatus.PASSED, ChallengeStatus.FAILED}:
            return self.status
        if observation.observed_at_seconds - self.started_at_seconds > self.timeout_seconds:
            waiting_for = self.status
            self.status = ChallengeStatus.FAILED
            self.failure_reason = (
                "blink_timeout"
                if waiting_for == ChallengeStatus.WAITING_FOR_BLINK
                else "action_timeout"
            )
            return self.status
        if self.status == ChallengeStatus.WAITING_FOR_BLINK and observation.blink_detected:
            self.status = (
                ChallengeStatus.WAITING_FOR_ACTION
                if self.require_head_action
                else ChallengeStatus.PASSED
            )
            return self.status
        if (
            self.status == ChallengeStatus.WAITING_FOR_ACTION
            and observation.turn_direction == self.required_turn
        ):
            self.status = ChallengeStatus.PASSED
        return self.status
