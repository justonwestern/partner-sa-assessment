"""
deploy.py
=========

Runs LOCALLY. Ships strands_claude.py to Bedrock AgentCore Runtime, then invokes
the deployed agent. The starter toolkit auto-creates the ECR repo and the IAM
execution role on first run (Docker must be running locally to build the image).

Verified against the Arize AX "Bedrock AgentCore" integration doc (June 2026).

Prereqs (see ../README.md):
    pip install bedrock-agentcore-starter-toolkit
    export ARIZE_SPACE_ID=... ARIZE_API_KEY=... ARIZE_PROJECT_NAME=...
    export AWS_REGION=us-west-2   # a region where AgentCore is available
"""

import os

from bedrock_agentcore_starter_toolkit import Runtime
from boto3.session import Session


def main() -> None:
    region = Session().region_name or os.environ.get("AWS_REGION", "us-west-2")

    runtime = Runtime()
    runtime.configure(
        entrypoint="strands_claude.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=region,
        agent_name="strands_agentcore_arize_observability",
        memory_mode="NO_MEMORY",
        # Disable AgentCore's built-in OTel; strands_claude.py wires its own
        # Arize-bound TracerProvider.
        disable_otel=True,
    )

    # AgentCore's container env expects OTEL_EXPORTER_OTLP_HEADERS as a plain
    # comma-separated key=value string (no quoting, no JSON).
    otlp_headers = (
        f"arize-space-id={os.environ['ARIZE_SPACE_ID']},"
        f"authorization={os.environ['ARIZE_API_KEY']},"
        f"arize-interface=python"
    )

    runtime.launch(
        env_vars={
            "ARIZE_PROJECT_NAME": os.environ.get(
                "ARIZE_PROJECT_NAME", "bedrock-agentcore-cookbook"
            ),
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.arize.com:443",
            "OTEL_EXPORTER_OTLP_HEADERS": otlp_headers,
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            # Stop AgentCore double-exporting to CloudWatch when using a
            # non-AWS observability backend.
            "DISABLE_ADOT_OBSERVABILITY": "true",
        },
    )

    # First invoke after launch can take 60-120s (cold start).
    result = runtime.invoke(
        {"prompt": "What is Bedrock AgentCore and why does it pair well with Arize?"}
    )
    print(result)


if __name__ == "__main__":
    main()
