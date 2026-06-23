"""
run_experiments.py
==================

Step 4: the tracing-experiment harness.

Runs a fixed query set (>= 10 queries) through the Partner Solutions Assistant:
  * 3 queries that exercise the Bedrock KB primitive (partner-integration asks),
  * 3 queries designed to surface failures (forced bad KB id, irrelevant query,
    forced tool error),
  * the remainder are normal traffic.

Then it:
  1. exports the resulting spans from local Phoenix to a pandas DataFrame and
     writes both CSV and Parquet (the parquet is the portable artifact),
  2. computes and prints a metrics report: p50 / p95 latency, total + per-query
     token cost, tool-invocation rate, and failure rate,
  3. saves the report to experiments/metrics_report.txt.

Run (mock fallback, no AWS needed):
    phoenix serve                          # http://localhost:6006
    MOCK_KB=true python -m src.run_experiments

Run against a real Bedrock KB:
    export KB_ID=...  AWS_REGION=us-east-1
    python -m src.run_experiments

NOTE: span EXPORT requires a running Phoenix at PHOENIX_ENDPOINT. If Phoenix is
unreachable, the harness still prints the in-process latency/tool/failure
metrics it collected directly (it does not depend on Phoenix for those), and
clearly labels the span-export step as skipped.
"""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path
from typing import Dict, List

from src.instrumentation import init_tracing, record_retrieval_span, get_tracer
from src.local_agent import build_agent
from src.tools import retrieve_partner_docs


EXPORT_DIR = Path(__file__).resolve().parent.parent / "experiments"
EXPORT_DIR.mkdir(exist_ok=True)


# --------------------------------------------------------------------------- #
# The query plan. `kind` drives both routing and the metrics breakdown.
# --------------------------------------------------------------------------- #
QUERY_PLAN: List[Dict] = [
    # ---- KB-exercising (partner integration) ----
    {"id": "kb-1", "kind": "kb", "prompt": "How does Arize integrate with AWS Bedrock for agentic RAG?"},
    {"id": "kb-2", "kind": "kb", "prompt": "Why would a Databricks customer add Arize on top of MLflow?"},
    {"id": "kb-3", "kind": "kb", "prompt": "What is the NVIDIA NeMo on-prem AI observability story?"},
    # ---- Normal traffic ----
    {"id": "ok-1", "kind": "normal", "prompt": "Does Phoenix trace Claude API calls from Anthropic?"},
    {"id": "ok-2", "kind": "normal", "prompt": "Which GCP Vertex artifacts flow back into Arize AX?"},
    {"id": "ok-3", "kind": "normal", "prompt": "Is us.anthropic.claude-sonnet-4-6 ready to invoke on Bedrock?"},
    {"id": "ok-4", "kind": "normal", "prompt": "What co-sell motions does Arize run with AWS?"},
    # ---- Failure-surfacing ----
    {"id": "fail-badkb", "kind": "fail_bad_kb", "prompt": "How does Arize integrate with AWS Bedrock?"},
    {"id": "fail-irrelevant", "kind": "fail_irrelevant", "prompt": "What is the best recipe for sourdough bread?"},
    {"id": "fail-toolerror", "kind": "fail_tool_error", "prompt": "Trigger a retrieval tool error on purpose."},
    # ---- Frustrated-user turns (drive the Step 5.1 user-frustration eval) ----
    {"id": "frustrated-1", "kind": "frustrated",
     "prompt": "This is the THIRD time I've asked and you STILL haven't answered: how does Arize integrate with AWS Bedrock?!"},
    {"id": "frustrated-2", "kind": "frustrated",
     "prompt": "That is NOT what I asked. Again: does Phoenix actually trace Claude calls, yes or no??"},
]


def _agent_tools_this_turn(agent, msgs_before: int) -> tuple:
    """Tools the AGENT actually invoked in THIS turn.

    NOTE: AgentResult.metrics.tool_metrics is CUMULATIVE across the agent's
    lifetime (the agent is reused across queries), so it cannot describe a single
    turn. Instead we scan the messages appended during this turn for Bedrock
    'toolUse' content blocks. Defensive: degrades to (0, []) on any Strands
    message-format change rather than crashing the harness.
    """
    names: List[str] = []
    try:
        msgs = getattr(agent, "messages", []) or []
        for m in msgs[msgs_before:]:
            content = m.get("content") if isinstance(m, dict) else None
            for blk in (content or []):
                if isinstance(blk, dict) and "toolUse" in blk:
                    nm = (blk.get("toolUse") or {}).get("name")
                    if nm:
                        names.append(str(nm))
    except Exception:  # noqa: BLE001 - telemetry must never break the harness
        pass
    return len(names), sorted(set(names))


