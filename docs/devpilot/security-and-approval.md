# DevPilot Security & Approval Controls

DevPilot is designed with enterprise security and strict tenant isolation as primary invariants.

## Security Controls Summary

| Threat Vector | Mitigation Strategy | Implementation |
|---|---|---|
| **Unauthorized Code Modification** | 2-Gate Human-in-the-Loop requirement | Plan approval and Code modification approval gating |
| **Path Traversal / Sandbox Escape** | Strict path normalization and root containment checks | `TaskWorkspaceManager.validate_relative_path` |
| **Credential Leakage** | Automated token masking & secret scrubbing | `mask_secrets` regex in LLM provider & diff engines |
| **Arbitrary Command Execution** | Strict allowlist for test execution | Commands restricted to `pytest`, `npm test`, `cargo test`, `go test` |
| **Resource Exhaustion** | Windows Job Objects / POSIX process isolation and execution timeouts | Hard caps on validation timeouts (default 30s) |
| **Cross-Tenant Data Exposure** | Multi-tenant scoping on all queries and operations | All DB queries filtered by `workspace_id` and `repository_id` |

## Approval Audit Trail

Every approval decision is recorded in the `devpilot_approvals` table with:
- `approval_type`: `PLAN_APPROVAL` or `MODIFICATION_APPROVAL`
- `status`: `APPROVED` or `REJECTED`
- `user_id`: ID of the authenticated user
- `rejection_reason`: Explanation if rejected
- `feedback`: User guidance for agent iteration
- `created_at`: Timestamp
