# TestPilot API Reference

TestPilot is Orchestrix AI's autonomous software testing agent. It detects testing frameworks, generates comprehensive test suites using LLMs and repository intelligence, enforces explicit human approval gates before writing or executing tests, runs test suites in isolated sandbox environments with Windows Job Object containment, parses granular individual test results, analyzes code coverage, diagnoses test failures, and selects prioritized regression tests using ImpactMind AST change analysis.

---

## Authentication & Authorization

All TestPilot endpoints require:
1. **User Authentication**: Valid session cookie or `Authorization: Bearer <token>`.
2. **Workspace Authorization**: Active workspace membership (`VIEWER` for read/detect operations, `MEMBER` or higher for generate, approve, reject, execute, diagnose, and cancel).
3. **Repository Scoping**: Repository must exist and belong to the verified workspace.
4. **CSRF Protection**: All state-changing requests (`POST`, `PATCH`, `DELETE`) require a valid `X-CSRF-Token` header.

Base prefix: `/api/v1/repositories/{repository_id}/testpilot`

---

## Endpoints

### 1. Detect Framework
- **Method**: `POST /{repository_id}/testpilot/detect`
- **Role**: `VIEWER`
- **Description**: Inspects repository root or subpath to identify test frameworks (`pytest`, `unittest`, `vitest`, `jest`, `mocha`), test directories, naming conventions, and local runner availability.
- **Request Body** (optional):
  ```json
  {
    "subpath": "packages/backend"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "language": "python",
    "framework": "pytest",
    "config_file": "pyproject.toml",
    "test_directory": "tests",
    "naming_convention": "test_*.py",
    "runner_command": "pytest",
    "is_available": true,
    "confidence": 0.95,
    "missing_requirements": []
  }
  ```

### 2. Generate Proposed Test Suite
- **Method**: `POST /{repository_id}/testpilot/suites`
- **Role**: `MEMBER`
- **Description**: Synthesizes a structured test suite using LLMs. **Never writes files or executes tests upon generation.** Persists suite in `GENERATED` status awaiting approval.
- **Request Body**:
  ```json
  {
    "framework": "pytest",
    "target_files": ["app/services/calculator.py"],
    "source_context": "def add(a: int, b: int) -> int: return a + b",
    "test_type": "unit",
    "snapshot_id": null,
    "symbols_info": [{"name": "add", "kind": "function"}]
  }
  ```
- **Response** (`201 Created`):
  ```json
  {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "workspace_id": "...",
    "repository_id": "...",
    "framework": "pytest",
    "target_files": ["app/services/calculator.py"],
    "test_type": "unit",
    "status": "GENERATED",
    "test_cases": [
      {
        "name": "test_add_basic",
        "description": "Tests positive integer addition",
        "test_type": "unit",
        "target_symbol": "add",
        "code": "def test_add_basic():\n    assert add(2, 3) == 5\n",
        "is_edge_case": false,
        "relevance_explanation": ""
      }
    ],
    "created_at": "2026-11-15T12:00:00Z",
    "approved_at": null,
    "approved_by": null
  }
  ```

### 3. List Test Suites
- **Method**: `GET /{repository_id}/testpilot/suites`
- **Role**: `VIEWER`
- **Query Parameters**:
  - `status`: Optional filter (`GENERATED`, `APPROVED`, `REJECTED`)
  - `limit`: Integer (default 20, max 100)
  - `offset`: Integer (default 0)
- **Response** (`200 OK`):
  ```json
  {
    "items": [...],
    "total": 1,
    "limit": 20,
    "offset": 0
  }
  ```

### 4. Retrieve Test Suite Details
- **Method**: `GET /{repository_id}/testpilot/suites/{suite_id}`
- **Role**: `VIEWER`
- **Response** (`200 OK`): Full `TestPilotSuiteResponse`.

### 5. Approve Test Suite
- **Method**: `POST /{repository_id}/testpilot/suites/{suite_id}/approve`
- **Role**: `MEMBER`
- **Description**: Explicit human approval gate. Transitions status from `GENERATED` to `APPROVED`.
- **Response** (`200 OK`): Updated `TestPilotSuiteResponse` with `approved_at` and `approved_by`.

### 6. Reject Test Suite
- **Method**: `POST /{repository_id}/testpilot/suites/{suite_id}/reject`
- **Role**: `MEMBER`
- **Request Body** (optional):
  ```json
  {
    "reason": "Test cases do not meet project guidelines"
  }
  ```
