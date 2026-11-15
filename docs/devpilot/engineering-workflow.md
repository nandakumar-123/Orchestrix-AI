# DevPilot Engineering Workflow & Approval Gating

DevPilot enforces a strict **Human-in-the-Loop** operating model. Code modifications cannot be generated, staged, or applied to repositories without explicit human authorization.

## Workflow Phases

```
1. Initiation (POST /repositories/{id}/devpilot/tasks)
   ├── Validate repository access and workspace tenant isolation
   └── Record task in CREATED status with initial timeline event

2. Context Retrieval & Analysis
   ├── Identify files of interest and affected AST symbols
   ├── Run semantic hybrid retrieval for conceptual context
   ├── Traverse Knowledge Graph callers to detect downstream impact
   └── Flag ambiguous requests into NEEDS_CLARIFICATION

3. Engineering Plan Formulation
   ├── Synthesize 14-section architectural plan
   ├── Evaluate baseline structural exposure with ImpactMind
   ├── Decompose into granular plan steps with risk ratings
   └── Transition to AWAITING_APPROVAL (Gate 1)

4. [HUMAN GATE 1] Plan Approval
   ├── User reviews summary, architecture, steps, and exposure score
   ├── If Approved: transitions to GENERATING
   └── If Rejected: transitions to CANCELLED or restarts planning with feedback

5. Code Generation & Sandbox Writing
   ├── Allocate isolated directory sandbox
   ├── Write generated source files and unit tests
   └── Calculate unified diff against repository snapshot

6. Automated Code Review
   ├── Inspect changes across 10 engineering dimensions
   ├── Check for out-of-scope files not in approved plan
   ├── Assign findings with severities (CRITICAL, HIGH, MEDIUM, LOW, INFO)
   └── Transition to AWAITING_MODIFICATION_APPROVAL (Gate 2)

7. [HUMAN GATE 2] Code Modification Approval
   ├── User inspects unified diff and code review findings
   ├── If Approved: transitions to APPLYING -> VALIDATING
   └── If Rejected: discards isolated sandbox and marks task REJECTED

8. Multi-Stage Validation
   ├── Tree-sitter AST parsing across registered languages
   ├── Post-change ImpactMind structural exposure re-assessment
   ├── Controlled test execution in sandboxed subprocess
   └── Transition to COMPLETED upon verification
```

## Human-in-the-Loop Approval Endpoints

### Gate 1: Plan Approval
- **Endpoint**: `POST /repositories/{id}/devpilot/tasks/{task_id}/approve-plan`
- **Request Body**:
  ```json
  {
    "approved": true,
    "feedback": "Proceed with token rotation, ensure 24h expiration"
  }
  ```
- **Permission Enforcement**: Any attempt to call `/generate` without an approved plan raises `HTTP 403 Forbidden` (`PermissionError`).

### Gate 2: Code Modification Approval
- **Endpoint**: `POST /repositories/{id}/devpilot/tasks/{task_id}/approve-changes`
- **Request Body**:
  ```json
  {
    "approved": true,
    "feedback": "Approved for validation"
  }
  ```
- **Audit Logging**: All approvals and rejections are permanently recorded in `devpilot_approvals` with user ID, timestamp, and review comments.
