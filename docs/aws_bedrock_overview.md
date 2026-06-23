# AWS Bedrock + Arize

Amazon Bedrock is the AWS-native managed service for foundation models (Anthropic Claude, Meta Llama, Amazon Titan, Mistral, Cohere). Customers building agentic RAG on Bedrock typically pair it with:

- Bedrock Knowledge Bases for retrieval
- Bedrock Agents for tool use
- LangChain or AWS Strands for orchestration

Arize fits as the observability and evaluation backbone above Bedrock. The Phoenix OSS distribution traces every Bedrock invocation via OpenInference. Arize AX (the enterprise platform) adds production-grade controls: long-term trace retention, prompt and dataset versioning, online evals, and role-based access for partner-managed deployments.

Co-sell motion with AWS:
- AWS re:Invent main stage and AWS Partner Network breakouts
- Joint workshops branded "Evaluating and Observing AI on AWS"
- Sales pairing with AWS ProServe and Bedrock specialist sellers on customer POCs

Typical Partner SA conversation: a Bedrock customer launches an agentic RAG pilot, hits hallucination or tool-call latency issues in UAT, and needs trace-level visibility to debug. Arize provides the trace tree, the span-level eval, and the regression dataset to gate the production rollout.
