# Automated Feedback Loop Report

- traces evaluated: **13**
- rubric failures: 2
- frustrated turns: 2
- tool misselections: 6

## Flags
- :triangular_flag_on_post: TOOL-SELECTION miss rate 6/13 exceeds 20%

## Failure-theme histogram
- missing_citation: 1
- off_topic: 1

## Proposed prompt patch (stub, human-in-the-loop)
Dominant failure theme: **missing_citation**.

Proposed new <INSTRUCTIONS> line (HUMAN APPROVAL REQUIRED):
> Always cite the source doc in brackets, e.g. [aws_bedrock_overview.md].

PR stub: open a branch `feedback/missing_citation-fix`, append the line to the fenced <INSTRUCTIONS> block in src/local_agent.py SYSTEM_PROMPT, re-run `python -m src.run_experiments` and `python -m src.evaluators.llm_judge`, and attach the before/after metrics to the PR description.

## Sample failing traces
- **Q:** Trigger a retrieval tool error on purpose.
  - rubric: fail (The answer does not reference a specific source, failing the cited criterion.)
- **Q:** What is the best recipe for sourdough bread?
  - rubric: fail (The answer does not address the specific partner the user asked about, as it div)
