# Design Memo: Partner Framework Agent, Observed in Phoenix / Arize

**Author:** Partner Solutions Architect candidate
**Scope:** Step 7 of the technical assessment. Partner choice, better-together
rationale, and a production-readiness plan. This memo reasons about production;
it does not build cloud infrastructure.

---

## 1. Partner choice: AWS (Strands + Bedrock), better together with Arize

I chose **AWS** as the partner and built the agent on **Strands** (AWS's
open-source agent SDK) running against **Amazon Bedrock** (Claude Sonnet), with
retrieval through a **Bedrock Knowledge Base**. The observability and evaluation
layer is **Phoenix** locally, with **Arize AX** as the enterprise upgrade.

Why this is the strongest joint story:

- **AWS owns the build surface; Arize owns the trust surface.** Bedrock,
  Knowledge Bases, AgentCore, and Strands let a customer stand up an agentic RAG
  system fast. None of them tell the customer whether the agent is *correct* in
  production. Arize is the trace tree, the span-level eval, and the regression
  gate that lets the customer ship with confidence. The two are complementary,
  not competitive, which is the cleanest co-sell.
- **The integration is native, not a bolt-on.** Strands emits OpenTelemetry
  spans natively; Arize consumes OpenInference (an OTel semantic-convention
  layer). There is no custom shim: the agent's own telemetry is the eval signal.
  That is a low-friction "better together" you can demo in fifteen minutes.
- **The co-sell motion already exists.** re:Invent main stage and AWS Partner
  Network breakouts, joint "Evaluating and Observing AI on AWS" workshops, and
  sales pairing with AWS ProServe and Bedrock specialist sellers on customer
  POCs. The technical artifact in this repo is the reusable proof point those
  motions need.

The repeatable partner play: a Bedrock customer launches an agentic RAG pilot,
hits hallucination or tool-call latency in UAT, and needs trace-level visibility
to debug. Arize provides the trace tree, the span-level eval, and the regression
dataset to gate the production rollout. This repo is that play, in code.

---

## 2. Local Phoenix default, Arize AX as the enterprise upgrade

The assessment build targets **local Phoenix** (`phoenix serve`,
`localhost:6006`) so the whole loop runs on a laptop with no cloud account. The
exact same OpenInference spans upgrade to **Arize AX** by flipping
`TRACE_BACKEND=ax` and supplying space-id / API-key headers (see
`src/instrumentation.py`). What AX adds on top of OSS Phoenix is the production
story: long-term trace retention, prompt and dataset versioning, online evals,
RBAC for partner-managed deployments, and the **Alyx** engineering agent that
drafts evals from observed failures. The local-to-AX path is deliberately a
one-line change so the upgrade narrative is credible, not hand-wavy.

---

## 3. Production-readiness plan

### 3.1 Collector placement

- **Do not export straight from the app to the SaaS backend in production.** The
  laptop demo uses a direct OTLP/HTTP exporter to Phoenix for simplicity. In
  production, run an **OpenTelemetry Collector** (or AWS Distro for OpenTelemetry,
  ADOT) as a sidecar or a per-cluster gateway. The app exports to `localhost`
  (sidecar) or an in-VPC collector endpoint; the collector batches, retries,
  redacts, samples, and fans out to Phoenix/AX.
- **Why:** it decouples app deploys from observability config, gives one place to
  enforce PII redaction and sampling, and survives backend outages via the
  collector's retry queue instead of blocking the request path.
- **Bedrock AgentCore note:** AgentCore registers its own OTel provider. We
  disable it (`disable_otel=True`, `DISABLE_ADOT_OBSERVABILITY=true`) and set our
  own exporter, so traces go to Phoenix/AX rather than being double-exported to
  CloudWatch. That decision lives in `agentcore/deploy.py` and is the kind of
  runtime quirk a production rollout has to get right.

### 3.2 Trace sampling strategy

- **Head sampling is the wrong default for agents.** Random head sampling drops
  whole traces blindly and tends to throw away the rare failures you most want.