def _run_one(agent, item: Dict) -> Dict:
    """Execute one planned query and collect per-query telemetry.

    Returns a record with latency, whether the KB tool ran, whether it errored,
    and a rough token estimate (chars/4 of the answer + retrieved context).
    """
    prompt = item["prompt"]
    kind = item["kind"]
    record = {
        "id": item["id"],
        "kind": kind,
        "prompt": prompt,
        "tool_invoked": False,        # harness-side: the forced retrieval ran
        "tool_error": False,
        "agent_tool_invoked": False,  # did the AGENT actually choose a tool?
        "agent_tool_calls": 0,
        "agent_tools_used": [],
        "answer": "",
        "latency_ms": 0.0,
        "approx_tokens": 0,
    }

    t0 = time.perf_counter()

    # Decide whether this query should exercise the KB primitive.
    exercises_kb = kind in ("kb", "fail_bad_kb", "fail_irrelevant", "fail_tool_error") or any(
        h in prompt.lower()
        for h in ("bedrock", "aws", "gcp", "vertex", "databricks", "mlflow",
                  "nvidia", "nemo", "anthropic", "claude", "partner")
    )

    # Wrap the whole query in ONE span so the manual RETRIEVER span and the
    # agent's LLM/tool spans share a single trace (matching local_agent.ask()),
    # instead of the retrieval span landing as a separate root trace.
    with get_tracer().start_as_current_span("agent_turn"):
        if exercises_kb:
            # Inject the failure conditions for the fail_* kinds.
            prev_kb = os.environ.get("KB_ID")
            prev_mock = os.environ.get("MOCK_KB")
            try:
                if kind == "fail_bad_kb":
                    # Force a real (non-mock) call against a bogus KB id so the
                    # bedrock retrieve raises and we capture a structured error.
                    os.environ["MOCK_KB"] = "false"
                    os.environ["KB_ID"] = "kb-DOES-NOT-EXIST-000000"
                elif kind == "fail_tool_error":
                    # Unset KB_ID on the real path -> structured "KB_ID not set" error.
                    os.environ["MOCK_KB"] = "false"
                    os.environ.pop("KB_ID", None)

                result = retrieve_partner_docs(prompt)
                record_retrieval_span(prompt, result)
                record["tool_invoked"] = True
                record["tool_error"] = result.is_error
                record["approx_tokens"] += sum(len(d.text) for d in result.documents) // 4
            finally:
                # Restore env so later queries are unaffected.
                if prev_kb is None:
                    os.environ.pop("KB_ID", None)
                else:
                    os.environ["KB_ID"] = prev_kb
                if prev_mock is None:
                    os.environ.pop("MOCK_KB", None)
                else:
                    os.environ["MOCK_KB"] = prev_mock

        # Always run the agent so there is an LLM span in the trace.
        # Snapshot the message count first so we can read THIS turn's tool calls.
        msgs_before = len(getattr(agent, "messages", []) or [])
        try:
            result_obj = agent(prompt)
            answer = str(result_obj)
            calls, names = _agent_tools_this_turn(agent, msgs_before)
            record["agent_tool_calls"] = calls
            record["agent_tools_used"] = names
            record["agent_tool_invoked"] = calls > 0
        except Exception as exc:  # noqa: BLE001 - record, do not crash the harness
            answer = f"AGENT_ERROR: {type(exc).__name__}: {exc}"
            record["tool_error"] = record["tool_error"] or True

    record["answer"] = answer
    record["approx_tokens"] += len(answer) // 4
    record["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    return record


def _export_spans_from_phoenix() -> bool:
    """Export Phoenix spans to CSV + Parquet. Returns True on success.

    Uses phoenix.Client().get_spans_dataframe(). Wrapped defensively because the
    span export is the only step that depends on a live Phoenix instance.
    """
    project = os.environ.get("ARIZE_PROJECT_NAME", "strands-agentcore-cookbook-local")
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006")

    # Phoenix's span-export API moved. Newer Phoenix exposes
    # phoenix.client.Client().spans.get_spans_dataframe(...); older releases used
    # the top-level phoenix.Client().get_spans_dataframe(...). Try new, then old.
    spans = None
    try:
        from phoenix.client import Client  # arize-phoenix-client

        spans = Client(base_url=endpoint).spans.get_spans_dataframe(project_name=project)
    except Exception as new_exc:  # noqa: BLE001
        try:
            import phoenix as px

            spans = px.Client(endpoint=endpoint).get_spans_dataframe(project_name=project)
        except Exception as old_exc:  # noqa: BLE001
            print(f"  [export] span export skipped (no usable Phoenix client): "
                  f"new={new_exc!r} old={old_exc!r}")
            return False

    try:
        if spans is None or len(spans) == 0:
            print("  [export] Phoenix returned no spans yet (still flushing?). Skipped.")
            return False
        spans.to_parquet(EXPORT_DIR / "spans.parquet")
        spans.to_csv(EXPORT_DIR / "spans.csv")
        print(f"  [export] wrote {len(spans)} spans -> "
              f"{EXPORT_DIR/'spans.parquet'} (+ .csv)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [export] span export failed during write: {exc}")
        return False


def _metrics_report(records: List[Dict]) -> str:
    """Compute the metrics report string from the per-query records."""
    n = len(records)
    latencies = sorted(r["latency_ms"] for r in records)
    p50 = statistics.median(latencies) if latencies else 0.0
    # Nearest-rank p95.
    p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else 0.0

    total_tokens = sum(r["approx_tokens"] for r in records)
    # The AGENT's real tool-selection rate (from AgentResult.metrics) is the
    # meaningful number. `tool_invoked` only means the harness forced a retrieval
    # for trace evidence, so it is reported separately below.
    agent_tool_n = sum(1 for r in records if r.get("agent_tool_invoked"))
    harness_retr_n = sum(1 for r in records if r["tool_invoked"])
    failures = sum(1 for r in records if r["tool_error"])

    # Rough cost model (illustrative): Claude Sonnet blended ~ $3 / 1M tokens.
    cost_per_1m = float(os.environ.get("COST_PER_1M_TOKENS", "3.0"))
    est_cost = total_tokens / 1_000_000.0 * cost_per_1m

    lines = []
    lines.append("=" * 60)
    lines.append("EXPERIMENT METRICS REPORT")
    lines.append("=" * 60)
    lines.append(f"queries run            : {n}")
    lines.append(f"latency p50 (ms)       : {p50:.1f}")
    lines.append(f"latency p95 (ms)       : {p95:.1f}")
    lines.append(f"agent tool-selection   : {agent_tool_n}/{n} = {agent_tool_n/n:.0%}  (agent actually invoked a tool)")
    lines.append(f"harness retrievals     : {harness_retr_n}/{n}  (forced for trace evidence)")
    lines.append(f"failure rate           : {failures}/{n} = {failures/n:.0%}")
    lines.append(f"total approx tokens    : {total_tokens}")
    lines.append(f"est cost @ ${cost_per_1m}/1M : ${est_cost:.6f}")
    lines.append("")
    lines.append("per-query:")
    lines.append(f"  {'id':16s} {'kind':16s} {'lat_ms':>8s} {'tok':>6s} {'agent_tool':>20s} err")
    for r in records:
        atool = ",".join(r.get("agent_tools_used") or []) or "-"
        lines.append(
            f"  {r['id']:16s} {r['kind']:16s} {r['latency_ms']:8.1f} "
            f"{r['approx_tokens']:6d} {atool:>20s} {str(r['tool_error'])}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> None:
    provider = init_tracing()
    agent = build_agent()

    print(f"Running {len(QUERY_PLAN)} queries through the agent...")
    records: List[Dict] = []
    for item in QUERY_PLAN:
        print(f"  -> [{item['kind']}] {item['prompt'][:60]}")
        records.append(_run_one(agent, item))

    # Flush spans so Phoenix has them before we export.
    provider.force_flush(timeout_millis=10000)
    time.sleep(2)

    print("\nExporting spans from Phoenix...")
    _export_spans_from_phoenix()

    report = _metrics_report(records)
    print("\n" + report)

    report_path = EXPORT_DIR / "metrics_report.txt"
    report_path.write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved report -> {report_path}")

    # Also persist the raw per-query records for the eval + feedback steps.
    import json
    (EXPORT_DIR / "query_records.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    print(f"Saved raw records -> {EXPORT_DIR/'query_records.json'}")

    provider.shutdown()


if __name__ == "__main__":
    main()
