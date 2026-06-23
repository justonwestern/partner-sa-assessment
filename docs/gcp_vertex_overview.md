# Google Cloud Vertex AI + Arize

Vertex AI is Google Cloud's managed ML and GenAI platform: Vertex Model Garden, Vertex Agents, Vertex Pipelines for orchestration, and Gemini models natively integrated.

Arize integrates with Vertex through the OpenInference instrumentation for Google Vertex and via LangChain when customers use Vertex models through LangChain's ChatVertexAI. Phoenix captures every Gemini call as a span with input, output, latency, and token counts.

Surfaces that flow into Arize AX:
- Vertex Pipelines run metadata (used as experiment versions in AX)
- Vertex Model Garden model identifiers (attached as span attributes for cross-model comparison)
- Eval artifacts from Vertex's built-in evaluators (imported as AX datasets for regression tracking)

Co-sell motion with Google Cloud:
- Google Next main stage and Partner Summit sessions
- GCP Marketplace listing for Arize AX
- Joint architectures referenced in the GCP "Generative AI on Vertex" reference patterns

Typical Partner SA conversation: a Gemini-based agent in Vertex Agents hits prompt-injection or grounding regressions when traffic scales. Arize surfaces the regression with span-level evals and gives the engineering team a dataset to fix the prompt or retriever.
