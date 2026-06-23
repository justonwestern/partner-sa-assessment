# Databricks (Mosaic AI) + Arize

Databricks customers use Mosaic AI for fine-tuning, model serving, vector search, and the Databricks Agent Framework. MLflow is the native experiment tracker on Databricks.

The common Partner SA question: "We already have MLflow for experiment tracking. Why do we need Arize?" The honest answer is:

- MLflow tracks training-time experiments and registered model versions
- Arize tracks production behavior, runtime traces, agent tool-use trees, and online evals
- The two are complementary, not duplicative. Arize ingests MLflow run IDs and attaches them to AX experiments so the same model can be evaluated offline (MLflow) and observed online (AX) with a single pane of glass

Phoenix instruments Databricks Agent Framework via the LangChain wrapper most customers use, and the OpenInference DSPy instrumentor for customers using DSPy on Databricks.

Co-sell motion with Databricks:
- Joint reference architecture published on databricks.com
- Databricks Data + AI Summit booth presence
- Pipeline pairing with Databricks Solutions Architects on Mosaic AI customers

Typical Partner SA conversation: a Mosaic AI customer ships a Llama-fine-tuned agent to production, sees retrieval quality drop on real traffic, and needs a way to evaluate retrieval relevance per span. Arize fills that gap.
