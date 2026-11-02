# PRD-002: Update API Gateway to Return the Score Request via Websocket

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
Before implementing the Fraud scorer system, I want to test if the request is going to API Gateway correctly and data is coming back via Websocket. I will build the Web UI based on this in later iterations. 

## 2. Requirements
I need
- API Gateway to return the Request in the format of Websocket response
- Score can be 100 for now
- All Transactions are successfull.

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the executing
- Update the code under `src\api_gateway` 

Details of the API can be found at `docs/openapi-spec/openapi.yaml`.

## 3. Out-of-scope
- Authenticated call to the API gateway
