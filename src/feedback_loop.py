"""
feedback_loop.py
================

Step 6: a lightweight, repeatable automated feedback loop.

This adapts the donor prompt_learning.py idea (English-critique -> instruction
patch) into an operational loop you can run on a schedule:

  1. PULL recent traces from local Phoenix (or fall back to the harness's
     experiments/query_records.json when Phoenix is not reachable).
  2. RUN the evals (frustration, tool-selection, rubric quality) over them.
  3. DETECT failure patterns (clusters of the same eval failing, KB tool errors,
     frustration spikes).
  4. EMIT a flag / report to experiments/feedback_report.md, and a STUB that
     drafts an improved system-prompt instruction and shows where a PR would be
     opened (the human-in-the-loop approval gate from Prompt Learning).

This is intentionally NOT a fully autonomous prompt rewriter. The donor demo
proved the loop can edit a fenced <INSTRUCTIONS> block from an English critique;
here we keep the human approval gate explicit, which is the responsible-AI story
for the panel.

Run (offline stub judge, uses harness records if present):
    python -m src.feedback_loop --offline

Run against live Phoenix traces with the OpenAI judge:
    phoenix serve
    export OPENAI_API_KEY=...
    python -m src.feedback_loop
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.evaluators.llm_judge import (
    eval_user_frustration,
    eval_tool_selection,
    eval_rubric_quality,
    openai_judge,
    stub_judge,
)

EXPORT_DIR = Path(__file__).resolve().parent.parent / "experiments"
REPORT_PATH = EXPORT_DIR / "feedback_report.md"

# Failure-rate thresholds that trip a flag.
RUBRIC_FAIL_THRESHOLD = 0.30      # >30% of answers failing the rubric
FRUSTRATION_THRESHOLD = 0.20      # >20% of turns reading as frustrated
TOOL_MISSELECT_THRESHOLD = 0.20   # >20% wrong tool decisions


# --------------------------------------------------------------------------- #
# Trace sourcing
# --------------------------------------------------------------------------- #
def _pull_from_phoenix(limit: int = 50) -> List[Dict]:
    """Pull recent root spans from Phoenix as {query, answer, tool_invoked}.

    Returns [] if Phoenix is unreachable so the caller can fall back to the
    harness records. Defensive about column names across Phoenix versions.
    """
    project = os.environ.get("ARIZE_PROJECT_NAME", "strands-agentcore-cookbook-local")
    try:
        import phoenix as px

        client = px.Client(endpoint=os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006"))
        spans = client.get_spans_dataframe(project_name=project)
        if spans is None or len(spans) == 0:
            return []
        in_col = next((c for c in spans.columns if c.endswith("input.value")), None)
        out_col = next((c for c in spans.columns if c.endswith("output.value")), None)
        if in_col is None:
            return []
        rows: List[Dict] = []
        for _, row in spans.head(limit).iterrows():
            q = str(row.get(in_col, "") or "")
            a = str(row.get(out_col, "") or "") if out_col else ""
            if not q:
                continue
            # Heuristic: did a retrieval span exist for this query? We approximate
            # by checking the span name column when present.
            name = str(row.get("name", "")).lower()
            rows.append({
                "query": q,
                "answer": a,
                "tool_invoked": "retrieve" in name,
            })
        return rows
    except Exception as exc:  # noqa: BLE001
        print(f"  [pull] Phoenix not reachable ({exc}); using harness records.")
        return []


def _pull_from_records() -> List[Dict]:
    """Fall back to experiments/query_records.json written by run_experiments."""
    path = EXPORT_DIR / "query_records.json"
    if not path.exists():
        return []
    recs = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"query": r["prompt"], "answer": r.get("answer", ""),
         "tool_invoked": bool(r.get("tool_invoked"))}
        for r in recs
    ]


# --------------------------------------------------------------------------- #
# Run evals + detect patterns
# --------------------------------------------------------------------------- #
def _evaluate(rows: List[Dict], judge_fn) -> List[Dict]:
    results = []
    for r in rows:
        frust_label, frust_expl = eval_user_frustration(r["query"], r["answer"], judge_fn)
        tool_label, tool_expl = eval_tool_selection(r["query"], r["tool_invoked"], judge_fn)
        rub_label, rub_expl = eval_rubric_quality(r["query"], r["answer"], judge_fn)
        rub_label = "pass" if rub_label.startswith("pass") else "fail"
        results.append({
            **r,
            "frustration": frust_label,
            "frustration_explanation": frust_expl,
            "tool_selection": tool_label,
            "tool_selection_explanation": tool_expl,
            "rubric": rub_label,
            "rubric_explanation": rub_expl,
        })
    return results


def _detect_patterns(results: List[Dict]) -> Dict:
    n = max(len(results), 1)
    rubric_fails = [r for r in results if r["rubric"] == "fail"]
    frustrated = [r for r in results if r["frustration"] == "frustrated"]
    mis_tool = [r for r in results if r["tool_selection"] == "incorrect"]

    # Cluster the rubric-failure critiques into a crude theme histogram.
    theme = Counter()
    for r in rubric_fails:
        e = r["rubric_explanation"].lower()
        if "cit" in e or "source" in e:           # citation / cite / cited
            theme["missing_citation"] += 1
        elif "concise" in e or "sentence" in e or "long" in e:
            theme["too_long"] += 1
        elif "topic" in e or "address" in e or "no-answer" in e:
            theme["off_topic"] += 1
        elif "ground" in e or "generic" in e or "filler" in e:
            theme["ungrounded"] += 1
        else:
            theme["other"] += 1

    flags = []
    if len(rubric_fails) / n > RUBRIC_FAIL_THRESHOLD:
        flags.append(f"RUBRIC failure rate {len(rubric_fails)}/{n} exceeds "
                     f"{RUBRIC_FAIL_THRESHOLD:.0%}")
    if len(frustrated) / n > FRUSTRATION_THRESHOLD:
        flags.append(f"FRUSTRATION rate {len(frustrated)}/{n} exceeds "
                     f"{FRUSTRATION_THRESHOLD:.0%}")
    if len(mis_tool) / n > TOOL_MISSELECT_THRESHOLD:
        flags.append(f"TOOL-SELECTION miss rate {len(mis_tool)}/{n} exceeds "
                     f"{TOOL_MISSELECT_THRESHOLD:.0%}")

    return {
        "n": n,
        "rubric_fails": rubric_fails,
        "frustrated": frustrated,
        "mis_tool": mis_tool,
        "theme": theme,
        "flags": flags,
    }


def _draft_prompt_patch(patterns: Dict) -> str:
    """STUB: turn the dominant failure theme into ONE proposed instruction.

    This mirrors the donor meta-prompt step but stays a stub: it proposes the
    English instruction and where the PR would go, leaving the human to approve.
    """
    theme = patterns["theme"]
    if not theme:
        return "_No dominant failure theme; no prompt change proposed._"
    top, _count = theme.most_common(1)[0]
    proposals = {
        "missing_citation": "Always cite the source doc in brackets, e.g. [aws_bedrock_overview.md].",
        "too_long": "Hard-cap every answer at three sentences; drop secondary co-sell detail.",
        "off_topic": "Restate the named partner in the first sentence before answering.",
        "ungrounded": "Answer only from search_partner_docs output; if empty, say you have no documented answer.",
        "other": "Tighten answers to the rubric: grounded, on-topic, cited, concise.",
    }
    instruction = proposals.get(top, proposals["other"])
    return (
        f"Dominant failure theme: **{top}**.\n\n"
        f"Proposed new <INSTRUCTIONS> line (HUMAN APPROVAL REQUIRED):\n"
        f"> {instruction}\n\n"
        f"PR stub: open a branch `feedback/{top}-fix`, append the line to the "
        f"fenced <INSTRUCTIONS> block in src/local_agent.py SYSTEM_PROMPT, re-run "
        f"`python -m src.run_experiments` and `python -m src.evaluators.llm_judge`, "
        f"and attach the before/after metrics to the PR description."
    )


def _write_report(patterns: Dict, results: List[Dict]) -> str:
    lines = []
    lines.append("# Automated Feedback Loop Report\n")
    lines.append(f"- traces evaluated: **{patterns['n']}**")
    lines.append(f"- rubric failures: {len(patterns['rubric_fails'])}")
    lines.append(f"- frustrated turns: {len(patterns['frustrated'])}")
    lines.append(f"- tool misselections: {len(patterns['mis_tool'])}\n")

    lines.append("## Flags")
    if patterns["flags"]:
        for f in patterns["flags"]:
            lines.append(f"- :triangular_flag_on_post: {f}")
    else:
        lines.append("- none: all eval rates within threshold.")
    lines.append("")

    lines.append("## Failure-theme histogram")
    if patterns["theme"]:
        for theme, count in patterns["theme"].most_common():
            lines.append(f"- {theme}: {count}")
    else:
        lines.append("- (no rubric failures)")
    lines.append("")

    lines.append("## Proposed prompt patch (stub, human-in-the-loop)")
    lines.append(_draft_prompt_patch(patterns))
    lines.append("")

    lines.append("## Sample failing traces")
    for r in patterns["rubric_fails"][:5]:
        lines.append(f"- **Q:** {r['query'][:80]}")
        lines.append(f"  - rubric: {r['rubric']} ({r['rubric_explanation'][:80]})")
    return "\n".join(lines)


def main() -> None:
    offline = "--offline" in sys.argv
    if not offline and not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; using --offline stub judge.\n")
        offline = True
    judge_fn = stub_judge if offline else openai_judge

    EXPORT_DIR.mkdir(exist_ok=True)

    print("Pulling recent traces...")
    rows = _pull_from_phoenix()
    if not rows:
        rows = _pull_from_records()
    if not rows:
        print("No traces found. Run `python -m src.run_experiments` first "
              "(it writes experiments/query_records.json).")
        return
    print(f"  got {len(rows)} traces.")

    print("Running evals...")
    results = _evaluate(rows, judge_fn)
    patterns = _detect_patterns(results)

    report = _write_report(patterns, results)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")

    print("\n" + report)
    print(f"\nSaved -> {REPORT_PATH}")
    if patterns["flags"]:
        print("\nFLAGS RAISED: a prompt patch was proposed (see report).")
    else:
        print("\nNo flags: system within eval thresholds.")


if __name__ == "__main__":
    main()
