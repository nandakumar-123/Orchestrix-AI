import json
import urllib.error
import urllib.request
import uuid

import pytest

from app.db.session import get_async_session_factory
from app.services.auth import create_auth_session, generate_csrf_token

BASE_URL = "http://localhost:8000"
REPO_ID = "5866ba57-370a-459d-ba63-c505e3bc9a72"
WORKSPACE_ID = "b0191f43-86a3-42fc-a169-c7c8ba88b433"
USER_ID = "8207f222-0d0b-462a-aeff-06560dc07a0a"


@pytest.mark.asyncio
async def test_live_backend_full_workflows():
    # Check if live server is running on localhost:8000
    try:
        with urllib.request.urlopen("http://localhost:8000/api/v1/health", timeout=2) as resp:
            if resp.status != 200:
                pytest.skip("Local test server is not running on port 8000")
    except Exception:
        pytest.skip("Local test server is not running on port 8000")

    # 1. Create real authenticated session in Neon DB
    factory = get_async_session_factory()
    async with factory() as session:
        auth_session, raw_token = await create_auth_session(session, uuid.UUID(USER_ID))
        csrf = generate_csrf_token()

    session_cookie = f"orchestrix_session={raw_token}; orchestrix_csrf={csrf}"
    headers = {
        "Cookie": session_cookie,
        "X-CSRF-Token": csrf,
        "Origin": "http://localhost:3000",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    def api_call(path, method="GET", body=None):
        url = f"{BASE_URL}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                res_body = json.loads(resp.read().decode("utf-8"))
                return status, res_body
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
            except Exception:
                err_json = {"raw": err_body}
            return e.code, err_json

    # Test /api/v1/auth/me
    status, me = api_call("/api/v1/auth/me")
    assert status == 200, f"Expected 200 from /auth/me, got {status}: {me}"
    assert me["email"] == "nandakumaranandrajan@gmail.com"
    print("SUCCESS: Authenticated /auth/me with live session token")

    # -------------------------------------------------------------------------
    # TestPilot Workflow A: Framework Detection
    # -------------------------------------------------------------------------
    status, det = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/detect?workspace_id={WORKSPACE_ID}",
        method="POST",
        body={},
    )
    assert status == 200, f"Detect failed: {det}"
    assert "framework" in det
    print(
        f"SUCCESS: TestPilot detect returned framework={det['framework']}, language={det['language']}, available={det['is_available']}"
    )

    # -------------------------------------------------------------------------
    # TestPilot Workflow B: AI Test Generation
    # -------------------------------------------------------------------------
    gen_payload = {
        "framework": "pytest",
        "target_files": ["services/timer.py"],
        "source_context": "class TimeTracker:\n    def __init__(self):\n        self.entries = []\n    def start(self, name):\n        self.entries.append(name)\n        return len(self.entries)",
        "test_type": "unit",
    }
    status, suite = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/suites?workspace_id={WORKSPACE_ID}",
        method="POST",
        body=gen_payload,
    )
    assert status == 201, f"Generate suite failed: {suite}"
    suite_id = suite["id"]
    assert suite["status"].upper() == "GENERATED"
    assert len(suite["test_cases"]) > 0
    print(f"SUCCESS: TestPilot suite generated id={suite_id}, cases={len(suite['test_cases'])}")

    # -------------------------------------------------------------------------
    # TestPilot Workflow C: Approval & Execution
    # -------------------------------------------------------------------------
    status, approved_suite = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/suites/{suite_id}/approve?workspace_id={WORKSPACE_ID}",
        method="POST",
    )
    assert status == 200, f"Approve failed: {approved_suite}"
    assert approved_suite["status"].upper() == "APPROVED"
    print(f"SUCCESS: TestPilot suite approved by {approved_suite['approved_by']}")

    status, execution = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/suites/{suite_id}/execute?workspace_id={WORKSPACE_ID}",
        method="POST",
        body={"timeout_seconds": 60},
    )
    assert status == 200, f"Execute failed: {execution}"
    execution_id = execution["id"]
    print(f"SUCCESS: TestPilot suite executed id={execution_id}, status={execution['status']}")

    status, results = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/executions/{execution_id}/results?workspace_id={WORKSPACE_ID}"
    )
    assert status == 200, f"Results failed: {results}"
    print(f"SUCCESS: TestPilot execution results count={len(results)}")

    # -------------------------------------------------------------------------
    # TestPilot Workflow D: AI Failure Diagnosis
    # -------------------------------------------------------------------------
    status, diag = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/executions/{execution_id}/diagnose?workspace_id={WORKSPACE_ID}",
        method="POST",
        body={"source_context": "AssertionError: 2 != 1 in test_start_tracker"},
    )
    assert status == 200, f"Diagnose failed: {diag}"
    assert "root_cause_analysis" in diag
    print(
        f"SUCCESS: TestPilot diagnosis returned root_cause_analysis length={len(diag['root_cause_analysis'])}"
    )

    # -------------------------------------------------------------------------
    # TestPilot Workflow E: Coverage
    # -------------------------------------------------------------------------
    status, cov = api_call(
        f"/api/v1/repositories/{REPO_ID}/testpilot/coverage?workspace_id={WORKSPACE_ID}"
    )
    assert status == 200, f"Coverage failed: {cov}"
    print(f"SUCCESS: TestPilot coverage reports total={cov['total']}")

    # -------------------------------------------------------------------------
    # SecureFlow Workflow A: Scanner Availability
    # -------------------------------------------------------------------------
    status, scanners = api_call(
        f"/api/v1/repositories/{REPO_ID}/secureflow/scanners?workspace_id={WORKSPACE_ID}"
    )
    assert status == 200, f"Scanners failed: {scanners}"
    scanner_names = [s["scanner"] for s in scanners["scanners"]]
    assert "secret-scanner" in scanner_names
    print(f"SUCCESS: SecureFlow scanners availability returned: {scanner_names}")

    # -------------------------------------------------------------------------
    # SecureFlow Workflow B: Security Scan
    # -------------------------------------------------------------------------
    status, scan = api_call(
        f"/api/v1/repositories/{REPO_ID}/secureflow/scans?workspace_id={WORKSPACE_ID}",
        method="POST",
        body={"scan_type": "SECRETS"},
    )
    assert status == 201, f"Start scan failed: {scan}"
    scan_id = scan["id"]
    assert scan["status"] in ("COMPLETED", "PARTIALLY_COMPLETED", "RUNNING")
    print(
        f"SUCCESS: SecureFlow scan executed id={scan_id}, status={scan['status']}, findings={scan['total_findings']}"
    )

    status, events = api_call(
        f"/api/v1/repositories/{REPO_ID}/secureflow/scans/{scan_id}/events?workspace_id={WORKSPACE_ID}"
    )
    assert status == 200, f"Events failed: {events}"
    print(f"SUCCESS: SecureFlow scan events logged count={events['total']}")

    # -------------------------------------------------------------------------
    # SecureFlow Workflow C: Finding Status Management
    # -------------------------------------------------------------------------
    status, findings = api_call(
        f"/api/v1/repositories/{REPO_ID}/secureflow/findings?workspace_id={WORKSPACE_ID}"
    )
    assert status == 200, f"List findings failed: {findings}"
    print(f"SUCCESS: SecureFlow findings listed count={findings['total']}")

    if findings["total"] > 0:
        target_f = findings["items"][0]
        f_id = target_f["id"]
        status, updated_f = api_call(
            f"/api/v1/repositories/{REPO_ID}/secureflow/findings/{f_id}/status?workspace_id={WORKSPACE_ID}",
            method="PATCH",
            body={"status": "CONFIRMED", "note": "Verified by security team during integration"},
        )
        assert status == 200, f"Update finding failed: {updated_f}"
        assert updated_f["status"] == "CONFIRMED"
        print(f"SUCCESS: SecureFlow finding status updated to CONFIRMED for id={f_id}")

        # -------------------------------------------------------------------------
        # SecureFlow Workflow D: DevPilot Remediation Bridge
        # -------------------------------------------------------------------------
        status, rem = api_call(
            f"/api/v1/repositories/{REPO_ID}/secureflow/findings/{f_id}/remediate?workspace_id={WORKSPACE_ID}",
            method="POST",
        )
        assert status == 200, f"Remediate failed: {rem}"
        assert rem["finding_id"] == f_id
        devpilot_task_id = rem["devpilot_task_id"]
        assert rem["requires_plan_approval"] is True
        print(f"SUCCESS: SecureFlow dispatched DevPilot remediation task id={devpilot_task_id}")

        status, rem_info = api_call(
            f"/api/v1/repositories/{REPO_ID}/secureflow/findings/{f_id}/remediation?workspace_id={WORKSPACE_ID}"
        )
        assert status == 200, f"Get remediation failed: {rem_info}"
        assert rem_info["devpilot_task_id"] == devpilot_task_id
        print(
            f"SUCCESS: SecureFlow retrieved linked DevPilot remediation task id={rem_info['devpilot_task_id']}"
        )
