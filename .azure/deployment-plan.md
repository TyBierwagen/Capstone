# Azure Deployment Plan

Status: Approved

## Objective
Deploy a reliable Azure Function that copies newly arrived sensor readings from Azure Table Storage to the fixed Upstream campaign 4 / station 3 destination.

## Scope
- Modify the existing Python Azure Functions app.
- Preserve the current temperature, humidity, battery-only upload contract.
- Use the existing Upstream authentication and CSV upload flow.
- Avoid duplicate Upstream records using the existing upload ledger strategy.
- Deploy the Function App code and verify the live trigger.

## Architecture Decision
Reuse the existing queue-trigger architecture in `functions/function_app.py`:

1. `postSensorData` stores the reading in Azure Table Storage and writes the reading to the `upstream-upload` queue.
2. `syncSensorDataToUpstream` consumes that queue message.
3. The consumer authenticates with the documented Upstream token flow and uploads temperature, humidity, and battery CSV data.
4. Upload destination remains fixed at campaign `4` / station `3`, with default coordinates `30.665742, -96.326784`.

This avoids a second upload path and preserves queue retry behavior when Upstream is temporarily unavailable.

## Implementation Plan
- Verify the deployed Function App, storage connection, queue trigger metadata, and relevant app settings.
- Make the live queue consumer resilient and ensure its deployed code matches the tested uploader contract.
- Validate Python syntax, Function indexing, and the deployment package locally.
- Deploy only the Functions code using the existing `deploy-functions.bat` path.
- Restart and verify the Function App health endpoint and trigger metadata.
- Send one controlled sensor reading or inspect a newly arrived reading, then verify its Upstream measurement.

## Azure Context
- Subscription: to be confirmed before deployment.
- Resource group: resolved from Terraform output or confirmed explicitly.
- Location: existing Function App location; no infrastructure changes planned.

## Risk and Rollback
- No resource deletion or schema migration is planned.
- Existing queue messages remain in Azure Storage and can be retried by the trigger.
- Rollback is code-only: redeploy the prior Functions package if verification fails.

## Validation
Pending approval and Azure context confirmation.
