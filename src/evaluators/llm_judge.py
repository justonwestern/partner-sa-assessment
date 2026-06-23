"""
llm_judge.py
============

Step 5: three evals plus a custom LLM-as-judge with explicit rubric and
hand-label validation. The judge returns a LABEL plus a one-sentence
English EXPLANATION (the "English error term" the feedback loop consumes).

Evals implemented here:
  1. User Frustration       -> frustrated | not_frustrated
  2. Partner-Native
     Tool-Selection         -> correct | incorrect  (did the agent choose the
                               KB tool when it should have, and skip it when it
                               should not have)
  3. Custom rubric judge    -> pass | fail  against an explicit 4-criterion
     ("Partner Answer        rubric, with the rubric printed in the prompt
      Quality")

The code_evaluator.py groundedness check stays as the 4th (code) evaluator.

Validation: run_validation() scores a small hand-labeled set (see
eval_labeled_set.json) with the rubric judge and prints an agreement report:
accuracy, precision, recall, F1, and Cohen's kappa between judge and humans.

Judge backend: OpenAI (gpt-4o-mini). Reads OPENAI_API_KEY.
For an offline dry run (no API key), pass judge_fn=stub_judge to the eval funcs;
run_validation(offline=True) uses a deterministic keyword stub so the agreement
math is demonstrable without network.

Run the validation report:
    python -m src.evaluators.llm_judge                 # uses OpenAI
    python -m src.evaluators.llm_judge --offline       # deterministic stub
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

LABELED_SET_PATH = Path(__file__).resolve().parent / "eval_labeled_set.json"

# A judge is a function: (prompt_text) -> (label, explanation).
JudgeFn = Callable[[str], Tuple[str, str]]


# --------------------------------------------------------------------------- #
# Rubric prompts (the explicit rubric is the Step 5c requirement)
# --------------------------------------------------------------------------- #
FRUSTRATION_PROMPT = """You are grading whether a USER is likely FRUSTRATED based
on their message to a Partner Solutions Assistant.

User message: {query}
Assistant answer: {answer}

Signals of frustration: repetition ("again", "still"), all-caps, "this is
wrong", "that's not what I asked", short angry phrasing, or an answer that
clearly failed to address the question.

Respond in exactly two lines:
Line 1: one word, exactly one of: frustrated, not_frustrated
Line 2: one sentence explaining why.
"""

TOOL_SELECTION_PROMPT = """You are grading whether an agent made the CORRECT
tool-selection decision for a partner-integration assistant.

The agent has a knowledge-base tool `search_partner_docs` that should be used
when, and only when, the user asks how Arize integrates with, co-sells with, or
is observed alongside a specific partner (AWS, GCP, Databricks, NVIDIA,
Anthropic). It should NOT be used for model-id formatting questions or unrelated
questions.

User message: {query}
Did the agent invoke search_partner_docs? {tool_invoked}

Respond in exactly two lines:
Line 1: one word, exactly one of: correct, incorrect
Line 2: one sentence explaining why the tool decision was right or wrong.
"""

# The custom rubric judge: an explicit, enumerated rubric in the prompt.
RUBRIC_PROMPT = """You are grading the QUALITY of a Partner Solutions Assistant
answer against an explicit rubric. The answer PASSES only if it satisfies ALL
four criteria; otherwise it FAILS.

RUBRIC:
  1. Grounded: the answer reflects partner-doc content (names a real integration
     surface, co-sell motion, or product), not generic filler.
  2. On-topic: the answer addresses the specific partner the user asked about.
  3. Cited: the answer references a source (a bracketed [source] or a named doc).
  4. Concise: the answer is roughly three sentences or fewer.

User message: {query}
Assistant answer: {answer}

Respond in exactly two lines:
Line 1: one word, exactly one of: pass, fail
Line 2: one sentence naming which rubric criterion drove the verdict.
"""


# --------------------------------------------------------------------------- #
# Judge backends
# --------------------------------------------------------------------------- #
def _parse_two_line(text: str) -> Tuple[str, str]:
    """Parse the two-line judge format into (label, explanation)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    first = lines[0].lower() if lines else (text or "").lower()
    match = re.match(r"[a-z_]+", first)
    label = match.group(0) if match else first
    explanation = lines[1] if len(lines) > 1 else ""
    return label, explanation


