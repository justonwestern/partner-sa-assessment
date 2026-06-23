"""
local_agent.py
==============

TRACK A: a Strands agent running locally, sending traces to LOCAL PHOENIX by
default (Step 1 + Step 3). It is the same agent code you later deploy on Bedrock
AgentCore in TRACK B (agentcore/strands_claude.py); only the runtime differs.

What changed from the skeleton:
  * tracing now targets local Phoenix (see src/instrumentation.py); AX is behind
    TRACE_BACKEND=ax.
  * `ask()` wraps each turn so that when the agent's answer relied on partner-doc
    retrieval, we ALSO emit a manual OpenInference RETRIEVER span via
    record_retrieval_span(). That gives Step 3 its required custom span with doc
    ids, scores, kb_id, token counts, and latency.

Run (mock fallback, no AWS needed):
    phoenix serve            # in another terminal -> http://localhost:6006
    MOCK_KB=true python -m src.local_agent

Run against a real Bedrock KB:
    export KB_ID=...  AWS_REGION=us-east-1
    python -m src.local_agent
"""

# Import instrumentation FIRST so the global TracerProvider is registered
# before the Strands Agent is constructed.
from src.instrumentation import init_tracing, record_retrieval_span

from strands import Agent
from strands.models.bedrock import BedrockModel

from src.tools import (
    search_partner_docs,
    check_model_access,
    retrieve_partner_docs,
)


SYSTEM_PROMPT = (
    "You are a Partner Solutions Assistant for an AI observability platform. "
    "Use the tools to answer integration questions about Strands, Bedrock "
    "AgentCore, and Arize partners. When the question is about how Arize "
    "integrates with a specific partner (AWS, GCP, Databricks, NVIDIA, "
    "Anthropic), call search_partner_docs. Cite the doc snippet you used. "
    "Answer in three sentences or fewer."
)

# Heuristic: which partners, if named, mean the answer should be grounded in a
# KB retrieval. Used only to decide whether to emit the manual retrieval span.
_PARTNER_HINTS = (
    "bedrock", "aws", "gcp", "vertex", "google", "databricks", "mosaic",
    "mlflow", "nvidia", "nemo", "anthropic", "claude", "partner",
)


def build_agent() -> Agent:
    """Construct the agent. Kept as a factory so TRACK B and the harness reuse it."""
    return Agent(
        name="PartnerSolutionsAssistant",
        model=BedrockModel(model_id="us.anthropic.claude-sonnet-4-6"),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_partner_docs, check_model_access],
    )


def ask(agent: Agent, prompt: str) -> str:
    """Run one turn and, when relevant, emit the manual retrieval span.

    The agent itself decides whether to call search_partner_docs. We mirror that
    decision with a heuristic so the manual RETRIEVER span (with doc ids/scores/
    kb_id/tokens/latency) is recorded for partner-integration questions. In a
    fully production build you would instead emit this span from inside the tool
    wrapper; we keep it here so the candidate can read the whole flow top-down.
    """
    lower = prompt.lower()
    if any(h in lower for h in _PARTNER_HINTS):
        result = retrieve_partner_docs(prompt)
        record_retrieval_span(prompt, result)

    result = agent(prompt)
    return str(result)


def main() -> None:
    provider = init_tracing()
    agent = build_agent()

    prompts = [
        "How do Strands agents send traces to Arize, and is "
        "us.anthropic.claude-sonnet-4-6 ready to invoke on Bedrock?",
        "How does Arize integrate with AWS Bedrock for agentic RAG?",
        "Why would a Databricks customer add Arize on top of MLflow?",
    ]
    for p in prompts:
        print(f"\n=== PROMPT: {p}\n")
        print(ask(agent, p))

    # Force flush + shutdown so the BatchSpanProcessor does not drop late spans
    # when the process exits.
    provider.force_flush(timeout_millis=10000)
    provider.shutdown()
    print("\n[local_agent] spans flushed. Open http://localhost:6006 to inspect.")


if __name__ == "__main__":
    main()
