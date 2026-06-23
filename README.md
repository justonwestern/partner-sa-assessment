# Partner SA Assessment: a Strands + Bedrock agent, observed in local Phoenix

A runnable "better-together" reference build for the Arize Partner Solutions
Architect assessment. A **Strands** agent on **Amazon Bedrock** (Claude Sonnet)
retrieves through a real **Bedrock Knowledge Base**, emits **OpenInference**
spans into **local Phoenix**, is scored by three evals plus an LLM-judge, and is
closed with a lightweight automated feedback loop. **Arize AX + Alyx** is the
documented enterprise upgrade path.

> Honest status: the code is import-clean and the offline paths (MOCK_KB, the
> stub-judge validation, the architecture diagram) are verified in this repo.
> The live paths (real Bedrock KB retrieval, AgentCore deploy, Phoenix span
> export) require your AWS account / a running `phoenix serve` and are labeled as
> such. See "What is real vs. needs a live run" below.

---

## Architecture (local default)

```
   user prompt
       |
       v
   Strands Agent  --calls-->  search_partner_docs  (REAL Bedrock Knowledge Base
   (Claude Sonnet               |                    retrieve(); Pydantic-validated
    on Bedrock)                 |                    RetrievalResult; observable
       |                        |                    failure channel)
       |  emits OTel spans      |
       |  (StrandsTelemetry)    +--> manual RETRIEVER span:
       v                             doc ids, scores, kb_id, tokens, latency_ms
   OpenInference processor (OTel -> OpenInference semantic conventions)
       |
       v
   OTLP/HTTP exporter ----> LOCAL PHOENIX (http://localhost:6006)
                                |
                                +--> run_experiments  (>=10 queries, metrics,
                                |                       span export to parquet/csv)
                                +--> evaluators        (frustration, tool-selection,
                                |                       rubric judge + validation,
                                |                       groundedness code eval)
                                +--> feedback_loop     (detect patterns -> flag ->
                                                        prompt-patch stub, human gate)

   Enterprise upgrade (TRACE_BACKEND=ax): the SAME OpenInference spans ship to
   Arize AX + Alyx (retention, RBAC, online evals) by swapping the exporter.

   Offline demo (MOCK_KB=true): the Bedrock KB is swapped for canned docs/*.md so
   the whole loop runs with no AWS account.
```

A rendered version is in `docs/architecture.png` (run `python docs/architecture.py`).

---

## Layout

```
strands-agentcore-arize-cookbook/
  src/
    instrumentation.py     # OTel -> OpenInference -> LOCAL PHOENIX (AX behind a flag)
                           #   + record_retrieval_span(): the manual RETRIEVER span
    tools.py               # REAL Bedrock KB tool, Pydantic RetrievalResult, MOCK_KB
    local_agent.py         # TRACK A: run the agent locally -> Phoenix
    run_experiments.py     # Step 4: >=10 queries, metrics, span export
    feedback_loop.py       # Step 6: scan traces -> evals -> flag -> prompt-patch stub
    evaluators/
      llm_judge.py         # Step 5: frustration, tool-selection, rubric judge + validation
      eval_labeled_set.json#   hand labels for judge-vs-human agreement
      code_evaluator.py    # groundedness code evaluator (4th eval)
  agentcore/
    strands_claude.py      # TRACK B: deployable AgentCore app (traces to AX or Phoenix)
    deploy.py              # configure + launch + invoke on AgentCore
    requirements.txt       # deps shipped INTO the container
  docs/
    architecture.py        # renders architecture.png (matplotlib)
    architecture.png       # the joint AWS + Arize reference diagram
    *_overview.md          # partner overview docs (canned MOCK_KB corpus)
  experiments/             # metrics_report.txt, spans.parquet/csv, feedback_report.md
  DESIGN_MEMO.md           # Step 7: partner choice + production-readiness plan
  requirements.txt         # laptop-side deps
  .env.example
```

---

## Setup

```bash
cd strands-agentcore-arize-cookbook
python3 -m venv .venv && source .venv/bin/activate     # Python 3.10-3.12
pip install -r requirements.txt
cp .env.example .env
# Fill in .env: KB_ID + AWS creds for the real KB, OPENAI_API_KEY for the judge.
# For an offline run, set MOCK_KB=true and skip the AWS / KB vars.
set -a && source .env && set +a
```

Enable Bedrock model access for `anthropic.claude-sonnet-4-6` in the Bedrock
console (Model access). For the real KB, create a Bedrock Knowledge Base, note
its **KB_ID**, and put it in `.env`.

---

## The seven steps and how to run each

Start Phoenix in its own terminal first (Steps 1, 3, 4, 6 export to it):

