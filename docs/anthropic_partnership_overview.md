# Anthropic Claude + Arize

Anthropic's Claude family (Opus, Sonnet, Haiku) is increasingly the default model for high-stakes agentic workflows: long-context document analysis, tool use through the Claude Tools API, and Claude Code for engineering automation.

Phoenix instruments Claude API calls via the OpenInference Anthropic instrumentor. Every Claude invocation, including Tools API calls and thinking-block content, surfaces as a span in Phoenix or Arize AX with full input, output, latency, and token usage.

Surfaces relevant to a Partner SA:
- Claude Code workflows can stream traces to Phoenix locally for debugging agentic dev flows
- Production Claude-based agents (customer support, research, code review) emit span-level data Arize evaluates for hallucination, instruction-following, and tool-use correctness
- Arize publishes evaluation templates tuned for Claude's response style, including verbosity and refusal patterns

Co-sell motion with Anthropic:
- Joint customer enablement for enterprises standardizing on Claude as their primary model
- Claude evaluation patterns shared in Anthropic's Cookbook
- Partner-led workshops on "Evaluating Claude Agents in Production"

Typical Partner SA conversation: a customer migrates a critical agent from GPT-4 to Claude Sonnet for tool-use stability, and needs an apples-to-apples eval comparison to defend the migration to internal stakeholders. Arize provides the side-by-side dataset, the relevance and hallucination scores, and the regression gate.
