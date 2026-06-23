"""
feedback_loop.py
================

Step 6: a lightweight, repeatable automated feedback loop.

This implements a prompt-learning idea (English-critique -> instruction
patch) as an operational loop you can run on a schedule:

  1. PULL recent traces from local Phoenix (or fall back to the harness's
     experiments/query_records.json when Phoenix is not reachable).
  2. RUN the evals (frustration, tool-selection, rubric quality) over them.
  3. DETECT failure patterns (clusters of the same eval failing, KB tool errors,
     frustration spikes).
  4. EMIT a flag / report to experiments/feedback_report.md, and a STUB that
     drafts an improved system-prompt instruction and shows where a PR would be
     opened (the human-in-the-loop approval gate from Prompt Learning).

This is intentionally NOT a fully autonomous prompt rewriter. The loop can
edit a fenced <INSTRUCTIONS> block from an English critique; here we keep the
human approval gate explicit, which is the responsible-AI posture for a
partner-facing quality loop.

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
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006")
    try:
        # Newer Phoenix: phoenix.client.Client().spans.get_spans_dataframe(...);
        # older releases used phoenix.Client().get_spans_dataframe(...). Try both.
        try:
            from phoenix.client import Client

            spans = Client(base_url=endpoint).spans.get_spans_dataframe(project_name=project)
        except Exception:
            import phoenix as px

            spans = px.Client(endpoint=endpoint).get_spans_dataframe(project_name=project)
        if spans is None or len(spans) == 0:
            return []
        in_col = next((c for c in spans.columns if c.endswith("input.value")), None)
        out_col = next((c for c in spans.columns if c.endswith("output.value")), None)
        kind_col = "span_kind" if "span_kind" in spans.columns else None
        trace_col = next((c for c in spans.columns if c.endswith("trace_id")), None)
        span_col = ("context.span_id" if "context.span_id" in spans.columns
                    else next((c for c in spans.columns if c.endswith("span_id")), None))
        if in_col is None or kind_col is None:
            return []

        # One clean row per USER TURN = the AGENT (invoke_agent) spans, whose
        # input.value is the user prompt and output.value the final answer. The
        # LLM/CHAIN sub-spans carry raw chat-message JSON, which is not a query,
        # so iterating every span (the old behaviour) polluted the eval set.
        agent = spans[spans[kind_col] == "AGENT"].copy()
        if "start_time" in agent.columns:
            agent = agent.sort_values("start_time", ascending=False)  # most recent first

        # Partner-tool use is read per-trace: did this turn's trace contain a
        # TOOL span for the partner-native `search_partner_docs` specifically
        # (NOT just any tool such as check_model_access)? That is the decision
        # the partner-SA tool-selection eval actually cares about.
        toolname_col = next((c for c in spans.columns if c.endswith("tool.name")), None)
        tool_traces = set()
        if trace_col:
            tool_spans = spans[spans[kind_col] == "TOOL"]
            if toolname_col is not None:
                tool_spans = tool_spans[tool_spans[toolname_col] == "search_partner_docs"]
            tool_traces = set(tool_spans[trace_col].dropna())

        rows: List[Dict] = []
        seen = set()
        for _, row in agent.iterrows():
            q = str(row.get(in_col, "") or "").strip()
            if not q or q == "nan" or q in seen:
                continue
            seen.add(q)  # dedupe repeated prompts across multiple runs
            a = str(row.get(out_col, "") or "") if out_col else ""
            rows.append({
                "query": q,
                "answer": a,
                "tool_invoked": bool(trace_col and row.get(trace_col) in tool_traces),
                "span_id": (str(row.get(span_col)) if span_col else None),
            })
            if len(rows) >= limit:
                break
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
         # Partner-native tool specifically, not just any tool the agent ran.
         "tool_invoked": "search_partner_docs" in (r.get("agent_tools_used") or [])}
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

    This is the meta-prompt step, kept as a stub: it proposes the English
    instruction and where the PR would go, leaving the human to approve.
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


def _log_annotations_to_phoenix(results: List[Dict]) -> None:
    """Step 5.1: attach the three eval labels back onto their Phoenix spans as
    annotations, so they are filterable in the Phoenix UI. Best-effort and needs
    span_id, which only the live-Phoenix pull provides (not the records fallback).
    """
    rows = [r for r in results if r.get("span_id")]
    if not rows:
        print("  [annotate] no span_ids (records fallback) -> skipped span annotation.")
        return
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006")
    try:
        import pandas as pd
        from phoenix.client import Client

        client = Client(base_url=endpoint)
        specs = [
            ("user_frustration", "frustration", "frustration_explanation"),
            ("partner_tool_selection", "tool_selection", "tool_selection_explanation"),
            ("partner_answer_quality", "rubric", "rubric_explanation"),
        ]
        for ann_name, label_key, expl_key in specs:
            df = pd.DataFrame(
                {
                    "span_id": [r["span_id"] for r in rows],
                    "label": [str(r.get(label_key, "")) for r in rows],
                    "explanation": [str(r.get(expl_key, "")) for r in rows],
                }
            ).set_index("span_id")
            client.spans.log_span_annotations_dataframe(
                dataframe=df, annotation_name=ann_name, annotator_kind="LLM",
            )
        print(f"  [annotate] logged user_frustration / partner_tool_selection / "
              f"partner_answer_quality onto {len(rows)} spans in Phoenix.")
    except Exception as exc:  # noqa: BLE001
        print(f"  [annotate] span annotation skipped: {exc}")


def _create_frustrated_dataset(results: List[Dict]) -> None:
    """Step 5.1: filter the frustrated interactions and register them as a
    Phoenix dataset (a regression set the fix workflow can target)."""
    frustrated = [r for r in results if r.get("frustration") == "frustrated"]
    if not frustrated:
        print("  [dataset] no frustrated interactions detected -> dataset not created.")
        return
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006")
    try:
        import time

        import pandas as pd
        from phoenix.client import Client

        client = Client(base_url=endpoint)
        df = pd.DataFrame(
            [
                {
                    "query": r["query"],
                    "answer": r.get("answer", ""),
                    "frustration_explanation": r.get("frustration_explanation", ""),
                }
                for r in frustrated
            ]
        )
        name = f"frustrated-interactions-{time.strftime('%Y%m%d-%H%M%S')}"
        client.datasets.create_dataset(
            name=name,
            dataframe=df,
            input_keys=["query"],
            output_keys=["answer"],
            metadata_keys=["frustration_explanation"],
            dataset_description="Turns flagged frustrated by the user-frustration eval.",
        )
        print(f"  [dataset] created Phoenix dataset '{name}' with "
              f"{len(frustrated)} frustrated example(s).")
    except Exception as exc:  # noqa: BLE001
        print(f"  [dataset] frustrated-interactions dataset skipped: {exc}")


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

    # Step 5.1: attach eval labels onto the Phoenix spans and build a dataset of
    # the frustrated interactions (both no-ops gracefully on the records fallback).
    _log_annotations_to_phoenix(results)
    _create_frustrated_dataset(results)

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
