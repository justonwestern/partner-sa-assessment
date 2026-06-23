"""
instrumentation.py
==================

OpenTelemetry -> OpenInference wiring for the LOCAL track, targeting LOCAL
PHOENIX by default (Step 3).

The assessment mandates capturing traces in local Phoenix (phoenix serve,
http://localhost:6006). So this module registers a TracerProvider that:

  * routes Strands' native OpenTelemetry spans through the OpenInference
    processor (so LLM / tool spans get OpenInference semantic-convention
    attributes Phoenix understands), and
  * exports them to local Phoenix's OTLP endpoint.

Arize AX (otlp.arize.com) is kept behind the TRACE_BACKEND=ax env flag and is
documented as the enterprise upgrade path: same OpenInference spans, swap the
exporter target and add space-id / api-key headers. That is the "better
together" production story for Step 7, not the local default.

This module also exposes `record_retrieval_span(...)`, the at-least-one MANUAL
custom span the brief requires. It wraps the Bedrock KB retrieval and records
OpenInference RETRIEVER-kind attributes: retrieval.documents (id + score + text
per document), plus kb_id, token counts, and latency_ms. See local_agent.py for
the call site.

Import this module BEFORE constructing any Strands Agent so the global
TracerProvider is registered first.
"""

from __future__ import annotations

import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Status, StatusCode

from strands.telemetry import StrandsTelemetry
from openinference.instrumentation.strands_agents import (
    StrandsAgentsToOpenInferenceProcessor,
)

# OpenInference semantic-convention attribute keys. Importing the constants
# rather than hardcoding strings keeps us aligned with the spec and is exactly
# the "explain OpenInference semantic conventions" talking point for Step 3.
from openinference.semconv.trace import (
    SpanAttributes,
    OpenInferenceSpanKindValues,
    DocumentAttributes,
)


# A module-level tracer so any file can grab the same instrument once tracing
# is initialized. Populated by init_tracing().
_TRACER: Optional[trace.Tracer] = None


def _phoenix_endpoint() -> str:
    """Local Phoenix OTLP traces endpoint (override with PHOENIX_ENDPOINT)."""
    base = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006").rstrip("/")
    # Phoenix's OTLP HTTP collector lives at /v1/traces.
    return f"{base}/v1/traces"


def init_tracing() -> TracerProvider:
    """Build, register, and return the TracerProvider.

    Default backend is LOCAL PHOENIX. Set TRACE_BACKEND=ax to ship the SAME
    OpenInference spans to Arize AX instead (the enterprise upgrade path).
    """
    global _TRACER

    project_name = os.environ.get(
        "ARIZE_PROJECT_NAME", "strands-agentcore-cookbook-local"
    )
    backend = os.environ.get("TRACE_BACKEND", "phoenix").strip().lower()

    resource = Resource.create(
        {
            # Phoenix and AX both read this to route into a project.
            "openinference.project.name": project_name,
            "service.name": "strands-agentcore-cookbook",
        }
    )
    provider = TracerProvider(resource=resource)
    # Reshape Strands' native OTel spans into OpenInference layout.
    provider.add_span_processor(StrandsAgentsToOpenInferenceProcessor())

    if backend == "ax":
        # ---- Enterprise upgrade path: Arize AX -------------------------------
        # Same spans, different destination. AX adds long-term retention,
        # online evals, RBAC, and the Alyx engineering agent on top.
        telemetry = StrandsTelemetry(tracer_provider=provider)
        telemetry.setup_otlp_exporter(
            endpoint="https://otlp.arize.com/v1/traces",
            headers={
                "authorization": os.environ["ARIZE_API_KEY"],
                "arize-space-id": os.environ["ARIZE_SPACE_ID"],
                "arize-interface": "python",
            },
        )
        dest = "Arize AX (otlp.arize.com)"
    else:
        # ---- Default: local Phoenix -----------------------------------------
        # Plain OTLP/HTTP exporter to the local Phoenix collector. No headers,
        # no cloud account; this is the screen-share-friendly default.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_phoenix_endpoint()))
        )
        dest = _phoenix_endpoint()

    # IMPORTANT: register globally. Strands' Agent calls
    # opentelemetry.trace.get_tracer(...), which reads the GLOBAL provider.
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("strands-agentcore-cookbook")

    print(
        f"[instrumentation] tracing initialized (backend={backend}) "
        f"-> {dest} | project '{project_name}'"
    )
    return provider


def get_tracer() -> trace.Tracer:
    """Return the shared tracer; init a no-export tracer if not yet set up."""
    global _TRACER
    if _TRACER is None:
        _TRACER = trace.get_tracer("strands-agentcore-cookbook")
    return _TRACER


def record_retrieval_span(query: str, result, parent_context=None):
    """Emit ONE manual RETRIEVER span around a Bedrock KB retrieval (Step 3).

    Records OpenInference semantic-convention attributes:
      * openinference.span.kind = RETRIEVER
      * input.value             = the query
      * retrieval.documents.{i}.document.{id,score,content}
      * custom: kb_id, retrieval.mocked, latency_ms, token counts

    `result` is a tools.RetrievalResult. If it carries an error, the span is set
    to status ERROR and the exception is recorded, so failures are observable
    rather than silently empty.

    This is a CONTEXT-FREE helper: it opens and closes its own span. Calling it
    inside the agent invocation means the OpenInference processor nests it under
    the active agent span automatically.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("retrieve_partner_docs") as span:
        # --- OpenInference span kind + input ---
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.RETRIEVER.value,
        )
        span.set_attribute(SpanAttributes.INPUT_VALUE, query)

        # --- Custom retrieval attributes ---
        span.set_attribute("kb_id", result.kb_id or "")
        span.set_attribute("retrieval.mocked", bool(result.mocked))
        span.set_attribute("latency_ms", float(result.latency_ms))
        span.set_attribute("retrieval.num_documents", len(result.documents))

        # Crude token estimate (chars / 4) so the span carries a cost signal even
        # without a tokenizer; the harness uses the LLM span for real counts.
        retrieved_chars = sum(len(d.text) for d in result.documents)
        approx_tokens = retrieved_chars // 4
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_PROMPT, approx_tokens)
        span.set_attribute("retrieval.approx_tokens", approx_tokens)

        # --- Per-document OpenInference attributes ---
        # retrieval.documents.{i}.document.{id|score|content}
        for i, doc in enumerate(result.documents):
            prefix = f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.{i}.{DocumentAttributes.DOCUMENT_ID}"
            span.set_attribute(prefix, doc.doc_id)
            span.set_attribute(
                f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.{i}.{DocumentAttributes.DOCUMENT_SCORE}",
                float(doc.score),
            )
            span.set_attribute(
                f"{SpanAttributes.RETRIEVAL_DOCUMENTS}.{i}.{DocumentAttributes.DOCUMENT_CONTENT}",
                doc.text[:2000],  # truncate to keep span payload sane
            )

        # --- Observable failure handling ---
        if result.is_error:
            span.set_status(Status(StatusCode.ERROR, result.error))
            span.set_attribute("error.message", result.error)
            # Record as an exception event too, so it shows in the span's events.
            span.record_exception(RuntimeError(result.error))
        else:
            span.set_status(Status(StatusCode.OK))
            span.set_attribute(
                SpanAttributes.OUTPUT_VALUE, result.to_answer_context()[:2000]
            )

        return result
