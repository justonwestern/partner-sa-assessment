"""
tools.py
========

Strands tools for the Partner Solutions Assistant.

The headline tool here is `search_partner_docs`, a REAL Bedrock Knowledge Base
retrieval (the partner-native primitive). It is the agent's retrieval surface:

  (a) it integrates and is only invoked when the agent decides retrieval is
      relevant (Strands tool-calling decides this from the docstring);
  (b) it returns a Pydantic-validated structured output (`RetrievalResult`)
      rather than a free-form string, so downstream evals + spans get a stable
      shape (documents, scores, kb_id);
  (c) it uses the real partner primitive: bedrock-agent-runtime `retrieve`
      against a Bedrock Knowledge Base (KB ID read from .env);
  (d) it handles failure observably: every failure path returns a structured
      RetrievalResult with `error` set (never a silent empty), and the manual
      retrieval span (see instrumentation.record_retrieval_span) is marked with
      span status ERROR by the caller in local_agent.py.

MOCK_KB fallback: set MOCK_KB=true in .env to return canned docs read from the
local docs/ folder (the partner-overview markdown). This lets you run the full
trace + eval + feedback loop even if KB provisioning stalls. Real Bedrock KB is
the DEFAULT (MOCK_KB unset or false).

Run a quick offline smoke test (uses MOCK_KB so it needs no AWS):
    MOCK_KB=true python -m src.tools
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
from strands import tool


# --------------------------------------------------------------------------- #
# Pydantic structured-output models (Step 2b)
# --------------------------------------------------------------------------- #
class RetrievedDocument(BaseModel):
    """One retrieved chunk, normalized across the real-KB and mock paths."""

    doc_id: str = Field(..., description="Stable id: KB chunk location or filename.")
    text: str = Field(..., description="The retrieved chunk text.")
    score: float = Field(..., description="Relevance score in [0, 1]; 0.0 if unknown.")
    source: str = Field("", description="Human-readable source (filename / S3 uri).")


class RetrievalResult(BaseModel):
    """Validated structured output returned by `search_partner_docs`.

    Keeping this as a model (not a bare string) is what lets the experiment
    harness, the manual retrieval span, and the evaluators all read the same
    fields: documents, scores, kb_id, latency, and an explicit error channel.
    """

    query: str
    kb_id: str = Field("", description="Knowledge Base id the query ran against.")
    documents: List[RetrievedDocument] = Field(default_factory=list)
    latency_ms: float = 0.0
    mocked: bool = False
    error: Optional[str] = Field(
        None,
        description="Set when retrieval failed; None on success. Never silently empty.",
    )

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_answer_context(self) -> str:
        """Flatten to the text the LLM sees, preserving citations.

        We still hand the agent a string (that is what an LLM consumes), but the
        STRUCTURED object is what the tool returns to the framework and what the
        span records. The agent-facing text uses a `[source] text` citation
        format so the eval prompts can check for grounding.
        """
        if self.is_error:
            return f"RETRIEVAL_ERROR: {self.error}"
        if not self.documents:
            return "No matching partner documentation found."
        return "\n\n".join(f"[{d.source or d.doc_id}] {d.text}" for d in self.documents)


# --------------------------------------------------------------------------- #
# MOCK_KB fallback: canned docs from the local docs/ folder
# --------------------------------------------------------------------------- #
_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _load_mock_corpus() -> List[RetrievedDocument]:
    """Read docs/*.md once into a tiny in-memory corpus for the mock path."""
    corpus: List[RetrievedDocument] = []
    if not _DOCS_DIR.exists():
        return corpus
    for md in sorted(_DOCS_DIR.glob("*.md")):
        corpus.append(
            RetrievedDocument(
                doc_id=md.name,
                text=md.read_text(encoding="utf-8").strip(),
                score=0.0,  # filled in by the keyword scorer below
                source=md.name,
            )
        )
    return corpus


def _mock_retrieve(query: str, top_k: int) -> RetrievalResult:
    """Keyword-overlap retrieval over the local markdown corpus.

    Deterministic and offline so the demo runs without AWS. Scores are a crude
    token-overlap ratio in [0, 1] purely so the span has plausible numbers.
    """
    t0 = time.perf_counter()
    corpus = _load_mock_corpus()
    q_tokens = {w for w in query.lower().split() if len(w) > 3}

    scored: List[RetrievedDocument] = []
    for doc in corpus:
        text_low = doc.text.lower()
        hits = sum(1 for w in q_tokens if w in text_low)
        score = hits / max(len(q_tokens), 1)
        if score > 0:
            scored.append(doc.model_copy(update={"score": round(score, 3)}))

    scored.sort(key=lambda d: d.score, reverse=True)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return RetrievalResult(
        query=query,
        kb_id="MOCK_KB",
        documents=scored[:top_k],
        latency_ms=round(latency_ms, 2),
        mocked=True,
        error=None,
    )


# --------------------------------------------------------------------------- #
# Real Bedrock Knowledge Base retrieval (the partner-native primitive)
# --------------------------------------------------------------------------- #
def _bedrock_retrieve(query: str, top_k: int) -> RetrievalResult:
    """Call bedrock-agent-runtime `retrieve` against a Bedrock Knowledge Base.

    Reads KB_ID and AWS_REGION from the environment. Any failure (missing KB id,
    boto error, throttling, bad credentials) is caught and returned as a
    structured RetrievalResult with `error` set, so the failure is observable on
    the span instead of disappearing into an empty list.
    """
    t0 = time.perf_counter()
    kb_id = os.environ.get("KB_ID", "").strip()
    region = os.environ.get("AWS_REGION", "us-east-1")

    if not kb_id:
        return RetrievalResult(
            query=query,
            kb_id="",
            documents=[],
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            mocked=False,
            error="KB_ID is not set; cannot call Bedrock Knowledge Base.",
        )

    try:
        import boto3  # imported lazily so the mock path needs no boto3

        client = boto3.client("bedrock-agent-runtime", region_name=region)
        resp = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        )
        docs: List[RetrievedDocument] = []
        for item in resp.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            loc = item.get("location", {})
            # Prefer the S3 uri as the doc id/source when present.
            s3_uri = loc.get("s3Location", {}).get("uri", "")
            chunk_id = item.get("metadata", {}).get("x-amz-bedrock-kb-chunk-id", "chunk")
            doc_id = s3_uri or chunk_id
            docs.append(
                RetrievedDocument(
                    doc_id=str(doc_id),
                    text=content,
                    score=float(item.get("score", 0.0) or 0.0),
                    source=s3_uri or str(doc_id),
                )
            )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        # An empty result is NOT an error here; the agent / eval can decide what
        # "ran but found nothing" means. Errors get the `error` channel.
        return RetrievalResult(
            query=query,
            kb_id=kb_id,
            documents=docs,
            latency_ms=round(latency_ms, 2),
            mocked=False,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - we WANT every failure surfaced
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            query=query,
            kb_id=kb_id,
            documents=[],
            latency_ms=round(latency_ms, 2),
            mocked=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def retrieve_partner_docs(query: str, top_k: int = 4) -> RetrievalResult:
    """Dispatch to the real KB or the mock corpus based on MOCK_KB.

    This is the plain-Python entrypoint the experiment harness and the manual
    span wrapper call directly (so they get the full structured object). The
    Strands @tool wrapper below delegates here.
    """
    mock = os.environ.get("MOCK_KB", "false").strip().lower() in ("1", "true", "yes")
    if mock:
        return _mock_retrieve(query, top_k)
    return _bedrock_retrieve(query, top_k)


# --------------------------------------------------------------------------- #
# Strands tools
# --------------------------------------------------------------------------- #
@tool
def search_partner_docs(query: str) -> str:
    """Search Arize partner integration docs (AWS, GCP, Databricks, NVIDIA, Anthropic).

    Use this whenever the user asks how Arize integrates with, co-sells with, or
    is observed alongside a specific cloud or model partner. Do NOT use it for
    questions about Bedrock model-id / inference-profile formatting; use
    check_model_access for those.

    Args:
        query: A natural-language question about an Arize partner integration.
    """
    # The framework receives the flattened, citation-preserving text, but we
    # validate + build the structured RetrievalResult first so the shape is
    # guaranteed. local_agent.py calls retrieve_partner_docs() directly to get
    # the structured object for the manual retrieval span.
    result = retrieve_partner_docs(query)
    return result.to_answer_context()


@tool
def check_model_access(model_id: str) -> str:
    """Report whether a Bedrock model id is configured for cross-region inference.

    Args:
        model_id: A Bedrock model id, e.g. 'us.anthropic.claude-sonnet-4-6'.
    """
    if model_id.startswith(("us.", "eu.", "apac.")):
        return f"{model_id} uses a cross-region inference profile and is ready to invoke."
    return (
        f"{model_id} is missing a geography prefix. Newer Claude models on "
        f"Bedrock require a cross-region inference profile (prefix 'us.')."
    )


# Quick offline smoke test:  MOCK_KB=true python -m src.tools
if __name__ == "__main__":
    os.environ.setdefault("MOCK_KB", "true")
    for q in [
        "How does Arize integrate with AWS Bedrock for agentic RAG?",
        "What is the NVIDIA NeMo on-prem observability story?",
        "totally unrelated question about gardening",
    ]:
        r = retrieve_partner_docs(q)
        print(f"\nQ: {q}")
        print(f"  kb_id={r.kb_id} mocked={r.mocked} error={r.error} "
              f"latency_ms={r.latency_ms} n_docs={len(r.documents)}")
        for d in r.documents:
            print(f"   - {d.source} score={d.score}")
