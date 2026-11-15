# SecureFlow API Reference

SecureFlow is Orchestrix AI's application security analysis agent. It orchestrates automated security scanning across hardcoded secrets, software dependencies (`pip-audit`, `npm-audit`, `osv-scanner`), and static application code (`Semgrep` for OWASP Top 10 vulnerabilities). It enforces strict secret redaction across all stored records and API responses, provides lifecycle triage for findings, records immutable audit events, and interfaces seamlessly with DevPilot to create human-approved remediation tasks.

---

## Authentication & Authorization

All SecureFlow endpoints require:
1. **User Authentication**: Valid session cookie or `Authorization: Bearer <token>`.
2. **Workspace Role-Based Access Control (RBAC)**:
   - `VIEWER`: Read-only access (list/inspect scans, retrieve scanner availability, list/inspect findings, list scan audit events, inspect remediation link).
   - `MEMBER`: Operational security actions (start security scans, update finding triage status, request DevPilot remediation).
   - `ADMIN` or `OWNER`: Administrative policy access (workspace-level security administration and scanner configuration).
3. **Repository Scoping**: Repository must exist and belong to the verified workspace.
4. **CSRF Protection**: All state-changing requests (`POST`, `PATCH`, `DELETE`) require a valid `X-CSRF-Token` header.

Base prefix: `/api/v1/repositories/{repository_id}/secureflow`

---

## Role Permission Matrix

| Endpoint | Method | Path | Minimum Role | Resource Ownership Check | CSRF Protected |
|---|---|---|---|---|---|
| Start Security Scan | `POST` | `/{repository_id}/secureflow/scans` | `MEMBER` | Repository in workspace | Yes |
| List Security Scans | `GET` | `/{repository_id}/secureflow/scans` | `VIEWER` | Repository in workspace | No |
| Retrieve Scan Details | `GET` | `/{repository_id}/secureflow/scans/{scan_id}` | `VIEWER` | Scan in repository & workspace | No |
| Scanner Availability & Status | `GET` | `/{repository_id}/secureflow/scanners` | `VIEWER` | Repository in workspace | No |
| List Security Findings | `GET` | `/{repository_id}/secureflow/findings` | `VIEWER` | Repository in workspace | No |
| Retrieve Individual Finding | `GET` | `/{repository_id}/secureflow/findings/{finding_id}` | `VIEWER` | Finding in repository & workspace | No |
| Update Finding Triage Status | `PATCH` | `/{repository_id}/secureflow/findings/{finding_id}/status` | `MEMBER` | Finding in repository & workspace | Yes |
| Retrieve Scan Audit Events | `GET` | `/{repository_id}/secureflow/scans/{scan_id}/events` | `VIEWER` | Scan in repository & workspace | No |
| Request DevPilot Remediation | `POST` | `/{repository_id}/secureflow/findings/{finding_id}/remediate` | `MEMBER` | Finding in repository & workspace | Yes |
| Retrieve Remediation Task | `GET` | `/{repository_id}/secureflow/findings/{finding_id}/remediation` | `VIEWER` | Finding in repository & workspace | No |
| Security Policy Administration | `GET` | `/{repository_id}/secureflow/admin/policy` | `ADMIN` or `OWNER` | Repository in workspace | No |

---

## Scanner Lifecycle Statuses

- `COMPLETED`: All integrated scanners executed successfully.
- `PARTIALLY_COMPLETED`: One or more integrated scanners were unavailable on the system (e.g., Semgrep binary missing). **An unavailable scanner is never reported as a clean pass.**
- `FAILED`: Scan encountered a terminal execution failure.
- `RUNNING`: Analysis is actively in progress.
- `CANCELLED`: Scan was aborted.

---

## Endpoints

### 1. Start Security Scan
- **Method**: `POST /{repository_id}/secureflow/scans`
- **Role**: `MEMBER`
- **Description**: Triggers an automated multi-scanner security analysis against the repository working directory.
- **Request Body** (optional):
  ```json
  {
    "scan_type": "FULL",
    "snapshot_id": null,
    "subpath": null
  }
  ```
  *(Supported `scan_type` values: `FULL`, `SECRETS`, `DEPENDENCIES`, `SAST`)*
- **Response** (`201 Created`):
  ```json
  {
    "id": "771e4567-e89b-12d3-a456-426614174999",
    "workspace_id": "...",
    "repository_id": "...",
    "snapshot_id": null,
    "scan_type": "FULL",
    "status": "COMPLETED",
    "scanners_used": [
      {"scanner": "secret-scanner", "status": "COMPLETED"},
      {"scanner": "pip-audit", "status": "COMPLETED"},
      {"scanner": "semgrep", "status": "COMPLETED"}
    ],
    "total_findings": 2,
    "critical_count": 1,
    "high_count": 1,
    "medium_count": 0,
    "low_count": 0,
    "started_at": "2026-11-15T12:00:00Z",
    "completed_at": "2026-11-15T12:00:15Z",
    "created_at": "2026-11-15T12:00:00Z"
  }
  ```

### 2. List Security Scans
- **Method**: `GET /{repository_id}/secureflow/scans`
- **Role**: `VIEWER`
- **Query Parameters**:
  - `status`: Optional filter (`COMPLETED`, `PARTIALLY_COMPLETED`, `FAILED`, `RUNNING`)
  - `limit`: Integer (default 20, max 100)
  - `offset`: Integer (default 0)
