# Phase 14 Step 3: DevMemory Core Engineering Memory Engine

## 1. Overview & Architecture

DevMemory is Orchestrix AI's persistent engineering memory engine. It acts as an organizational shared brain across all Orchestrix agents (`DevPilot`, `ImpactMind`, `TestPilot`, `SecureFlow`, and `FlowForge`), capturing architectural decisions, verified bug fixes, conventions, security guidance, test strategies, and empirical discoveries across workspace repositories.

### Key Architecture Principles:
1. **Evidence-Grounded Verification**:
   - A memory starts as `UNVERIFIED` and cannot transition to `VERIFIED` without concrete, empirical evidence (test results, code references, benchmark outcomes, or human review).
2. **Deterministic Deduplication**:
   - SHA-256 content hashing normalized across `workspace_id:memory_type:content` avoids duplicate records. Re-submitting identical engineering discoveries safely returns the existing canonical memory.
3. **Automated Secret Redaction**:
   - Every memory title, summary, source reference, and content payload is scrubbed by `redact_secrets` prior to database persistence and vector embedding.
4. **Tenant Isolation**:
   - All memories, evidence records, directional relationships, and audit logs are strictly scoped by `workspace_id` with composite foreign key constraints at both database and application level.
5. **Hybrid Semantic & Lexical Retrieval**:
   - Combines vector embeddings (`sentence-transformers/all-MiniLM-L6-v2` via `FastEmbedProvider`, 384 dimensions) with BM25-style lexical scoring, calibrated multipliers (+20% for `VERIFIED`, +10% for empirical evidence), and recency decay.
6. **Graceful Degradation**:
   - Primary agent workflows (DevPilot, TestPilot, SecureFlow) degrade gracefully if vector services or Neo4j Knowledge Graph providers are unavailable or offline.

---

## 2. Taxonomy & Models

### Core Enums
- **MemoryType** (12 types):
  `ARCHITECTURE_DECISION`, `TECHNICAL_DECISION`, `BUG_FIX`, `REPO_KNOWLEDGE`, `CODE_EXPLANATION`, `ENGINEERING_CONVENTION`, `REPOSITORY_CONVENTION`, `TASK_OUTCOME`, `IMPLEMENTATION_DISCOVERY`, `KNOWN_LIMITATION`, `VERIFIED_SOLUTION`, `SECURITY_KNOWLEDGE`, `TEST_KNOWLEDGE`, `DEPENDENCY_KNOWLEDGE`.
- **EvidenceType** (8 types):
  `CODE_REFERENCE`, `TEST_RESULT`, `COMMIT_DIFF`, `EXECUTION_LOG`, `PR_REVIEW`, `BENCHMARK`, `DOCUMENTATION`, `MANUAL_VERIFICATION`.
- **MemoryRelationshipType** (6 types):
  `EXTENDS`, `SUPERSEDES`, `CONTRADICTS`, `RELATES_TO`, `CAUSED_BY`, `RESOLVED_BY`.
  *Note: Establishing a `SUPERSEDES` relationship automatically transitions the target memory to `OUTDATED`.*
- **MemoryVerificationStatus** (4 lifecycle states):
  `UNVERIFIED`, `VERIFIED`, `OUTDATED`, `ARCHIVED`.

---

## 3. FlowForge Step 2.1 Follow-up Validation (Part H)

As part of Phase 14 Step 3, the FlowForge Step 2.1 execution reliability hardening was verified:
1. **Idempotency Keys over Title Matching**:
   - FlowForge agent node execution uses `workflow:{workflow_id}:{node_id}` and `execution:{execution_id}:{node_id}` idempotency keys embedded in task requests.
   - Independent tasks with identical titles remain distinct, preventing cross-task collisions while guaranteeing idempotent re-execution for identical steps.
2. **Crash Recovery Step Categorization**:
   - `SAFE_TO_RETRY_NODE_TYPES = {TRIGGER, NOTIFICATION, CONDITION, PARALLEL, MERGE, END}` are safely reset to `PENDING` upon recovery.
   - Unsafe agent mutation steps (`DEVPILOT`, `TESTPILOT`, `SECUREFLOW`, `AGENT_TASK`) are safely preserved as `FAILED` or left in their prior deterministic state without accidental duplicate side-effects.

---

## 4. Verification & Test Suite Summary

- **DevMemory Unit Tests** (`backend/tests/test_devmemory_unit.py`):
  - `test_memory_creation_lifecycle_and_redaction`: PASSED
  - `test_memory_deduplication_returns_existing`: PASSED
  - `test_verification_workflow_requires_evidence`: PASSED
  - `test_outdated_and_archived_lifecycle`: PASSED
  - `test_cross_workspace_memory_and_relationship_isolation`: PASSED
  - `test_relationship_supersession_marks_target_outdated`: PASSED
- **DevMemory Retrieval & Graph Tests** (`backend/tests/test_devmemory_retrieval_and_api.py`):
  - `test_hybrid_search_scoring_and_status_filtering`: PASSED
  - `test_context_builder_budget_and_containment`: PASSED
  - `test_graph_synchronization_and_resilience`: PASSED
- **FlowForge Security & Reliability Tests** (`backend/tests/test_flowforge_security.py`):
  - 9 tests PASSED (including crash recovery, approval RBAC, and title independence).
- **Backend Full Test Suite**:
  - `321 passed, 26 warnings in 328.05s`.
- **Static Analysis & Type Checking**:
  - `ruff check`: All checks passed.
  - `ruff format --check`: All formatted.
  - `mypy backend/app/services/devmemory backend/app/api/v1/devmemory.py`: Success (no issues found).
- **Frontend Verification**:
  - Vitest: 55 passed (3 skipped live mocks).
  - ESLint: Passed cleanly.
  - Production Build (`next build`): 19 routes compiled statically with zero errors.
