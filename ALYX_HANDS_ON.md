# Hands-on with Alyx (prep item #6)

Goal: 30-45 minutes that earn you the line *"I've been in Alyx -- here's where
I'd take it with partners."* Do this AFTER Track A has pushed traces into your
AX space, so Alyx has real spans (yours) to work on. That is the whole point:
one work stream, not two.

## Prereqs
- Free Arize AX account at https://app.arize.com (you confirmed you'll create this).
- Track A run at least once so the `ARIZE_PROJECT_NAME` project has traces.

## Step 1 -- Generate a trace view (5 min)
1. Open your AX space and select your project.
2. Open the trace from `src/local_agent.py`: an `invoke_agent
   PartnerSolutionsAssistant` root span wrapping the `search_partner_docs` /
   `check_model_access` tool spans and the `chat` LLM span.
3. Click into a span. Note the prompt, response, token usage, and latency. This
   is the "trace view" -- screenshot it.

## Step 2 -- Have Alyx draft a code evaluator (15 min)
Open Alyx and run these prompts (paraphrased from Arize's own Alyx 2.0 examples):

- Error analysis -> eval:
  *"Review my traces, identify the most critical failure mode in the Partner
  Solutions Assistant, and turn it into an eval."*
- Then ask it to make that eval a **code evaluator** so you can compare it to the
  hand-written one in `src/evaluators/code_evaluator.py`.
- Trace debugging:
  *"Find spans where the assistant answered without citing a doc snippet, and
  explain why."*

Screenshot the evaluator Alyx generates. The interview gold is the comparison:
your `evaluate_groundedness` vs. Alyx's generated evaluator -- where they agree,
where Alyx caught something you didn't, and what you'd ship to a partner.

## Step 3 -- Prompt experimentation (10 min, optional but strong)
- *"Generate a small dataset for the Partner Solutions Assistant use case, create
  two prompt variants, attach an evaluation, and run an experiment."*
- This maps directly to Aparna's Prompt Learning research and your existing
  prompt-learning demo. Note the result honestly (even if variant B loses).

## The line for Jason
> "I spun up AX, piped my Strands-on-AgentCore agent's traces in, and used Alyx
> to turn a failure mode into a code evaluator in one prompt. Here's where I'd
> take that with AWS and NVIDIA partners: ship the notebook, then a webinar."

## Quotes you can safely use (verified, from Arize's official Alyx 2.0 post)
Use these as Arize's own framing -- attribute them to Arize, not to Jason
personally, unless you confirm he said them:
- *"You're no longer orchestrating tools. You're delegating intent."*
- *"Alyx changes the unit of work ... across the entire AI engineering lifecycle."*
- Their north star for Alyx: *"Cursor for AI engineering."*

## On the Observe 2026 keynote (June 4) -- do this yourself
I could not find a reliable transcript of Jason's specific keynote lines online,
and misquoting the CEO to his face is a downside you don't want. Pull 2-3 lines
straight from the recording instead:
- Search "Arize Observe 2026 keynote" on the Arize YouTube (@arizeai) and on
  https://arize.com/observe.
- Note exact phrasing + timestamp for 2-3 lines about Alyx / agents / the
  context-graph or eval-data thesis, and quote those back. If you can't confirm
  a line is his, attribute it to "the Observe keynote" rather than to Jason.
