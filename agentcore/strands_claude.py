"""
strands_claude.py
=================

TRACK B (the headline deliverable Rich named): the SAME Partner Solutions
Assistant, packaged as a Bedrock AgentCore Runtime app and sending OTLP traces
to Arize AX. This is the file AgentCore builds into a container and deploys.

Verified against the Arize AX "Bedrock AgentCore" integration doc (June 2026):
https://arize.com/docs/ax/integrations/python-agent-frameworks/aws-strands/bedrock-agentcore

Runtime-specific quirk: AgentCore registers its OWN tracer provider by default.
You must disable that (disable_otel=True at configure time + DISABLE_ADOT_
OBSERVABILITY=true at launch) and explicitly set the Arize-bound provider here,
or OTel refuses to override the registered provider.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel
from openinference.instrumentation.strands_agents import (
    StrandsAgentsToOpenInferenceProcessor,
)

# ---- Tracing wiring (runs once at container import) -----------------------
# The OTLP gRPC exporter reads endpoint + headers from OTEL_EXPORTER_OTLP_*
# env vars, which deploy.py injects at launch() time.
_resource = Resource.create(
    {
        "openinference.project.name": os.environ.get(
            "ARIZE_PROJECT_NAME", "bedrock-agentcore-cookbook"
        ),
        "service.name": "bedrock-agentcore-strands-agent",
    }
)
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(StrandsAgentsToOpenInferenceProcessor())
_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(_provider)

# ---- The deployed app ------------------------------------------------------
app = BedrockAgentCoreApp()

SYSTEM_PROMPT = (
    "You are a Partner Solutions Assistant for an AI observability platform. "
    "Answer integration questions about Strands, Bedrock AgentCore, and Arize "
    "in three sentences or fewer, citing the relevant concept."
)


@app.entrypoint
def partner_solutions_agent(payload, context=None):
    """AgentCore invokes this for every /invocations POST."""
    agent = Agent(
        name="PartnerSolutionsAssistant",
        model=BedrockModel(
            model_id="us.anthropic.claude-sonnet-4-6",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"),
        ),
        system_prompt=SYSTEM_PROMPT,
    )
    response = agent(payload.get("prompt", ""))
    # Force a flush so spans for this invocation are not stranded on a
    # long-lived runtime waiting for the next call.
    _provider.force_flush()
    return response.message["content"][0]["text"]


if __name__ == "__main__":
    app.run()
