# Running in Google Colab

This directory contains the ready-to-run interactive Jupyter Notebook for deploying and evaluating **Transaction Fraud Scorer Agentic AI** using **LangChain** and **Ollama** in Google Colab.

---

## 🚀 Quick Instructions to Run in Colab

### Option 1: Open Directly in Colab via GitHub
1. Go to [Google Colaboratory](https://colab.research.google.com/).
2. Click **File** ➔ **Open notebook** ➔ **GitHub** tab.
3. Enter repository URL: `https://github.com/daknamsubho/TransactionFraudScorerAgenticAI`
4. Select `notebooks/colab_setup_and_run.ipynb`.
5. *(Recommended)* Under **Runtime** ➔ **Change runtime type**, select **T4 GPU** for faster inference (though CPU also works).
6. Click **Runtime** ➔ **Run all** (or step through cell by cell).

### Option 2: Upload Notebook Manually
1. Download or locate [`notebooks/colab_setup_and_run.ipynb`](./colab_setup_and_run.ipynb).
2. Go to [Google Colab](https://colab.research.google.com/) and click **Upload**.
3. Select `colab_setup_and_run.ipynb`.
4. Run the cells sequentially.

---

## 📋 What the Notebook Executes

1. **Step 1: Hardware Check**: Verifies T4 GPU or CPU availability.
2. **Step 2: Ollama Daemon Setup**: Installs Ollama via official installer and starts `ollama serve` on `http://localhost:11434`.
3. **Step 3: Model Download**: Pulls `llama3.2:3b` (~2.0 GB) with native tool/function calling support.
4. **Step 4: Package Installation**: Installs `langchain`, `langchain-ollama`, `mcp`, `pydantic`, and `rich`.
5. **Step 5: MCP Tool Verification**: Tests LangChain tool adapters for Velocity, Geo Anomaly, Merchant Risk, and Account History.
6. **Step 6: LangChain Orchestrator**: Connects `FraudScorerOrchestrator` to `ChatOllama`.
7. **Step 7 & 8: Scenario Evaluations**: Scores both safe ($42.50) and fraudulent ($3,500.00 with impossible travel) transactions.
8. **Step 9: Custom Evaluator**: Interactive cell to test custom transactions.
