"""
Unit tests for the code-based evaluator and the LLM-judge validation math.

These cover the two pieces the README's "Verification status" table calls
unit-tested:
  * the groundedness code evaluator (src/evaluators/code_evaluator.py), and
  * the judge-vs-human agreement math + deterministic stub judge that backs the
    rubric-judge validation (src/evaluators/llm_judge.py).

All dependencies here are pure stdlib: code_evaluator imports only `dataclasses`,
and llm_judge imports OpenAI lazily inside `openai_judge`, so the offline stub
judge and the agreement metrics run with no network and no API key.

Run:  pytest -q
"""

import math

from src.evaluators.code_evaluator import evaluate_groundedness
from src.evaluators import llm_judge


# --------------------------------------------------------------------------- #
# Groundedness code evaluator
# --------------------------------------------------------------------------- #
def test_groundedness_grounded_short_answer():
    out = "Strands emits OpenTelemetry spans that Arize ingests via OpenInference."
    r = evaluate_groundedness(out)
    assert r.label == "grounded"
    assert r.score == 1.0


def test_groundedness_ungrounded_when_no_markers():
    r = evaluate_groundedness("It just works, trust me.")
    assert r.label == "ungrounded"
    assert r.score == 0.0


def test_groundedness_empty_answer():
    r = evaluate_groundedness("")
    assert r.label == "ungrounded"
    assert r.explanation == "Empty answer."


def test_groundedness_breaks_length_contract():
    # Cites a partner concept but runs well past the 3-sentence contract.
    long_answer = "Arize is great. " * 6
    r = evaluate_groundedness(long_answer, max_sentences=3)
    assert r.label == "ungrounded"
    assert "sentence" in r.explanation.lower()


# --------------------------------------------------------------------------- #
# Cohen's kappa
# --------------------------------------------------------------------------- #
def test_cohens_kappa_perfect_agreement():
    bits = [1, 0, 1, 1, 0]
    assert llm_judge.cohens_kappa(bits, bits) == 1.0


def test_cohens_kappa_chance_agreement_is_zero():
    # po == pe here, so kappa collapses to 0.0.
    judge = [1, 1, 0, 0]
    human = [1, 0, 1, 0]
    assert math.isclose(llm_judge.cohens_kappa(judge, human), 0.0, abs_tol=1e-9)


def test_cohens_kappa_empty_input():
    assert llm_judge.cohens_kappa([], []) == 0.0


# --------------------------------------------------------------------------- #
# Precision / recall / F1 helper
# --------------------------------------------------------------------------- #
def test_prf_perfect_scores():
    judge = [1, 1, 0, 0]
    human = [1, 1, 0, 0]
    prf = llm_judge._prf(judge, human)
    assert prf["accuracy"] == 1.0
    assert prf["precision"] == 1.0
    assert prf["recall"] == 1.0
    assert prf["f1"] == 1.0


# --------------------------------------------------------------------------- #
# Deterministic stub judge (rubric criterion)
# --------------------------------------------------------------------------- #
def test_stub_judge_rubric_fails_when_uncited():
    prompt = (
        "RUBRIC: ... User message: How does Arize work with AWS?\n"
        "Assistant answer: Bedrock and Phoenix work together nicely."
    )
    label, _ = llm_judge.stub_judge(prompt)
    assert label == "fail"  # grounded but missing a bracketed [source] citation


def test_stub_judge_rubric_passes_when_grounded_and_cited():
    prompt = (
        "RUBRIC: ... User message: How does Arize work with AWS?\n"
        "Assistant answer: Bedrock traces flow to Phoenix via OpenInference [aws_overview]."
    )
    label, _ = llm_judge.stub_judge(prompt)
    assert label == "pass"


# --------------------------------------------------------------------------- #
# End-to-end offline validation report
# --------------------------------------------------------------------------- #
def test_run_validation_offline_runs_and_reports():
    report = llm_judge.run_validation(offline=True)
    assert "VALIDATION" in report
    assert "accuracy" in report
    assert "cohen_kappa" in report