def openai_judge(prompt: str, model: str = "gpt-4o-mini") -> Tuple[str, str]:
    """Call OpenAI and parse the two-line label+explanation."""
    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=80,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_two_line(resp.choices[0].message.content or "")


def stub_judge(prompt: str) -> Tuple[str, str]:
    """Deterministic offline judge so validation math runs without an API key.

    Crude keyword heuristics matched to each rubric prompt. Good enough to make
    the agreement report meaningful in a dry run; NOT a substitute for the LLM
    judge in the real demo.
    """
    p = prompt.lower()
    if "frustrated" in p and "not_frustrated" in p:
        # Inspect ONLY the user message, not the rubric text (which lists the
        # frustration example phrases and would trip every call otherwise).
        user_msg = ""
        if "user message:" in p:
            user_msg = p.split("user message:", 1)[1].split("assistant answer:", 1)[0]
        frustrated = any(s in user_msg for s in (
            "again", "still", "not what i asked", "this is wrong", "!!", "ugh",
        ))
        return ("frustrated" if frustrated else "not_frustrated", "stub: keyword heuristic")
    if "search_partner_docs" in p and "correct" in p and "incorrect" in p:
        # Look only at the user-message + the tool-invocation answer line.
        user_msg = ""
        if "user message:" in p:
            user_msg = p.split("user message:", 1)[1]
        invoked = "invoke search_partner_docs? true" in user_msg or "invoked? true" in user_msg
        partner = any(k in user_msg for k in (
            "aws", "bedrock", "gcp", "vertex", "databricks", "mlflow",
            "nvidia", "nemo", "anthropic", "claude",
        ))
        correct = invoked == partner
        return ("correct" if correct else "incorrect", "stub: invoked-vs-expected")
    # rubric judge: inspect ONLY the answer portion, not the rubric text (which
    # itself contains an example "[source]" citation and partner names).
    answer = ""
    if "assistant answer:" in p:
        answer = prompt.split("Assistant answer:", 1)[1].strip()
    answer_low = answer.lower()
    cited = "[" in answer  # a bracketed [source] in the answer itself
    grounded = any(k in answer_low for k in (
        "bedrock", "mlflow", "nemo", "vertex", "phoenix", "instrumentor",
        "openinference", "co-sell", "run id", "ax experiment",
    ))
    # Vague-filler signal: short generic boosterism with no specifics.
    filler = any(s in answer_low for s in (
        "always better", "lots of", "many things", "probably", "somehow",
        "i think", "great tool", "best results",
    ))
    too_long = answer.count(".") > 4  # rough >3-sentence proxy
    no_answer = "don't have a documented answer" in answer_low
    ok = grounded and cited and not filler and not too_long and not no_answer
    if not ok:
        why = ("missing citation" if not cited else
               "too long" if too_long else
               "ungrounded/filler" if (filler or not grounded) else
               "off-topic/no-answer")
        return ("fail", f"stub: {why}")
    return ("pass", "stub: grounded, cited, concise")


# --------------------------------------------------------------------------- #
# The three evals
# --------------------------------------------------------------------------- #
def eval_user_frustration(query: str, answer: str, judge_fn: JudgeFn) -> Tuple[str, str]:
    return judge_fn(FRUSTRATION_PROMPT.format(query=query, answer=answer))


def eval_tool_selection(query: str, tool_invoked: bool, judge_fn: JudgeFn) -> Tuple[str, str]:
    return judge_fn(
        TOOL_SELECTION_PROMPT.format(query=query, tool_invoked=str(tool_invoked))
    )


def eval_rubric_quality(query: str, answer: str, judge_fn: JudgeFn) -> Tuple[str, str]:
    return judge_fn(RUBRIC_PROMPT.format(query=query, answer=answer))


