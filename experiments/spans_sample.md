# Span export sample

A small, human-readable excerpt of the spans exported from local Phoenix by `run_experiments.py` (Step 4). The full export (`spans.parquet` + `.csv`) is gitignored for size; regenerate with `python -m src.run_experiments` against a running `phoenix serve`.

## Span-kind distribution (full export)

| span_kind | count |
|---|---|
| CHAIN | 85 |
| LLM | 82 |
| AGENT | 48 |
| RETRIEVER | 45 |
| UNKNOWN | 45 |
| TOOL | 36 |

## One representative trace (nested)

**Query:** How does Arize integrate with AWS Bedrock for agentic RAG?

| span | kind | latency (ms) | tokens | tool |
|---|---|---:|---:|---|
| agent_turn | UNKNOWN | 6521 |  |  |
| retrieve_partner_docs | RETRIEVER | 0 |  |  |
| invoke_agent PartnerSolutionsAssistant | AGENT | 5980 | 11197 |  |
| execute_event_loop_cycle | CHAIN | 2027 |  |  |
| chat | LLM | 1473 | 2889 |  |
| execute_tool search_partner_docs | TOOL | 552 |  | search_partner_docs |
| execute_event_loop_cycle | CHAIN | 3953 |  |  |
| chat | LLM | 3951 | 4482 |  |

The `agent_turn` wrapper holds the whole turn in one trace; the manual `retrieve_partner_docs` RETRIEVER span sits beside the agent's LLM/tool spans.

## Custom RETRIEVER span attributes (the Step 3 manual instrumentation)

- `openinference.span.kind` = `RETRIEVER`
- `kb_id` = `SLVVH8SNKQ`
- `input.value` = How does Arize integrate with AWS Bedrock for agentic RAG?

| # | retrieval.documents.{i}.document.id | score |
|---|---|---:|
| 0 | aws_bedrock_overview.md | 0.806 |
| 1 | databricks_mosaic_overview.md | 0.492 |
| 2 | gcp_vertex_overview.md | 0.466 |
| 3 | nvidia_nemo_overview.md | 0.425 |

_Full span content (document text, per-span token counts, latency_ms) is preserved in the gitignored parquet/csv export._