- **Response** (`200 OK`):
  ```json
  {
    "items": [...],
    "total": 5,
    "limit": 20,
    "offset": 0
  }
  ```

### 3. Retrieve Scan Details
- **Method**: `GET /{repository_id}/secureflow/scans/{scan_id}`
- **Role**: `VIEWER`
- **Response** (`200 OK`): `SecureFlowScanResponse`.

### 4. Scanner Availability & Status
- **Method**: `GET /{repository_id}/secureflow/scanners`
- **Role**: `VIEWER`
- **Description**: Returns live system availability, binary paths, and readiness for all scanners.
- **Response** (`200 OK`):
  ```json
  {
    "scanners": [
      {
        "scanner": "secret-scanner",
        "category": "SECRET",
        "is_available": true,
        "details": "Native regex and Shannon entropy scanner with zero credential leakage"
      },
      {
        "scanner": "pip-audit",
        "category": "DEPENDENCY",
        "is_available": true,
        "details": "Python package vulnerability audit"
      },
      {
        "scanner": "semgrep",
        "category": "SAST",
        "is_available": true,
        "binary_path": "C:\\Tools\\semgrep.exe",
        "details": "Static application security testing for OWASP Top 10 vulnerabilities"
      }
    ],
    "all_available": true
  }
  ```

### 5. List Security Findings
- **Method**: `GET /{repository_id}/secureflow/findings`
- **Role**: `VIEWER`
- **Query Parameters**:
  - `severity`: Optional filter (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`)
  - `status`: Optional filter (`OPEN`, `CONFIRMED`, `FALSE_POSITIVE`, `ACCEPTED_RISK`, `RESOLVED`)
  - `category`: Optional filter (`SECRET`, `DEPENDENCY`, `SAST`)
  - `limit`: Integer (default 20, max 100)
  - `offset`: Integer (default 0)
- **Response** (`200 OK`):
  ```json
  {
    "items": [
      {
        "id": "...",
        "workspace_id": "...",
        "repository_id": "...",
        "scan_id": "...",
        "scanner": "secret-scanner",
        "category": "SECRET",
        "severity": "CRITICAL",
        "confidence": 1.0,
        "rule_id": "SEC001",
        "title": "Hardcoded API Key",
        "description": "Detected hardcoded credentials in app/config.py",
        "redacted_evidence": "API_SECRET = '[REDACTED_SECRET]'",
        "file_path": "app/config.py",
        "line_start": 14,
        "line_end": 14,
        "remediation_recommendation": "Migrate secret to environment variables",
        "fingerprint": "a3f5b7...",
        "status": "OPEN",
        "created_at": "2026-11-15T12:00:10Z",
        "updated_at": "2026-11-15T12:00:10Z"
      }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0
  }
  ```

### 6. Retrieve Individual Finding
- **Method**: `GET /{repository_id}/secureflow/findings/{finding_id}`
- **Role**: `VIEWER`
- **Response** (`200 OK`): `SecureFlowFindingResponse`.

### 7. Update Finding Triage Status
- **Method**: `PATCH /{repository_id}/secureflow/findings/{finding_id}/status`
- **Role**: `MEMBER`
- **Description**: Updates the lifecycle status of a finding (e.g. marking as `FALSE_POSITIVE` or `RESOLVED`).
- **Request Body**:
  ```json
  {
    "status": "FALSE_POSITIVE",
    "note": "Verified that this string is a synthetic mock token in unit tests."
  }
  ```
- **Response** (`200 OK`): Updated `SecureFlowFindingResponse`.

### 8. Retrieve Scan Audit Events
- **Method**: `GET /{repository_id}/secureflow/scans/{scan_id}/events`
- **Role**: `VIEWER`
- **Description**: Retrieves audit trail events logged during the scan execution. All event payloads are scrubbed of sensitive secrets.
- **Response** (`200 OK`):
  ```json
  {
    "items": [
      {
        "id": "...",
        "scan_id": "...",
        "event_type": "SCAN_STARTED",
        "message": "Initiated FULL security scan session.",
        "details": {"scan_type": "FULL"},
        "created_at": "2026-11-15T12:00:00Z"
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
  ```

### 9. Request DevPilot Remediation
- **Method**: `POST /{repository_id}/secureflow/findings/{finding_id}/remediate`
- **Role**: `MEMBER`
- **Description**: Converts the vulnerability into a DevPilot engineering remediation task. Enforces strict human approval boundaries before code changes are applied.
- **Response** (`200 OK`):
  ```json
  {
    "finding_id": "...",
    "devpilot_task_id": "...",
    "task_title": "[Security Remediation] Hardcoded API Key",
    "task_status": "CREATED",
    "requires_plan_approval": true,
    "requires_code_approval": true
  }
  ```

### 10. Retrieve Associated Remediation Task
- **Method**: `GET /{repository_id}/secureflow/findings/{finding_id}/remediation`
- **Role**: `VIEWER`
- **Description**: Returns the active DevPilot remediation task linked to this finding, or `null` if no remediation has been requested.
- **Response** (`200 OK`): `RemediationTaskResponse` or `null`.