- **Use tail-based sampling at the collector:** keep 100% of traces that contain
  an error span, a tool failure, a high-latency span, or a low eval score; keep a
  low baseline rate (for example 5-10%) of clean traffic for distribution
  monitoring. This is configured in the collector's tail-sampling processor, not
  in app code, so policy changes do not require a redeploy.
- **Always keep traces that an online eval flags.** The point of the system is
  catching regressions; never sample those away.

### 3.3 Eval cost at scale

- **Evals are LLM calls, so they cost money and add latency.** Running an
  LLM-judge on every span at full traffic is the failure mode.
- **Mitigations, in order of leverage:** (1) sample which spans get judged (judge
  the tail-sampled set, not all traffic); (2) use a small, cheap judge model
  (`gpt-4o-mini` here) and validate it against human labels so you trust the
  cheap model (see `src/evaluators/llm_judge.py`, which reports accuracy and
  Cohen's kappa); (3) run code-based evals (like the groundedness checker in
  `code_evaluator.py`) for free where a deterministic check suffices, and reserve
  LLM-judges for the genuinely subjective dimensions; (4) run evals
  asynchronously/offline over the exported span dataframe rather than inline in
  the request path. The validated-judge step is what lets you defend "we judge
  with a cheap model" to a customer.

### 3.4 PII handling and redaction

- **Redact at the collector, before traces leave the customer perimeter.** Span
  input/output values are the highest-risk attributes (they carry raw user text).
  Use the collector's attributes/transform processor to hash, drop, or mask
  fields (emails, account numbers, names) by attribute key and by regex on
  `input.value` / `output.value`.
- **Prefer in-VPC for regulated customers.** For finance, healthcare, and
  government, the NVIDIA NeMo on-prem pattern generalizes: Arize AX can deploy
  inside the customer's perimeter so production traces never reach a third-party
  SaaS. That is the answer to "we cannot ship traces out."
- **Minimize at the source too:** do not put secrets or full documents on spans;
  the manual retrieval span here truncates document content and records ids +
  scores rather than dumping full payloads.

### 3.5 Instrumentation overhead

- **Tracing is cheap when batched and async.** Use `BatchSpanProcessor` (we do),
  never the simple processor, so spans are exported off the request path.
- **The real cost is the manual spans and the eval calls, not the OTel plumbing.**
  Keep manual-span attribute payloads bounded (we truncate document content to
  2000 chars). Budget single-digit-millisecond overhead for span creation; the
  eval LLM calls are the part to run async.
- **Measure it:** `src/run_experiments.py` already reports p50/p95 latency and a
  token-cost estimate, which is exactly the overhead-budget instrument you would
  watch in a canary.

### 3.6 Reliability and rollback

- **Observability must fail open.** If Phoenix/AX is unreachable, the agent must
  still serve. The collector's retry queue absorbs short outages; the app should
  never block on the exporter. The exporters here are non-blocking and the tool
  layer returns structured errors rather than raising into the request path.
- **Gate prompt/agent changes on evals, and keep rollback one flag away.** The
  feedback loop (`src/feedback_loop.py`) proposes prompt patches but keeps a
  human approval gate; changes ship behind the fenced `<INSTRUCTIONS>` block so a
  rollback is reverting one block, and the before/after metrics (latency, eval
  pass rate) are attached to the PR. Treat the eval suite as the regression gate:
  a prompt change that drops rubric pass-rate or raises frustration does not
  merge.
- **Canary the agent, not just the model.** Roll a new prompt/tool config to a
  small traffic slice, compare eval scores and latency against the incumbent on
  the same query set, and promote only on a clean delta.

---

## 4. The 60-second pitch

AWS gives a customer everything to *build* an agent: Bedrock for the model,
Knowledge Bases for retrieval, Strands and AgentCore to orchestrate and deploy.
What AWS does not give them is proof the agent is *right* in production. That is
Arize. Strands emits OpenTelemetry natively, Arize speaks OpenInference, so the
agent's own telemetry becomes the eval signal with no custom glue. The customer
ships on AWS, debugs and gates with Arize, and we co-sell the same workshop into
every Bedrock agentic-RAG account. Better together, in one trace tree.
