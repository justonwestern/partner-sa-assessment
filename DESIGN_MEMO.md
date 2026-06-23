# Design Memo: Partner Framework Agent, Observed in Phoenix / Arize

**Scope:** Partner choice, the better-together rationale, and a production-readiness
plan. This memo reasons about production; it does not build cloud infrastructure.

---

## 1. Partner choice: AWS (Strands + Bedrock), better together with Arize

I chose **AWS** and built the agent on **Strands** (AWS's open-source agent SDK)
against **Amazon Bedrock** (Claude Sonnet), with retrieval through a **Bedrock
Knowledge Base**. Observability and evaluation run in **Phoenix** locally, with
**Arize AX** as the enterprise upgrade. Why it's the strongest joint story:

- **AWS owns the build surface; Arize owns the trust surface.** Bedrock, Knowledge
  Bases, AgentCore, and Strands let a customer stand up agentic RAG fast, but none
  of them tell the customer whether the agent is *correct* in production. Arize is
  the trace tree, the span-level eval, and the regression gate. Complementary, not
  competitive: the cleanest co-sell.
- **The integration is native, not a bolt-on.** Strands emits OpenTelemetry spans
  natively; Arize consumes OpenInference (an OTel semantic-convention layer). No
  custom shim: the agent's own telemetry is the eval signal, demoable in minutes.
- **The co-sell motion exists** (re:Invent, APN breakouts, joint "Evaluating AI on
  AWS" workshops, ProServe / Bedrock-specialist POC pairing). This repo is the
  reusable proof point those motions need.

The repeatable play: a Bedrock customer launches an agentic-RAG pilot, hits
hallucination or tool-call latency in UAT, and needs trace-level visibility to
debug. Arize provides the trace tree, span-level eval, and regression dataset to
gate rollout. This repo is that play, in code.

---

## 2. Local Phoenix default, Arize AX as the enterprise upgrade

The build targets **local Phoenix** (`phoenix serve`, `localhost:6006`) so the
whole loop runs on a laptop with no cloud account. The same OpenInference spans
upgrade to **Arize AX** by flipping `TRACE_BACKEND=ax` and adding space-id /
API-key headers (`src/instrumentation.py`). AX adds the production layer:
long-term retention, prompt/dataset versioning, online evals, RBAC for
partner-managed deployments, and the **Alyx** agent that drafts evals from
observed failures. The local-to-AX path is one line, so the upgrade narrative is
credible, not hand-wavy.

---

## 3. Production-readiness plan

**3.1 Collector placement.** Don't export app-to-SaaS directly in production. Run
an **OpenTelemetry Collector** (or ADOT) as a sidecar or per-cluster gateway; the
app exports to localhost / an in-VPC endpoint and the collector batches, retries,
redacts, samples, and fans out to Phoenix/AX. This decouples app deploys from
observability config, centralizes PII redaction and sampling, and survives backend
outages via the retry queue instead of blocking requests. *AgentCore quirk:* it
registers its own OTel provider, so we disable it (`disable_otel=True`) and set our
own exporter to avoid double-export to CloudWatch (`agentcore/deploy.py`).

**3.2 Trace sampling.** Head sampling is wrong for agents — it drops the rare
failures you most want. Use **tail-based sampling at the collector**: keep 100% of
traces with an error span, tool failure, high-latency span, low eval score, or an
online-eval flag; keep a 5-10% baseline of clean traffic for distribution
monitoring. It's collector config, not app code, so policy changes need no redeploy.

**3.3 Eval cost at scale.** Evals are LLM calls, so judging every span at full
traffic is the failure mode. In order of leverage: (1) judge only the tail-sampled
set; (2) use a small, cheap judge (`gpt-4o-mini`) *validated* against human labels
so you can trust it (`llm_judge.py` reports accuracy + Cohen's kappa); (3) use free
code-based evals (`code_evaluator.py`) for deterministic checks, reserving
LLM-judges for subjective dimensions; (4) run evals async/offline over the exported
span dataframe, not inline.

**3.4 PII handling.** Redact at the collector, before traces leave the customer
perimeter — span input/output values carry raw user text; use the
attributes/transform processor to hash/drop/mask by key and regex. For regulated
customers, deploy Arize AX in-VPC so production traces never reach third-party SaaS.
Minimize at the source too: the manual retrieval span truncates document content
and records ids + scores, not full payloads.

**3.5 Instrumentation overhead.** Tracing is cheap when batched and async — use
`BatchSpanProcessor` (we do), never the simple one. The real cost is manual-span
payloads and eval calls, not the OTel plumbing; we cap document content at 2000
chars and budget single-digit-ms span creation. `run_experiments.py` already
reports p50/p95 latency and token cost — the overhead instrument you'd watch in a
canary.

**3.6 Reliability and rollback.** Observability must fail open: if Phoenix/AX is
unreachable the agent still serves (non-blocking exporters, collector retry queue,
tool layer returns structured errors). Gate prompt/agent changes on evals: the
feedback loop proposes patches behind the fenced `<INSTRUCTIONS>` block with a human
approval gate, so rollback is reverting one block and the eval suite is the
regression gate (a change that drops rubric pass-rate or raises frustration doesn't
merge). Canary new configs on a traffic slice and promote only on a clean
eval/latency delta.

---

## 4. The 60-second pitch

AWS gives a customer everything to *build* an agent — Bedrock for the model,
Knowledge Bases for retrieval, Strands and AgentCore to orchestrate and deploy.
What it doesn't give them is proof the agent is *right* in production. That's
Arize. Strands emits OpenTelemetry natively and Arize speaks OpenInference, so the
agent's own telemetry becomes the eval signal with no custom glue. The customer
ships on AWS, debugs and gates with Arize, and we co-sell the same workshop into
every Bedrock agentic-RAG account. Better together, in one trace tree.
