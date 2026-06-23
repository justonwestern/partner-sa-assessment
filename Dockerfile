# Optional container image for the LOCAL track (TRACK A) of this assessment.
# Packages the Strands + Bedrock agent, the experiment harness, the evals, and
# the feedback loop into one image.
#
# Notes:
#   * The agent invokes Claude on Bedrock, so pass AWS credentials at runtime
#     (env or a mounted ~/.aws). MOCK_KB=true only mocks the KB retrieval, not
#     the LLM call.
#   * Point PHOENIX_ENDPOINT at a reachable Phoenix to capture / export spans.
#   * TRACK B (AgentCore) builds its own image via the starter toolkit; see
#     agentcore/.
#
# Build & run (zero-config smoke test, fully offline, no AWS/Phoenix needed):
#   docker build -t partner-sa-assessment .
#   docker run --rm partner-sa-assessment                 # -> mock KB retrieval
#
# Full harness against real Bedrock + Phoenix:
#   docker run --rm \
#     -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION=us-east-1 \
#     -e KB_ID=YOUR_KB_ID -e MOCK_KB=false \
#     -e OPENAI_API_KEY \
#     -e PHOENIX_ENDPOINT=http://host.docker.internal:6006 \
#     partner-sa-assessment python -m src.run_experiments
#
# Feedback loop:
#   docker run --rm -e OPENAI_API_KEY \
#     -e PHOENIX_ENDPOINT=http://host.docker.internal:6006 \
#     partner-sa-assessment python -m src.feedback_loop

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MOCK_KB=true \
    AWS_REGION=us-east-1 \
    PHOENIX_ENDPOINT=http://host.docker.internal:6006 \
    ARIZE_PROJECT_NAME=strands-agentcore-cookbook-local

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# App code + the canned MOCK_KB corpus (docs/*.md) used when MOCK_KB=true.
COPY src/ ./src/
COPY docs/ ./docs/

# Default to the offline KB smoke test so `docker run` works with zero config
# (no AWS, no Phoenix). Override the command to run the agent, the harness, or
# the feedback loop (see the header comment for examples).
CMD ["python", "-m", "src.tools"]
