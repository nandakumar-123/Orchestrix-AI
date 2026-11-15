# Controlled Test Runner: Security & Execution Safeguards

## 1. Security Architecture & Threat Model

Executing automated tests inherently involves running arbitrary or developer-supplied code. In multi-tenant environments, uncontrolled execution poses risks of shell injection, credential leakage, denial-of-service, and environment escaping.

The **ControlledTestRunner** in ImpactMind implements defense-in-depth safeguards:

```
[ User Request ]
       |
       v
[ Gate 1: Explicit User Approval (run_approved=true) ] ---> Reject if missing (400 Bad Request)
       |
       v
[ Gate 2: Workspace ADMIN Role Check ] --------------> Reject if unauthorized (403 Forbidden)
       |
       v
[ Gate 3: Command Allowlisting & Shell Sanitization ] -> Reject disallowed binaries / metacharacters (; && || | ` $ > <)
       |
       v
[ Gate 4: Working Directory Isolation ] ---------------> Reject outside workspace paths
       |
       v
[ Subprocess Launch with Timeout (60s) ]
       |
       v
[ Gate 5: Output Truncation (50KB limit) ]
       |
       v
[ Gate 6: Secret & Token Redaction Engine ]
       |
       v
[ Persist TestExecutionRun Record ]
```

---

## 2. Guardrails & Enforcement

### 2.1 Explicit User Approval Gate
Test execution cannot be triggered autonomously or implicitly. API requests to `POST /repositories/{id}/impact/{assessment_id}/tests/run` must provide `{"run_approved": true}`. In the frontend UI, this requires checking the "Explicitly Approve Execution" gate.

### 2.2 Command Allowlist
Only recognized test runners and prefixes are permitted:
- `pytest`
- `python -m pytest`
- `uv run pytest`
- `npm test`
- `npm run test`
- `npx vitest`
- `vitest`
- `go test`

Any other command (e.g. `rm`, `curl`, `bash`, `python -c`) is rejected immediately with a `ValueError`.

### 2.3 Shell Injection Metacharacter Rejection
Commands containing shell injection characters:
`;`, `&&`, `||`, `|`, `` ` ``, `$`, `>`, `<`, `\n`, `\r`
are rejected before subprocess creation.

### 2.4 Credential & Secret Redaction
All standard output and standard error text emitted during execution passes through regular expression sanitization before persistence:
- Bearer tokens, JWT tokens, AWS/GitHub/OpenAI API keys, and connection passwords matching standard patterns are masked with `[REDACTED_SECRET]`.

### 2.5 Resource Bounds & Cancellation
- **Timeout**: Enforced via `asyncio.wait_for(timeout=60.0)`. Timed-out jobs are killed (`proc.kill()`) and marked `TIMED_OUT`.
- **Output Limit**: Both `stdout` and `stderr` are truncated at `50 KB` to protect backend memory and database rows.
- **Cancellation**: Active executions can be terminated via `POST /repositories/{id}/impact/{assessment_id}/tests/cancel`.
