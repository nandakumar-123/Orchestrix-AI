# SecureFlow DevPilot Remediation Bridge

## Overview

The `DevPilotRemediationBridge` (`app.services.secureflow.remediation_bridge`) provides a controlled bridge connecting SecureFlow vulnerability findings directly to DevPilot for automated remediation.

## Operational Workflow

1. **Finding Ingestion**: Finding ID is retrieved from `secureflow_findings`.
2. **Pre-Remediation Secret Scrubbing**: All finding titles, descriptions, and code snippets are passed through `redact_secrets` before constructing the remediation prompt. This guarantees that remediation prompts never leak exposed credentials.
3. **DevPilot Task Creation**:
   - Creates a `DevPilotTask` record with `task_type = "SECURITY"`.
   - Populates structured prompt detailing the vulnerability, affected files, line numbers, and remediation guidance.
   - Sets initial task status to `CREATED`.
4. **Preservation of Human Approval Gates**:
   - The bridge strictly creates the task in the `CREATED` state.
   - The DevPilot agent will generate a remediation plan and wait for human review (`AWAITING_APPROVAL`).
   - Generated code changes require explicit modification approval before being applied.
   - Fixes are never committed, merged, or pushed automatically without user sign-off.
5. **Bidirectional Association**:
   - Updates `finding.devpilot_task_id` with the newly created task ID for complete end-to-end traceability.
