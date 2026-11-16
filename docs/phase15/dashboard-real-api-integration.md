# Phase 15 Step 1 — Dashboard Real API Integration

## 1. Overview & Objectives

In Phase 15 Step 1, the Orchestrix AI frontend dashboard was completely decoupled from hardcoded/mock data structures and connected to verified, authenticated backend APIs. The dashboard now faithfully represents the real-time operational posture, active repositories, autonomous AI agent states, task pipeline, security findings, change blast assessments, engineering memories, and visual workflows for the active workspace.

---

## 2. Dashboard Data-Source Audit & Hardcoded Data Removal

### Hardcoded Data Eliminated:
- **`SAMPLE_METRICS`**: Removed hardcoded repository, agent, and memory count figures. Replaced by `DashboardMetrics` calculated directly from the database per workspace.
- **`SPECIALIST_AGENTS`**: Removed fabricated operational statuses (`busy`, `operational`). Replaced by dynamic `AgentStatusSummary` derived from real backend task and workflow execution histories.
- **`SAMPLE_ACTIVITIES`**: Removed fabricated stream items (`"Indexed 1,420 files"`). Replaced by aggregated `ActivityEventItem` rows compiled across real task runs, workflow executions, security scans, impact assessments, and memory lifecycle operations.
- **`SAMPLE_TASKS`**: Removed static mock tasks. Replaced by `TaskSummaryItem` reflecting real `DevPilotTask` and `EngineeringTask` database models.
- **`SAMPLE_REPOSITORIES`**: Removed mock repo cards. Replaced by `RepositorySummary` reflecting active workspace repositories and their latest indexing jobs.

---

## 3. Backend Endpoints & Architecture

### New Authenticated Endpoint:
- **`GET /api/v1/dashboard/overview`**
  - **Security**: Requires active session authentication (`get_current_user`) and workspace membership (`require_workspace_membership(WorkspaceRole.VIEWER)`).
  - **Parameters**:
    - `workspace_id: UUID` (Required)
    - `repository_id: UUID | None` (Optional filter)
  - **Response Model**: `DashboardOverviewResponse` (defined in `backend/app/services/dashboard/schemas.py`).
  - **Service**: `DashboardService` (`backend/app/services/dashboard/dashboard_service.py`).

### Data Aggregations:
1. **Repository Aggregation**: Queries `Repository` and joins latest `IndexingJob` to compute connection and indexing status.
2. **Workflow Aggregation**: Queries `WorkflowDefinition`, `WorkflowExecution`, and `WorkflowApproval` scoped to workspace.
3. **Agent Status Synthesis**: Queries active and completed executions for `DevPilot`, `ImpactMind`, `TestPilot`, `SecureFlow`, `FlowForge`, and `DevMemory`. Derives status (`RUNNING`, `AVAILABLE`, `IDLE`, `FAILED`).
4. **Task Overview**: Aggregates `DevPilotTask` and `EngineeringTask` models ordered by recency.
5. **Security Summary**: Queries `SecureFlowFinding` and `SecureFlowScan` for open, confirmed, accepted, and resolved counts and severity distribution.
6. **Change Intelligence**: Queries `ImpactAssessment` for blast radius score and exposure tier.
7. **Engineering Memory**: Aggregates `EngineeringMemory` verification statuses (`VERIFIED`, `UNVERIFIED`, `OUTDATED`, `ARCHIVED`).
8. **Recent Activity Timeline**: Merges real-time timestamps across tasks, workflows, scans, and memory items into a unified audit feed.

---

## 4. Frontend Integration & Components

- **`frontend/src/lib/dashboard.ts`**: TypeScript API client with typed schemas for `DashboardOverviewResponse`.
- **`frontend/src/app/dashboard/page.tsx`**: Fully integrated client component with workspace reactivity, refresh actions, and error handling.
- **`frontend/src/components/dashboard/metric-cards.tsx`**: Displays verified workspace counts with navigation links.
- **`frontend/src/components/dashboard/orchestration-control.tsx`**: Live mesh status and agent topology linking to consoles.
- **`frontend/src/components/dashboard/agent-grid.tsx`**: Live agent status indicators with task run counters.
- **`frontend/src/components/dashboard/domain-intelligence.tsx`**: Specialized cards for SecureFlow, ImpactMind, DevMemory, and FlowForge.
- **`frontend/src/components/dashboard/repository-overview.tsx`**: Real repositories and indexing state.
- **`frontend/src/components/dashboard/activity-timeline.tsx`**: Real audit timeline.
- **`frontend/src/components/dashboard/recent-tasks.tsx`**: DevPilot active tasks and statuses.

---

## 5. Metric Traceability Matrix

| Dashboard Metric | Actual Data Source | API / Service | Verified |
|---|---|---|---|
| Connected Repositories | `repositories` table | `DashboardService.get_overview()` | Yes |
| Indexed Repositories | `repository_indexing_jobs` (COMPLETED) | `DashboardService.get_overview()` | Yes |
| Active Workflows | `workflow_definitions` (ACTIVE) | `DashboardService.get_overview()` | Yes |
| Workflow Executions | `workflow_executions` table | `DashboardService.get_overview()` | Yes |
| Pending Approvals | `workflow_approvals` (PENDING) | `DashboardService.get_overview()` | Yes |
| Engineering Memories | `engineering_memories` table | `DashboardService.get_overview()` | Yes |
| Verified Memories | `engineering_memories` (VERIFIED) | `DashboardService.get_overview()` | Yes |
| Open Security Findings | `secureflow_findings` (OPEN) | `DashboardService.get_overview()` | Yes |
| Running Tasks | `devpilot_tasks` & `engineering_tasks` | `DashboardService.get_overview()` | Yes |
| Total Tasks | `devpilot_tasks` & `engineering_tasks` | `DashboardService.get_overview()` | Yes |
| Impact Assessments | `impact_assessments` table | `DashboardService.get_overview()` | Yes |
| Agent Execution Counts | Task & execution logs | `DashboardService.get_overview()` | Yes |
| Audit Activity | Multi-model union | `DashboardService.get_overview()` | Yes |

---

## 6. Verification & Test Results

- **Backend Pytest**: 335 passed, 0 failed, 0 skipped.
- **Backend Ruff & MyPy**: 100% clean, 0 errors.
- **Frontend Vitest**: 86 passed, 3 skipped, 0 failed.
- **Frontend ESLint**: 0 errors, 0 warnings.
- **Frontend Next.js Production Build**: Turbopack compiled successfully, TypeScript passed, all 24 routes prerendered.