- **Response** (`200 OK`): Updated `TestPilotSuiteResponse` with status `REJECTED`.

### 7. Execute Approved Test Suite
- **Method**: `POST /{repository_id}/testpilot/suites/{suite_id}/execute`
- **Role**: `MEMBER`
- **Description**: Staged execution in an isolated task workspace. **Rejects unapproved suites with HTTP 403 Forbidden.** Validates custom commands against strict framework allowlists (`pytest`, `unittest`, `vitest`, `jest`, `mocha`).
- **Request Body**:
  ```json
  {
    "custom_command": null,
    "timeout_seconds": 120
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "id": "e8a93941-b062-47ef-a0f5-3c1a89cfa111",
    "suite_id": "123e4567-e89b-12d3-a456-426614174000",
    "workspace_id": "...",
    "repository_id": "...",
    "command": "pytest -v",
    "status": "PASSED",
    "exit_code": 0,
    "duration_ms": 145,
    "passed_count": 1,
    "failed_count": 0,
    "skipped_count": 0,
    "error_message": null,
    "stdout": "...",
    "stderr": "",
    "executed_at": "2026-11-15T12:05:00Z",
    "created_at": "2026-11-15T12:05:00Z"
  }
  ```

### 8. Retrieve Test Execution Details
- **Method**: `GET /{repository_id}/testpilot/executions/{execution_id}`
- **Role**: `VIEWER`
- **Response** (`200 OK`): `TestExecutionResponse`.

### 9. Retrieve Individual Test Results
- **Method**: `GET /{repository_id}/testpilot/executions/{execution_id}/results`
- **Role**: `VIEWER`
- **Query Parameters**:
  - `status`: Optional filter (`PASSED`, `FAILED`, `SKIPPED`, `ERROR`)
- **Response** (`200 OK`):
  ```json
  [
    {
      "id": "...",
      "execution_id": "...",
      "test_name": "tests/test_calculator.py::test_add_basic",
      "status": "PASSED",
      "duration_ms": 12,
      "failure_message": null,
      "traceback": null
    }
  ]
  ```

### 10. List Coverage Reports
- **Method**: `GET /{repository_id}/testpilot/coverage`
- **Role**: `VIEWER`
- **Query Parameters**:
  - `execution_id`: Optional filter by execution
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
        "execution_id": "...",
        "line_coverage_pct": 91.2,
        "branch_coverage_pct": 84.0,
        "uncovered_files": ["app/legacy.py"],
        "uncovered_functions": [],
        "created_at": "2026-11-15T12:06:00Z"
      }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0
  }
  ```

### 11. Diagnose Test Failures
- **Method**: `POST /{repository_id}/testpilot/executions/{execution_id}/diagnose`
- **Role**: `MEMBER`
- **Description**: Parses tracebacks, performs secret scrubbing, and provides root-cause diagnosis and non-destructive remediation suggestions via LLM.
- **Request Body** (optional):
  ```json
  {
    "source_context": "Optional relevant code snippets"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "failing_test": "tests/test_pay.py::test_charge",
    "error_message": "ValueError: Invalid currency",
    "traceback_parsed": {"frames": [...]},
    "root_cause_analysis": "Missing uppercase normalization on currency code.",
    "fix_suggestions": ["Ensure currency string is converted with .upper()"],
    "affected_files": ["app/pay.py"],
    "confidence": 0.94,
    "target_symbol": "charge"
  }
  ```

### 12. Select Regression Tests via ImpactMind
- **Method**: `POST /{repository_id}/testpilot/impact/select`
- **Role**: `VIEWER`
- **Description**: Analyzes unified git diff using Phase 11 ImpactMind intelligence to recommend prioritized regression tests and calculate a structural change exposure score.
- **Request Body**:
  ```json
  {
    "diff_text": "diff --git a/app/pay.py b/app/pay.py...",
    "all_test_files": ["tests/test_pay.py", "tests/test_math.py"]
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "selected_tests": [{"test_file": "tests/test_pay.py", "priority": "HIGH"}],
    "impacted_symbols": ["charge"],
    "risk_exposure_score": 0.42,
    "change_summary": "1 file modified, 1 function signature altered",
    "rationale": ["Impacts payment processing pipeline"]
  }
  ```

### 13. Cancel Test Execution
- **Method**: `POST /{repository_id}/testpilot/executions/{execution_id}/cancel`
- **Role**: `MEMBER`
- **Description**: Terminates active test process and marks execution as `CANCELLED`.
- **Response** (`200 OK`): Updated `TestExecutionResponse`.
