# Automated Feedback Loop Report

- traces evaluated: **6**
- rubric failures: 4
- frustrated turns: 1
- tool misselections: 3

## Flags
- :triangular_flag_on_post: RUBRIC failure rate 4/6 exceeds 30%
- :triangular_flag_on_post: TOOL-SELECTION miss rate 3/6 exceeds 20%

## Failure-theme histogram
- missing_citation: 4

## Proposed prompt patch (stub, human-in-the-loop)
Dominant failure theme: **missing_citation**.

Proposed new <INSTRUCTIONS> line (HUMAN APPROVAL REQUIRED):
> Always cite the source doc in brackets, e.g. [aws_bedrock_overview.md].

PR stub: open a branch `feedback/missing_citation-fix`, append the line to the fenced <INSTRUCTIONS> block in src/local_agent.py SYSTEM_PROMPT, re-run `python -m src.run_experiments` and `python -m src.evaluators.llm_judge`, and attach the before/after metrics to the PR description.

## Sample failing traces
- **Q:** Is us.anthropic.claude-sonnet-4-6 ready to invoke on Bedrock?
  - rubric: fail (stub: missing citation)
- **Q:** What is the best recipe for sourdough bread?
  - rubric: fail (stub: missing citation)
- **Q:** Trigger a retrieval tool error on purpose.
  - rubric: fail (stub: missing citation)
- **Q:** How does Arize integrate with AWS Bedrock?
  - rubric: fail (stub: missing citation)
