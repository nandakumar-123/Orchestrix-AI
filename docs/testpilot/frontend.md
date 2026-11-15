# TestPilot — Frontend Architecture & Integration Guide

## 1. Overview

The **TestPilot** frontend dashboard (`/testing`) provides an interactive interface for autonomous software testing, framework detection, AI test synthesis, sandboxed test execution, and failure diagnosis.

It connects directly to the FastAPI backend (`/api/v1/repositories/{repo_id}/testpilot`) and strictly adheres to the zero-mock principle: all operational metrics, test suites, execution logs, and coverage stats are computed dynamically from real API responses.

---

## 2. Component Structure & Routes

- **Route**: `/testing`
- **Page Component**: `frontend/src/app/testing/page.tsx`
- **Client Service**: `frontend/src/lib/testpilot.ts`
- **Navigation**: Integrated in `frontend/src/components/navigation/sidebar.tsx` under `ENGINEERING` with `FlaskConical` icon and badge `Phase 13`.
- **Test File**: `frontend/src/__tests__/testpilot.test.tsx`

---

## 3. Key Capabilities

### 3.1 Workspace & Repository Selection with RBAC
- Resolves authenticated user session via `fetchCurrentUser()`.
- Supports multi-workspace switching and lists connected GitHub repositories.
- Displays current workspace role (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`).
- **Permission Enforcement**:
  - `VIEWER`: Read-only access across all views. Generation, execution, and approval buttons are disabled.
  - `MEMBER`: Allowed to run framework detection, synthesize test suites, execute approved suites, and run AI failure diagnoses.
  - `ADMIN` & `OWNER`: Full permissions including human approval gates (`Approve Suite` and `Reject Suite`).

### 3.2 Dynamic Overview Stats
- **Test Suites Created**: Total number of test suites generated for the active repository.
- **Latest Run Pass Rate**: Percentage of passed tests from the most recent test run (`passed / (passed + failed)`), or `"No runs yet"`.
- **Line Coverage**: Latest line coverage percentage or `"Not measured"`.
- **Branch Coverage**: Latest branch coverage percentage or `"Not measured"` when branch instrumentation is not configured.

### 3.3 Tabbed Agent Workspace
1. **Test Suites & Synthesis**:
   - Form to generate test suites targeting `pytest`, `unittest`, `vitest`, `jest`, `mocha`, or `custom`.
   - Supports test categories: `unit`, `integration`, `regression`, `edge_case`, and `negative`.
   - Interactive code inspector for generated test cases with edge-case flags and rationale.
   - Dual-action human approval gates (`Approve` and `Reject` with audit notes).
2. **Framework Detection**:
   - Subpath-aware detection runner (`detectFrameworks`).
   - Detailed framework cards showing config files, test directory, naming patterns, runner commands, confidence scores, and missing host binaries.
3. **Controlled Execution Runner**:
   - Sandboxed test execution with custom command override and configurable timeout.
   - Live polling while status is `RUNNING` or `PENDING`.
   - Real-time execution abort via `Cancel Execution`.
   - Live stdout and stderr streaming viewports.
   - Individual test outcomes table displaying status, runtime duration, failure messages, and tracebacks.
4. **AI Failure Diagnoser**:
   - Invoked when test executions encounter failing assertions (`diagnoseFailure`).
   - Surfaces automated root-cause analysis, actionable fix suggestions, confidence scores, and affected file paths.
5. **Coverage Dashboard**:
   - Historical coverage reports table (`listCoverageReports`).
   - Breakdown of uncovered files and functions in the latest report.

---

## 4. API Client Interface (`src/lib/testpilot.ts`)

```typescript
export async function detectFrameworks(repositoryId: string, subpath?: string, workspaceId?: string): Promise<DetectedFramework[]>;
export async function generateTestSuite(repositoryId: string, data: GenerateSuiteRequest, workspaceId?: string): Promise<TestPilotSuite>;
export async function listTestSuites(repositoryId: string, params?: ListSuitesParams): Promise<TestPilotSuiteListResponse>;
export async function approveTestSuite(repositoryId: string, suiteId: string, workspaceId?: string): Promise<TestPilotSuite>;
export async function rejectTestSuite(repositoryId: string, suiteId: string, reason?: string, workspaceId?: string): Promise<TestPilotSuite>;
export async function executeTestSuite(repositoryId: string, suiteId: string, options?: ExecuteOptions, workspaceId?: string): Promise<TestExecution>;
export async function getTestExecution(repositoryId: string, executionId: string, workspaceId?: string): Promise<TestExecution>;
export async function getTestResults(repositoryId: string, executionId: string, workspaceId?: string): Promise<IndividualTestResult[]>;
export async function listCoverageReports(repositoryId: string, params?: ListCoverageParams): Promise<CoverageReportListResponse>;
export async function diagnoseFailure(repositoryId: string, executionId: string, sourceContext?: string, workspaceId?: string): Promise<DiagnosisResponse>;
export async function cancelExecution(repositoryId: string, executionId: string, workspaceId?: string): Promise<TestExecution>;
export async function selectImpactTests(repositoryId: string, diffText: string, allTestFiles?: string[], workspaceId?: string): Promise<ImpactTestSelectionResponse>;
```
