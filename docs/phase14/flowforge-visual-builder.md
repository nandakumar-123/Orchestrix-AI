# FlowForge Visual Workflow Builder — Phase 14 Step 4

## Overview

FlowForge Visual Workflow Builder is an interactive, production-grade node-based visual workflow editor integrated into Orchestrix AI. It enables engineering teams to visually compose, validate, activate, and execute autonomous multi-agent pipelines with full separation of duties and RBAC enforcement.

---

## Architecture & Routes

The builder is integrated into the Next.js frontend with five primary routes:

| Route | Purpose | Key Capabilities |
|---|---|---|
| `/workflows` | Workflow Catalog & Management | List workflows with status filters (Draft, Active, Paused, Archived), activate/pause controls, metadata summary, execution shortcuts |
| `/workflows/new` | New Workflow Canvas | Interactive drag-and-drop workflow designer initialized with a blank canvas and instant creation |
| `/workflows/[workflowId]` | Visual Workflow Editor | Live React Flow canvas, node palette, configuration drawer, draft saving, server-side graph validation, version publishing, execution trigger |
| `/workflows/[workflowId]/executions` | Execution History | Execution run timeline with statuses, start/completion times, durations, error summaries, and direct cancellation |
| `/workflows/executions/[executionId]` | Execution Detail & Approvals | Interactive execution canvas overlay (visualizing node execution statuses: completed, running, failed, timed out), audit event timeline, human-in-the-loop approval decision gates |

---

## Canvas & Graph Serialization Layer

The editor is built on `@xyflow/react` (React Flow) and bridges bidirectional conversions between the UI graph and the backend schema:

```
[React Flow Nodes & Edges]
       ▲                 │
       │                 ▼
backendGraphToReactFlow()  reactFlowToBackendGraph()
       ▲                 │
       │                 ▼
[FlowForge Backend WorkflowGraphDefinition]
{
  "nodes": WorkflowNodeDefinition[],
  "connections": WorkflowNodeConnection[]
}
```

- **Node Positions**: Automatically persisted in `node.config._position` so canvas layout coordinates round-trip faithfully without backend schema modifications.
- **Condition Branches**: Edge `sourceHandle` identifiers (`true`, `false`) map directly to `WorkflowNodeConnection.condition_branch`.
- **Execution Overlays**: Node execution statuses (`WorkflowStepStatus`) and error traces are mapped directly into node visual cards at runtime.

---

## Node Catalog (11 Node Types)

The visual canvas supports all 11 FlowForge node types:

1. **TRIGGER** (`Zap`): Webhook, cron schedule, manual, or repository event triggers.
2. **DEVPILOT** (`Code2`): Autonomous engineering tasks with task titles, types, and repository scopes.
3. **IMPACTMIND** (`Network`): Blast radius and change impact analysis with target branches.
4. **TESTPILOT** (`FlaskConical`): Automated test suite generation with framework detection and file targeting.
5. **SECUREFLOW** (`Shield`): Security vulnerability scanning with risk thresholds.
6. **CONDITION** (`GitFork`): Deterministic branching logic with `true` and `false` outbound ports.
7. **APPROVAL** (`UserCheck`): Human-in-the-loop checkpoint gate reserved for `ADMIN` or `OWNER` review.
8. **PARALLEL** (`Split`): Multi-branch fan-out execution.
9. **MERGE** (`GitMerge`): Branch barrier convergence.
10. **NOTIFICATION** (`Bell`): Slack, email, or webhook notification dispatch.
11. **END** (`StopCircle`): Terminal workflow boundary.

---

## Security & RBAC Enforcement

The frontend strictly respects workspace authority rules aligned with backend authorization policies:

| Role | Catalog & Viewing | Canvas Editing & Saving | Activation & Execution | Checkpoint Approvals |
|---|---|---|---|---|
| **VIEWER** | Read-Only | Read-Only canvas | Disabled | Disabled |
| **MEMBER** | Full access | Full editing | Enabled | Disabled (View only) |
| **ADMIN** | Full access | Full editing | Enabled | **Enabled** (Approve & Reject) |
| **OWNER** | Full access | Full editing | Enabled | **Enabled** (Full authority) |

- **Separation of Duties**: Requester cannot approve their own checkpoint.
- **CSRF Protection**: All state-modifying requests (`POST`, `PATCH`, `DELETE`) automatically attach `X-CSRF-Token` headers.
- **Zero Mock Fallback**: Production views query live workspace-scoped API endpoints (`/api/v1/workflows`).

---

## Verification & Test Results

- **Unit & Integration Suite**:
  - `frontend/src/__tests__/flowforge.test.tsx`: 20/20 passed
  - Full frontend suite: 75 passed, 3 skipped (live integration placeholders)
  - Backend FlowForge regression (`test_flowforge_core.py`, `test_flowforge_security.py`): 25/25 passed
- **Static Quality**:
  - TypeScript: Zero errors across 23 Next.js routes
  - ESLint: Zero errors
  - Next.js Turbopack production build: 23 routes successfully compiled
