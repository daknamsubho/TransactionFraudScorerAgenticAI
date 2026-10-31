# PRD-003: Implement WebUI

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
I need to a Web UI to Send the Transactions and view the Websocket data.

## 2. Requirements
I need
- A Simple Web client that should injest Websockets
- Web client should be able to request using REST API
- HTML, CSS and JS/TS files should be seperated
- API Gateway URL should be configurable via UI

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing
- Update the code under `src\web_client` 

Details of the API can be found at `docs/openapi-spec/openapi.yaml`.

## 3. Out-of-scope
- Authenticated call to the API gateway
- Fancy JS Frameworks