```bash
phoenix serve            # -> http://localhost:6006
```

### Step 1 + 3: partner agent + Phoenix instrumentation + manual span

```bash
# Offline (canned docs, no AWS):
MOCK_KB=true python -m src.local_agent
# Real Bedrock KB:
export KB_ID=...  AWS_REGION=us-east-1
python -m src.local_agent
```

Open http://localhost:6006: you should see an `invoke_agent
PartnerSolutionsAssistant` root span, a `chat` LLM span, tool spans, and the
manual `retrieve_partner_docs` RETRIEVER span carrying `retrieval.documents.*`
(doc ids + scores), `kb_id`, token counts, and `latency_ms`.

### Step 2: real Bedrock KB tool

The tool lives in `src/tools.py`. Smoke-test it offline:

```bash
MOCK_KB=true python -m src.tools
```

It returns a Pydantic `RetrievalResult` (documents, scores, kb_id, latency,
explicit `error` channel). On the real path a missing KB id, bad credentials, or
a Bedrock error all return a structured error and mark the span status ERROR;
never a silent empty.

### Step 4: query harness + metrics

```bash
MOCK_KB=true python -m src.run_experiments        # or real KB without MOCK_KB
```

Runs 10 queries (3 exercise the KB, 3 force failures: bad KB id, irrelevant
query, tool error), exports Phoenix spans to `experiments/spans.parquet` (+ csv),
and writes `experiments/metrics_report.txt` with p50/p95 latency, token cost,
tool-invocation rate, and failure rate.

### Step 5: three evals + LLM judge + validation

```bash
python -m src.evaluators.llm_judge                # OpenAI judge
python -m src.evaluators.llm_judge --offline      # deterministic stub judge
python -m src.evaluators.code_evaluator           # groundedness code eval
```

Prints the judge-vs-human agreement report (accuracy, precision, recall, F1,
Cohen's kappa) over `eval_labeled_set.json`. The three evals are User
Frustration, Partner-Native Tool-Selection, and the custom rubric judge
("Partner Answer Quality"); `code_evaluator.py` is the 4th, code-based eval.

### Step 6: automated feedback loop

```bash
python -m src.feedback_loop                        # OpenAI judge, live Phoenix
python -m src.feedback_loop --offline              # stub judge, harness records
```

Pulls recent traces (Phoenix, or falls back to
`experiments/query_records.json`), runs the evals, clusters failure themes,
raises flags past threshold, and writes `experiments/feedback_report.md` with a
human-in-the-loop prompt-patch stub.

### Step 7: production-readiness memo

See `DESIGN_MEMO.md` (partner choice, better-together rationale, collector
placement, sampling, eval cost at scale, PII redaction, instrumentation
overhead, reliability/rollback).

### Architecture diagram

```bash
python docs/architecture.py        # writes docs/architecture.png
```

### TRACK B: deploy on Bedrock AgentCore (optional, needs Docker + AWS)

```bash
cd agentcore && python deploy.py
```

---

## What is real vs. needs a live run

| Component | State |
|---|---|
| Pydantic-validated KB tool + structured error channel | Real, offline-verified (MOCK_KB) |
| Manual OpenInference RETRIEVER span wiring | Real code, verified import-clean |
| LLM-judge + 3 evals + judge-vs-human validation | Real; offline stub verified (acc 0.92, kappa 0.82) |
| Groundedness code evaluator | Real, unit-tested |
| Feedback loop (detect -> flag -> patch stub) | Real, offline-verified |
| Architecture diagram | Real, PNG rendered |
| Real Bedrock KB retrieval | Needs your KB_ID + AWS creds (a live run) |
| Phoenix span export in harness/feedback | Needs a running `phoenix serve` |
| AgentCore deploy | Real code; needs your AWS account + Docker |

The `MOCK_KB=true` fallback is the honest demo safety net: if KB provisioning
stalls before the panel, the full trace + eval + feedback loop still runs on the
canned `docs/*.md` corpus. Real Bedrock KB is the default; the fallback is opt-in
and disclosed here.

---

## Sources
- Arize AX, Strands Agents SDK tracing: https://arize.com/docs/ax/integrations/python-agent-frameworks/aws-strands/aws-strands-tracing
- Arize AX, Bedrock AgentCore tracing: https://arize.com/docs/ax/integrations/python-agent-frameworks/aws-strands/bedrock-agentcore
- AWS ML blog, Strands + Arize AX: https://aws.amazon.com/blogs/machine-learning/observing-and-evaluating-ai-agentic-workflows-with-strands-agents-sdk-and-arize-ax/
- OpenInference semantic conventions: https://github.com/Arize-ai/openinference
- Arize Prompt Learning research: https://arize.com/blog/
