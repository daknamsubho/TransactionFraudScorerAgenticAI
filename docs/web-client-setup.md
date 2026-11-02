# Step-by-Step Guide: Python Environment Setup & Running the Web Client (`src/web_client`)

This guide walks through setting up the Python environment on your local computer, starting the **Web Client UI (`src/web_client`)**, and connecting it to the **FastAPI Gateway (`src/api_gateway`)** running either in **Google Colab (via Cloudflare Tunnel)** or **locally**.

---

## 1. Prerequisites

- **Python**: `>= 3.11` (`3.11`, `3.12`, `3.13`, or `3.14`)
- **Git**: Installed on your machine
- **Package Manager**: [`uv`](https://docs.astral.sh/uv/) (recommended) or standard `venv` + `pip`

---

## 2. Step-by-Step Python Environment Setup

### Option A: Using `uv` (Recommended & Fastest)

1. **Install `uv`** (if not already installed):
   ```bash
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Or via Homebrew on macOS
   brew install uv
   ```

2. **Clone the repository and navigate to the project root**:
   ```bash
   git clone -b feature/local_models https://github.com/daknamsubho/TransactionFraudScorerAgenticAI.git
   cd TransactionFraudScorerAgenticAI
   ```

3. **Create the virtual environment and install all dependencies**:
   ```bash
   uv sync
   ```
   *(This automatically creates `.venv/` and installs `fraud_scorer`, `api_gateway`, and `web_client` in editable mode along with all required dependencies.)*

4. **(Optional) Activate the virtual environment in your shell**:
   ```bash
   source .venv/bin/activate
   ```

---

### Option B: Using Standard Python `venv` & `pip`

1. **Clone the repository and navigate to the project root**:
   ```bash
   git clone -b feature/local_models https://github.com/daknamsubho/TransactionFraudScorerAgenticAI.git
   cd TransactionFraudScorerAgenticAI
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Upgrade `pip` and install the project in editable mode**:
   ```bash
   pip install --upgrade pip
   pip install -e .
   ```

---

## 3. Step-by-Step: Running the Two-Page Web Client UI Locally

The Web Client is split into **two dedicated pages**:
1. **Page 1 — Submit Transaction (`http://127.0.0.1:3000/index.html`)**: Configure the API Gateway URL and submit `CARD` or `ACH` transactions (`POST /api/v1/transactions/score`).
2. **Page 2 — Decision Queue (`http://127.0.0.1:3000/queue.html`)**: Live WebSocket stream (`/ws/transactions/events`) displaying incoming scored transactions in a queue where analysts can inspect details and **Accept** or **Reject** transactions (`POST /api/v1/transactions/decision`).

1. **Start / Stop the Web Client Server** on port `3000`:
   - Using the helper Bash script (`src/web_client/webclient.sh`):
     ```bash
     # Start in background
     ./src/web_client/webclient.sh start --host 127.0.0.1 --port 3000

     # Check status
     ./src/web_client/webclient.sh status

     # Stop server
     ./src/web_client/webclient.sh stop
     ```
   - Or in the foreground using `uv`:
     ```bash
     uv run fraud-web-client --host 127.0.0.1 --port 3000
     ```
   - Or with an activated `.venv`:
     ```bash
     fraud-web-client --host 127.0.0.1 --port 3000
     ```
   - Or via Python module directly:
     ```bash
     uv run python -m web_client.server --host 127.0.0.1 --port 3000
     ```

2. **Open Both Pages in Your Browser**:
   - **Submit Page**: [`http://127.0.0.1:3000/index.html`](http://127.0.0.1:3000/index.html)
   - **Decision Queue Page**: [`http://127.0.0.1:3000/queue.html`](http://127.0.0.1:3000/queue.html) *(or click **"Open Decision Queue in New Tab ↗"** from the Submit page so you can watch the queue update live while submitting transactions!)*

---

## 4. Connecting the Web Client to the API Gateway

You can connect the Web Client to either a **Remote Google Colab Gateway (via Cloudflare Tunnel)** or a **Local FastAPI Gateway**.

### Scenario 1: Connecting to Google Colab via Cloudflare Tunnel

1. Open [`notebooks/colab_setup_and_run.ipynb`](../notebooks/colab_setup_and_run.ipynb) in Google Colab.
2. Run **Step 1** (Verify Hardware), **Step 2** (Clone & Install Dependencies), and **Step 3** (Start FastAPI Gateway & Expose via Cloudflare Tunnel).
3. Copy the printed **Public Base URL** from the output of Step 3, for example:
   ```text
   https://example-random-words.trycloudflare.com
   ```
4. In your local browser at `http://127.0.0.1:3000`:
   - Paste the `https://*.trycloudflare.com` URL into the **API Gateway Base URL** field at the top of the page.
   - Notice the **Derived WS Endpoint** automatically updates to `wss://example-random-words.trycloudflare.com/ws/transactions/events`.
   - Click **Check Health** to verify connectivity (`Health OK`).
   - Click **Connect WebSocket** — the badge will turn green (`CONNECTED`).

### Scenario 2: Connecting to a Local FastAPI Gateway

1. In a second terminal window on your computer, start the FastAPI Gateway on port `8000`:
   ```bash
   uv run fraud-api-gateway --host 127.0.0.1 --port 8000
   ```
   *(Add `--tunnel` if you also want to start a Cloudflare Tunnel locally: `uv run fraud-api-gateway --port 8000 --tunnel`.)*
2. In your browser at `http://127.0.0.1:3000`:
   - Leave **API Gateway Base URL** set to `http://localhost:8000`.
   - Click **Check Health** and **Connect WebSocket**.

---

## 5. Sending Transactions & Viewing Real-Time WebSocket Events

1. **Ensure WebSocket is Connected**:
   Verify the **WebSocket** status badge in the top bar reads `CONNECTED`.
2. **Load a Preset or Fill Out the Form**:
   - Click **Load Card Preset** to populate a sample `CARD` transaction, or **Load ACH Preset** to populate a sample `ACH` bank transfer.
   - Modify any fields (`Username`, `Amount`, `Latitude`/`Longitude`, `MCC`, `Card` or `ACH` details) as desired.
3. **Submit the Transaction (`POST /api/v1/transactions/score`)**:
   - Click **Submit Transaction for Fraud Scoring**.
   - The **Latest REST Score Response** box on the left will display the HTTP response (`transaction_id`, `score: 100.0`, `status: "APPROVE"`).
   - Simultaneously, the **Real-Time WebSocket Events (`/ws/transactions/events`)** table on the right will receive the pushed event row (`Transaction ID`, `Username`, `Amount`, `Score`, `Status`) and display the full JSON payload (including `score_details.request_payload`) in the **WebSocket Event Details** inspector.
4. **Accept or Reject a Transaction (`POST /api/v1/transactions/decision`)**:
   - Click **Accept** or **Reject** directly on any row in the WebSocket table (or enter a custom `Reason` in the **Submit Transaction Decision** section and click **Accept Transaction** / **Reject Transaction**).
   - The status badge in the table updates immediately to `ACCEPTED` or `REJECTED`.