# --------------------------------------------------------------------------- #
# Hand-label validation + agreement metrics
# --------------------------------------------------------------------------- #
def _binary(label: str, positive: str) -> int:
    return 1 if label.strip().lower() == positive else 0


def cohens_kappa(judge: List[int], human: List[int]) -> float:
    """Cohen's kappa for two binary raters."""
    n = len(judge)
    if n == 0:
        return 0.0
    po = sum(1 for j, h in zip(judge, human) if j == h) / n
    pj1 = sum(judge) / n
    ph1 = sum(human) / n
    pe = pj1 * ph1 + (1 - pj1) * (1 - ph1)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def _prf(judge: List[int], human: List[int]) -> Dict[str, float]:
    """Accuracy, precision, recall, F1 with `pass`==1 as the positive class."""
    n = len(judge)
    tp = sum(1 for j, h in zip(judge, human) if j == 1 and h == 1)
    fp = sum(1 for j, h in zip(judge, human) if j == 1 and h == 0)
    fn = sum(1 for j, h in zip(judge, human) if j == 0 and h == 1)
    acc = sum(1 for j, h in zip(judge, human) if j == h) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"accuracy": acc, "precision": prec, "recall": rec, "f1": f1}


def run_validation(offline: bool = False) -> str:
    """Score the labeled set with the rubric judge and build an agreement report.

    The labeled set is a list of {query, answer, human_label} where human_label
    is "pass" | "fail" (the gold judgement of the rubric judge). We run the
    rubric judge, then compute accuracy / precision / recall / F1 / Cohen's kappa
    between judge and humans, treating "pass" as the positive class.
    """
    items = json.loads(LABELED_SET_PATH.read_text(encoding="utf-8"))
    judge_fn: JudgeFn = stub_judge if offline else openai_judge

    judge_bits: List[int] = []
    human_bits: List[int] = []
    rows = []
    for it in items:
        j_label, j_expl = eval_rubric_quality(it["query"], it["answer"], judge_fn)
        # Normalize the judge label to pass/fail.
        j_label = "pass" if j_label.startswith("pass") else "fail"
        judge_bits.append(_binary(j_label, "pass"))
        human_bits.append(_binary(it["human_label"], "pass"))
        rows.append((it["query"][:42], it["human_label"], j_label, j_expl[:50]))

    prf = _prf(judge_bits, human_bits)
    kappa = cohens_kappa(judge_bits, human_bits)

    out = []
    out.append("=" * 64)
    out.append("LLM-JUDGE VALIDATION (rubric 'Partner Answer Quality' vs humans)")
    out.append(f"backend: {'STUB (offline)' if offline else 'OpenAI gpt-4o-mini'}  "
               f"n={len(items)}")
    out.append("=" * 64)
    out.append(f"  {'query':42s} {'human':6s} {'judge':6s} note")
    for q, h, j, note in rows:
        flag = "" if h == j else "  <-- disagree"
        out.append(f"  {q:42s} {h:6s} {j:6s} {note}{flag}")
    out.append("-" * 64)
    out.append(f"accuracy : {prf['accuracy']:.2f}")
    out.append(f"precision: {prf['precision']:.2f}  (pass = positive class)")
    out.append(f"recall   : {prf['recall']:.2f}")
    out.append(f"f1       : {prf['f1']:.2f}")
    out.append(f"cohen_kappa: {kappa:.2f}  "
               f"({_kappa_strength(kappa)} agreement)")
    out.append("=" * 64)
    return "\n".join(out)


def _kappa_strength(k: float) -> str:
    if k < 0.0:
        return "worse-than-chance"
    if k < 0.20:
        return "slight"
    if k < 0.40:
        return "fair"
    if k < 0.60:
        return "moderate"
    if k < 0.80:
        return "substantial"
    return "almost-perfect"


if __name__ == "__main__":
    offline = "--offline" in sys.argv
    if not offline and not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; running --offline stub judge instead.\n")
        offline = True
    print(run_validation(offline=offline))
