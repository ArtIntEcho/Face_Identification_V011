import pytest

from face_access.matching import encode_embedding, find_best_candidate, find_best_match


def test_best_match_uses_cosine_similarity_and_threshold() -> None:
    templates = [
        ("A", encode_embedding([1.0, 0.0, 0.0])),
        ("B", encode_embedding([0.0, 1.0, 0.0])),
    ]

    accepted = find_best_match([0.9, 0.1, 0.0], templates, threshold=0.9)
    rejected = find_best_match([0.7, 0.7, 0.0], templates, threshold=0.9)

    assert accepted is not None
    assert accepted.person_id == "A"
    assert accepted.similarity == pytest.approx(0.99388, abs=0.0001)
    assert rejected is None


def test_zero_embedding_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        encode_embedding([0.0, 0.0])


def test_best_candidate_is_available_below_acceptance_threshold() -> None:
    templates = [("A", encode_embedding([1.0, 0.0, 0.0]))]

    candidate = find_best_candidate([0.7, 0.7, 0.0], templates)

    assert candidate is not None
    assert candidate.person_id == "A"
    assert candidate.similarity == pytest.approx(0.7071, abs=0.0001)