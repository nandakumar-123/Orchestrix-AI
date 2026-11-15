# SecureFlow — Frontend Architecture & Integration Guide

## 1. Overview

The **SecureFlow** frontend dashboard (`/security`) provides a security analysis console for static application security testing (SAST), secret detection, vulnerability triage, and autonomous remediation through DevPilot.

It connects directly to the FastAPI backend (`/api/v1/repositories/{repo_id}/secureflow`) and contains zero mock data or hardcoded metrics: all vulnerability findings, severity distributions, scan runs, and scanner health statuses are derived from live backend responses.

---

## 2. Component Structure & Routes

- **Route**: `/security`
- **Page Component**: `frontend/src/app/security/page.tsx`
- **Client Service**: `frontend/src/lib/secureflow.ts`
- **Navigation**: Integrated in `frontend/src/components/navigation/sidebar.tsx` under `ENGINEERING` with `ShieldAlert` icon and badge `Phase 13`.
- **Test File**: `frontend/src/__tests__/secureflow.test.tsx`

---

## 3. Key Capabilities

### 3.1 Workspace & Repository Selection with RBAC
- Authenticates session using `fetchCurrentUser()` and loads accessible repositories.
- Displays current workspace role (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`).
- **Permission Enforcement**:
  - `VIEWER`: Read-only access to scan results and findings. Scan dispatch and triage forms are disabled.
  - `MEMBER` & above: Authorized to trigger scans, update lifecycle statuses, and dispatch DevPilot remediation tasks.

### 3.2 Dynamic Overview Stats
- **Critical**: Live count of unresolved critical severity vulnerabilities.
- **High**: Live count of high severity vulnerabilities.
- **Medium / Low**: Aggregated count of medium and low severity findings.
- **Latest Scan Status**: Visual badge (`COMPLETED`, `RUNNING`, `PARTIALLY_COMPLETED`, `FAILED`) reflecting latest repository scan.

### 3.3 Tabbed Agent Workspace
1. **Findings Explorer & Detail Drawer**:
   - Filter bar supporting multi-attribute filtering by **Severity** (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), **Status** (`OPEN`, `CONFIRMED`, `FALSE_POSITIVE`, `ACCEPTED_RISK`, `RESOLVED`), and **Category** (`secrets`, `sast`, `dependencies`).
   - Detailed findings table with severity indicators, rule IDs, and file/line locations.
   - Comprehensive Finding Detail Drawer:
     - Full advisory title, scanner engine, rule name, and fingerprint.
     - Vulnerability description and remediation recommendations.
     - Redacted evidence snippet ensuring secrets never leak to the UI.
     - Finding triage form to transition status with audit comments.
     - **DevPilot Remediation Bridge**: One-click action to create a DevPilot task (`remediateFinding`), with interactive link to navigate directly to `/devpilot`.
2. **Scan Runner & Audit History**:
   - Scan trigger form allowing scan mode selection (`FULL`, `SECRETS`, `DEPENDENCIES`, `SAST`) and optional subpath restrictions.
   - Real-time polling while status is `RUNNING`.
   - Comprehensive scan history table with counts breakdown (`Critical`, `High`, `Total`).
   - Detailed audit event timeline viewer (`SCAN_STARTED`, `SCANNER_STARTED`, `SCANNER_COMPLETED`, `FINDINGS_RECORDED`, etc.).
   - Explicit highlighting for `PARTIALLY_COMPLETED` scans if any scanners were unavailable on the host.
3. **Scanner Engine Status**:
   - Host tool availability cards for `secret_scanner`, `pip_audit`, `npm audit`, `OSV`, and `Semgrep`.
   - Displays binary paths, installed tool versions, and availability status.

---

## 4. API Client Interface (`src/lib/secureflow.ts`)

```typescript
export async function getScannerAvailability(repositoryId: string, workspaceId?: string): Promise<ScannerAvailabilityResponse>;
export async function startScan(repositoryId: string, payload?: StartScanPayload, workspaceId?: string): Promise<SecureFlowScan>;
export async function listScans(repositoryId: string, params?: ListScansParams): Promise<SecureFlowScanListResponse>;
export async function getScan(repositoryId: string, scanId: string, workspaceId?: string): Promise<SecureFlowScan>;
export async function getScanEvents(repositoryId: string, scanId: string, params?: ListEventsParams): Promise<SecureFlowScanEventListResponse>;
export async function listFindings(repositoryId: string, params?: ListFindingsParams): Promise<SecureFlowFindingListResponse>;
export async function getFinding(repositoryId: string, findingId: string, workspaceId?: string): Promise<SecureFlowFinding>;
export async function updateFindingStatus(repositoryId: string, findingId: string, status: FindingStatus, note?: string, workspaceId?: string): Promise<SecureFlowFinding>;
export async function remediateFinding(repositoryId: string, findingId: string, workspaceId?: string): Promise<RemediationTaskResponse>;
export async function getFindingRemediation(repositoryId: string, findingId: string, workspaceId?: string): Promise<RemediationTaskResponse | null>;
```
