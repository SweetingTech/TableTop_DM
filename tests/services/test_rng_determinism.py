import importlib
import pytest

pytestmark = pytest.mark.unit


def test_seeded_rng_produces_repeatable_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTDM_RNG_SEED", "12345")
    import services.mechanics.dice as dice

    importlib.reload(dice)
    first = [dice.roll_d20().total for _ in range(5)]

    importlib.reload(dice)
    second = [dice.roll_d20().total for _ in range(5)]

    assert first == second


def test_unseeded_rng_does_not_require_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTDM_RNG_SEED", raising=False)
    import services.mechanics.dice as dice

    importlib.reload(dice)
    value = dice.roll_d20().total
    assert 1 <= value <= 20


def test_invalid_seed_falls_back_to_unseeded_rng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTDM_RNG_SEED", "not-a-number")
    import services.mechanics.dice as dice

    importlib.reload(dice)
    assert dice._SEEDED_RNG is None
    value = dice.roll_d20().total
    assert 1 <= value <= 20
