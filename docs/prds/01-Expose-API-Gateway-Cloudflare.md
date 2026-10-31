# PRD-001: Esxpose API Gateway for External Website consumption

## Status
- **Status**: Approved 


---
## 1. Executive Summary & Objective
My local computer is not resourcefull enough to use Local LLMs. However, I need to run the Website in my local computer mimcing the Client Server Microservice Architecture. Hence, I need to use Google Colab to run the LLM in GPU. Based on the Architecture `docs/architecture.md` I need to Injest the Transactions per user and run it through the Fraud scorer system.

## 2. Requirements
I need
- FAPI Gateway using Fast API to Injest RestAPI Request to pass to the Fraud scorer
- The Fast API endpoint need to be exposed using Cloudflare Tunneling

Do the following
- Update the `notebooks/colab_setup_and_run.ipynb` to add the steps that is required for the implementation
- Create a folder under src as àpi_gateway`to store any code rrequired to the Fast API gateway here

Details of the API can be found at `docs/openapi-spec/openapi.yaml`.

## 3. Out-of-scope
- Authenticated call to the API gateway
