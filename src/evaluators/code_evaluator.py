"""
code_evaluator.py
=================

A code-based evaluator -- the same KIND of artifact Alyx drafts for you in
Arize AX when you ask it to "turn this failure mode into an eval." Keeping a
hand-written one alongside it makes the comparison concrete: the evaluator you
wrote versus one generated from your traces, and where they agree or differ.

This evaluator scores whether the Partner Solutions Assistant's answer is
GROUNDED: did it actually cite a doc snippet, and did it stay within the length
contract? It returns the (label, score, explanation) shape Arize expects from a
code evaluator, so it can be registered as an online eval or run offline over a
dataset of spans.
"""

from dataclasses import dataclass


# Phrases that signal the answer leaned on the retrieval tool output rather than
# free-associating. In a real eval you would check the tool-call span directly.
_GROUNDING_MARKERS = (
    "agentcore",
    "strands",
    "arize",
    "opentelemetry",
    "openinference",
    "cross-region",
)


@dataclass
class EvalResult:
    label: str          # "grounded" | "ungrounded"
    score: float        # 1.0 | 0.0
    explanation: str


def evaluate_groundedness(output: str, max_sentences: int = 3) -> EvalResult:
    """Return a grounding verdict for one agent answer.

    Args:
        output: The agent's final answer text.
        max_sentences: Length contract from the system prompt.
    """
    text = (output or "").strip()
    if not text:
        return EvalResult("ungrounded", 0.0, "Empty answer.")

    sentence_count = sum(text.count(p) for p in (".", "!", "?")) or 1
    cited = any(marker in text.lower() for marker in _GROUNDING_MARKERS)

    if not cited:
        return EvalResult(
            "ungrounded",
            0.0,
            "Answer cites none of the partner doc concepts; likely not grounded "
            "in the retrieval tool output.",
        )
    if sentence_count > max_sentences:
        return EvalResult(
            "ungrounded",
            0.0,
            f"Answer cited docs but ran to ~{sentence_count} sentences, breaking "
            f"the {max_sentences}-sentence contract.",
        )
    return EvalResult(
        "grounded",
        1.0,
        f"Answer cited partner doc concepts and respected the "
        f"{max_sentences}-sentence contract.",
    )


# Minimal self-test so the file is runnable on its own:
#   python -m src.evaluators.code_evaluator
if __name__ == "__main__":
    good = "Strands emits OpenTelemetry spans that Arize ingests via OpenInference."
    bad = "It just works, trust me."
    for sample in (good, bad):
        r = evaluate_groundedness(sample)
        print(f"{r.label:11s} score={r.score} :: {sample}\n            -> {r.explanation}")
