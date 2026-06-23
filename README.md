# Partner SA Assessment: a Strands + Bedrock agent, observed in local Phoenix

A runnable "better-together" reference build for the Arize Partner Solutions
Architect assessment. A **Strands** agent on **Amazon Bedrock** (Claude Sonnet)
retrieves through a real **Bedrock Knowledge Base**, emits **OpenInference**
spans into **local Phoenix**, is scored by three evals plus an LLM-judge, and is
closed with a lightweight automated feedback loop. **Arize AX + Alyx** is the
documented enterprise upgrade path.

> Status: end-to-end live-verified on 2026-06-23 against a **real Bedrock
> Knowledge Base** (Titan Text Embeddings V2 + quick-create OpenSearch
> Serverless), **Claude Sonnet on Bedrock**, a local `phoenix serve`, and the
> **OpenAI judge**. The `MOCK_KB=true` offline path is the disclosed fallback
> (canned `docs/*.md` corpus, no AWS). AgentCore deploy (TRACK B) is real code
> that needs your AWS account + Docker. See "What is real vs. needs a live run".

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

Enable Anthropic Claude on Bedrock: the legacy "Model access" page is retired;
serverless models auto-enable on first invoke, but first-time Anthropic use
requires submitting the one-time use-case form (Bedrock → Model catalog banner).
For the real KB, create a Bedrock Knowledge Base (S3 data source + Titan Text
Embeddings V2 + quick-create OpenSearch Serverless), note its **KB_ID**, and put
it in `.env`. Note: Bedrock KB creation must be done as an IAM user/role, not the
account root. Credentials are read from your AWS CLI profile (`aws configure`),
so they never need to live in `.env` (set `AWS_PROFILE`/`AWS_REGION` instead).

---

## The seven steps and how to run each

Start Phoenix in its own terminal first (Steps 1, 3, 4, 6 export to it):

```bash
phoenix serve            # -> http://localhost:6006
```

> **Step 1 choice (partner + sample):** instead of cloning an off-the-shelf
> sample, this is a *purpose-built* Strands agent on Bedrock — the assessment's
> allowed extra-credit path — so every piece (the tool, the manual span, the
> evals, the feedback loop) is one I can explain, modify, and extend on demand.
> The partner rationale ("AWS owns the build surface, Arize owns the trust
> surface") is in `DESIGN_MEMO.md` §1.

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

Runs 12 queries (KB-exercising; 3 forced failures: bad KB id, irrelevant query,
tool error; and 2 frustrated-user turns), exports Phoenix spans to
`experiments/spans.parquet` (+ csv), and writes `experiments/metrics_report.txt`
with p50/p95 latency, token cost, the agent's real tool-selection rate (read
per-turn from the tool spans, reported separately from the harness's forced
retrievals), and failure rate. Live run: p50 ~5.5s, agent tool-selection 7/12,
2 observable retrieval failures.

The full span export (`experiments/spans.parquet` + `.csv`) is gitignored for
size; regenerate it with the command above against a running Phoenix. The
committed evidence is the digested `experiments/metrics_report.txt`,
`query_records.json`, `feedback_report.md`, and a small human-readable
`experiments/spans_sample.md` excerpt of the exported spans.

### Step 5: three evals + LLM judge + validation

```bash
python -m src.evaluators.llm_judge                # OpenAI judge
python -m src.evaluators.llm_judge --offline      # deterministic stub judge
python -m src.evaluators.code_evaluator           # groundedness code eval
```

Prints the judge-vs-human agreement report (accuracy, precision, recall, F1,
Cohen's kappa) over `eval_labeled_set.json` (15 items incl. 3 borderline cases).
Live run with OpenAI gpt-4o-mini: acc 0.93 / F1 0.94 / kappa 0.86, with one
honest disagreement on a borderline missing-citation answer (the judge
over-credited the citation criterion — mitigation: the deterministic
`code_evaluator.py` citation/groundedness check). The three evals are User
Frustration, Partner-Native Tool-Selection, and the custom rubric judge
("Partner Answer Quality"); `code_evaluator.py` is the 4th, code-based eval.

**Methodology.** Each eval is an LLM judge that returns a label plus a
one-sentence English rationale (the "English error term" the feedback loop
consumes). *User Frustration* reads the user message for frustration signals
(repetition, "again/still", all-caps, "that's not what I asked") and labels
`frustrated` / `not_frustrated`. *Tool-Selection* is told the query and whether
the partner-native `search_partner_docs` actually ran, then judges whether that
was the right call. The *rubric judge* scores against an explicit 4-criterion
rubric (grounded, on-topic, cited, concise). Trust is established by validating
the rubric judge against the hand-labeled set and reporting agreement +
disagreements (above); `feedback_loop.py` then writes each label back onto the
Phoenix span as an annotation and filters the frustrated turns into a dataset.

### Step 6: automated feedback loop

```bash
python -m src.feedback_loop                        # OpenAI judge, live Phoenix
python -m src.feedback_loop --offline              # stub judge, harness records
```

Pulls recent traces (Phoenix root/agent spans, or falls back to
`experiments/query_records.json`), runs the evals, **attaches their labels back
onto the Phoenix spans as annotations** (`user_frustration`,
`partner_tool_selection`, `partner_answer_quality`) and **registers a
`frustrated-interactions` Phoenix dataset** (Step 5.1: filter + dataset),
clusters failure themes, raises flags past threshold, and writes
`experiments/feedback_report.md` with a human-in-the-loop prompt-patch stub.

The loop uses the `phoenix.client` SDK (the programmatic equivalent of the PX
CLI) to pull spans, log annotations, and create the dataset; the PX CLI / Phoenix
skills are an interchangeable surface for the same operations in a dev workflow.

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
| Real Bedrock KB retrieval (Pydantic tool + structured error channel) | Live-verified 2026-06-23 (KB over 5 partner docs; correct top-doc ranking; failures surfaced) |
| Manual OpenInference RETRIEVER span (doc ids/scores/kb_id/tokens/latency) | Live-verified; renders as a RETRIEVER span nested under the agent turn in Phoenix |
| Three evals + LLM judge + judge-vs-human validation | Live-verified with OpenAI gpt-4o-mini (acc 0.93, F1 0.94, kappa 0.86 over 15 items) |
| Eval labels attached to spans + `frustrated-interactions` dataset | Live-verified in the Phoenix UI |
| Groundedness code evaluator | Real, unit-tested |
| Feedback loop (detect -> flag -> patch stub) | Live-verified against Phoenix traces |
| Phoenix span export in harness/feedback (`phoenix.client`) | Live-verified with `phoenix serve` running |
| Architecture diagram | Real, PNG rendered (`docs/architecture.png`) |
| AgentCore deploy (TRACK B) | Real code; needs your AWS account + Docker (not run here) |

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
