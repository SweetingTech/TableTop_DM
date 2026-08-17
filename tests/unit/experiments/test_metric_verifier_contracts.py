from __future__ import annotations

import uuid

import pytest

from experiments.metrics import MetricEvaluator
from experiments.models import MetricContract, MetricSpec
from experiments.verifiers import VerifierRegistry
from kernel.contracts import VerifierFact

pytestmark = pytest.mark.unit


def _fact(fact_type: str, value: bool | int | float | str) -> VerifierFact:
    return VerifierFact(
        fact_type=fact_type,
        value=value,
        evidence_event_ids=(uuid.uuid5(uuid.NAMESPACE_URL, f"evidence:{fact_type}:{value}"),),
        verifier_version="test-verifier-1.0.0",
    )


def test_metric_contract_supports_every_deterministic_reduction_and_defaults():
    facts = (
        _fact("number", 2),
        _fact("number", 4),
        _fact("flag", False),
        _fact("flag", True),
        _fact("label", "ready"),
    )
    contract = MetricContract(
        metrics=(
            MetricSpec(name="sum", fact_type="number", reduction="SUM"),
            MetricSpec(name="mean", fact_type="number", reduction="MEAN"),
            MetricSpec(name="count", fact_type="number", reduction="COUNT"),
            MetricSpec(name="any", fact_type="flag", reduction="ANY"),
            MetricSpec(name="all", fact_type="flag", reduction="ALL"),
            MetricSpec(name="value", fact_type="label", reduction="VALUE"),
            MetricSpec(name="fallback", fact_type="missing", default=9),
        )
    )

    assert MetricEvaluator().evaluate(facts, contract) == {
        "sum": 6.0,
        "mean": 3.0,
        "count": 2,
        "any": True,
        "all": False,
        "value": "ready",
        "fallback": 9,
    }


def test_metric_contract_rejects_ambiguous_or_missing_values():
    evaluator = MetricEvaluator()
    duplicate = MetricContract(
        metrics=(
            MetricSpec(name="same", fact_type="a", default=0),
            MetricSpec(name="same", fact_type="b", default=0),
        )
    )
    with pytest.raises(ValueError, match="unique"):
        evaluator.evaluate((), duplicate)
    with pytest.raises(ValueError, match="no absent facts"):
        evaluator.evaluate(
            (),
            MetricContract(metrics=(MetricSpec(name="missing", fact_type="absent"),)),
        )
    with pytest.raises(ValueError, match="expected one fact"):
        evaluator.evaluate(
            (_fact("one", 1), _fact("one", 2)),
            MetricContract(metrics=(MetricSpec(name="one", fact_type="one"),)),
        )


def test_verifier_registry_resolves_explicit_versions_and_rejects_bad_contracts():
    registry = VerifierRegistry()
    old = registry.register("score", lambda _events, _state: (_fact("score", 1),))
    latest = registry.register(
        "score",
        lambda _events, _state: (_fact("score", 2),),
        version="2.0.0",
    )

    assert old == "score@1.0.0"
    assert latest == "score@2.0.0"
    assert registry.verify((old,), (), {})[0].value == 1
    assert registry.verify(("score",), (), {})[0].value == 2
    with pytest.raises(ValueError, match="already registered"):
        registry.register("score", lambda _events, _state: (), version="2.0.0")
    with pytest.raises(ValueError, match="Unknown verifier"):
        registry.verify(("missing",), (), {})

    bad = VerifierRegistry()
    bad.register("bad", lambda _events, _state: ("persuasive prose",))  # type: ignore[return-value]
    with pytest.raises(TypeError, match="non-normalized fact"):
        bad.verify(("bad",), (), {})
