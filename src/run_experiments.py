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

from src.instrumentation import init_tracing, record_retrieval_span
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
]


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
        "tool_invoked": False,
        "tool_error": False,
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
    try:
        answer = str(agent(prompt))
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
    try:
        import phoenix as px

        client = px.Client(endpoint=os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006"))
        spans = client.get_spans_dataframe(project_name=project)
        if spans is None or len(spans) == 0:
            print("  [export] Phoenix returned no spans yet (still flushing?). Skipped.")
            return False
        spans.to_parquet(EXPORT_DIR / "spans.parquet")
        spans.to_csv(EXPORT_DIR / "spans.csv")
        print(f"  [export] wrote {len(spans)} spans -> "
              f"{EXPORT_DIR/'spans.parquet'} (+ .csv)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [export] span export skipped (Phoenix not reachable?): {exc}")
        return False


def _metrics_report(records: List[Dict]) -> str:
    """Compute the metrics report string from the per-query records."""
    n = len(records)
    latencies = sorted(r["latency_ms"] for r in records)
    p50 = statistics.median(latencies) if latencies else 0.0
    # Nearest-rank p95.
    p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))] if latencies else 0.0

    total_tokens = sum(r["approx_tokens"] for r in records)
    tool_calls = sum(1 for r in records if r["tool_invoked"])
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
    lines.append(f"tool-invocation rate   : {tool_calls}/{n} = {tool_calls/n:.0%}")
    lines.append(f"failure rate           : {failures}/{n} = {failures/n:.0%}")
    lines.append(f"total approx tokens    : {total_tokens}")
    lines.append(f"est cost @ ${cost_per_1m}/1M : ${est_cost:.6f}")
    lines.append("")
    lines.append("per-query:")
    lines.append(f"  {'id':16s} {'kind':16s} {'lat_ms':>8s} {'tok':>6s} tool err")
    for r in records:
        lines.append(
            f"  {r['id']:16s} {r['kind']:16s} {r['latency_ms']:8.1f} "
            f"{r['approx_tokens']:6d} {str(r['tool_invoked']):5s} {str(r['tool_error'])}"
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
