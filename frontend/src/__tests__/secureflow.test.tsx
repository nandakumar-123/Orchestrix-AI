import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SecurityPage from "../app/security/page";
import * as authModule from "../lib/auth";
import * as githubModule from "../lib/github";
import * as secureflowModule from "../lib/secureflow";

describe("SecureFlow: Application Security Analysis UI", () => {
  const mockUser: authModule.CurrentUser = {
    id: "user-123",
    email: "sec@orchestrix.ai",
    full_name: "Security Engineer",
    avatar_url: null,
    email_verified: true,
    workspaces: [
      {
        workspace_id: "ws-123",
        name: "Enterprise Workspace",
        slug: "ent-ws",
        role: "MEMBER",
      },
    ],
  };

  const mockRepo: githubModule.WorkspaceRepository = {
    id: "repo-123",
    workspace_id: "ws-123",
    installation_id: "inst-123",
    github_repository_id: 112233,
    name: "backend-service",
    full_name: "orchestrix/backend-service",
    owner_login: "orchestrix",
    html_url: "https://github.com/orchestrix/backend-service",
    default_branch: "main",
    visibility: "private",
    language: "Python",
    is_active: true,
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockFinding: secureflowModule.SecureFlowFinding = {
    id: "find-123",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    scan_id: "scan-123",
    scanner: "secret_scanner",
    category: "secrets",
    severity: "CRITICAL",
    confidence: 0.99,
    rule_id: "SEC001_AWS_KEY",
    title: "Hardcoded AWS Access Key Detected",
    description: "An active AWS access key identifier was detected in configuration file.",
    redacted_evidence: "AWS_ACCESS_KEY_ID = [REDACTED_SECRET]",
    file_path: "config/aws.py",
    line_start: 14,
    line_end: 14,
    remediation_recommendation: "Rotate compromised key in AWS IAM and load credential via environment variable.",
    remediation_code_snippet: "AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']",
    external_advisory_url: "https://docs.aws.amazon.com/general/latest/gr/aws-access-keys-best-practices.html",
    fingerprint: "fp_aws_12345",
    status: "OPEN",
    created_at: "2026-03-01T12:00:00Z",
    updated_at: "2026-03-01T12:00:00Z",
  };

  const mockScan: secureflowModule.SecureFlowScan = {
    id: "scan-12345678",
    workspace_id: "ws-123",
    repository_id: "repo-123",
    snapshot_id: null,
    scan_type: "FULL",
    status: "COMPLETED",
    scanners_used: [{ scanner: "secret_scanner" }],
    total_findings: 1,
    critical_count: 1,
    high_count: 0,
    medium_count: 0,
    low_count: 0,
    started_at: "2026-03-01T12:00:00Z",
    completed_at: "2026-03-01T12:01:00Z",
    created_at: "2026-03-01T12:00:00Z",
  };

  const mockScanners: secureflowModule.ScannerStatusItem[] = [
    {
      scanner: "secret_scanner",
      category: "secrets",
      is_available: true,
      version: "1.0.0",
      binary_path: "built-in",
      details: "High-entropy and regex secret detection",
    },
    {
      scanner: "pip_audit",
      category: "dependencies",
      is_available: true,
      version: "2.7.3",
      binary_path: "/usr/bin/pip-audit",
      details: "PyPA PyPI vulnerability scanner",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(githubModule, "fetchWorkspaceRepositories").mockResolvedValue([mockRepo]);
    vi.spyOn(secureflowModule, "listFindings").mockResolvedValue({
      items: [mockFinding],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.spyOn(secureflowModule, "listScans").mockResolvedValue({
      items: [mockScan],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.spyOn(secureflowModule, "getScannerAvailability").mockResolvedValue({
      scanners: mockScanners,
      all_available: true,
    });
    vi.spyOn(secureflowModule, "getFindingRemediation").mockResolvedValue(null);
    vi.spyOn(secureflowModule, "updateFindingStatus").mockResolvedValue({
      ...mockFinding,
      status: "CONFIRMED",
    });
    vi.spyOn(secureflowModule, "remediateFinding").mockResolvedValue({
      finding_id: "find-123",
      devpilot_task_id: "task-999",
      task_title: "Remediate Hardcoded AWS Access Key",
      task_status: "PLANNING",
      requires_plan_approval: true,
      requires_code_approval: true,
    });
    vi.spyOn(secureflowModule, "startScan").mockResolvedValue(mockScan);
  });

  it("renders SecureFlow header, role badge, and repository selector", async () => {
    render(<SecurityPage />);

    expect(
      await screen.findByText("SecureFlow — Application Security Analysis")
    ).toBeInTheDocument();
    expect(screen.getByText("MEMBER")).toBeInTheDocument();
    expect(screen.getByText("orchestrix/backend-service")).toBeInTheDocument();
  });

  it("computes severity breakdown dynamically and displays findings", async () => {
    render(<SecurityPage />);

    await waitFor(() => {
      expect(screen.getByText("Hardcoded AWS Access Key Detected")).toBeInTheDocument();
    });

    // Check critical counter card
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Requires immediate remediation")).toBeInTheDocument();
  });

  it("selects a finding, shows redacted evidence, and updates triage status", async () => {
    render(<SecurityPage />);

    const findingRow = await screen.findByText("Hardcoded AWS Access Key Detected");
    await userEvent.click(findingRow);

    expect(await screen.findByText("Evidence (Secrets Redacted):")).toBeInTheDocument();
    expect(screen.getByText(/AWS_ACCESS_KEY_ID = \[REDACTED_SECRET\]/)).toBeInTheDocument();

    // Select status CONFIRMED and submit triage
    const statusSelect = screen.getByRole("combobox", { name: /Triage Status Selection/i });
    await userEvent.selectOptions(statusSelect, "CONFIRMED");

    const updateBtn = screen.getByRole("button", { name: "Update" });
    await userEvent.click(updateBtn);

    await waitFor(() => {
      expect(secureflowModule.updateFindingStatus).toHaveBeenCalledWith(
        "repo-123",
        "find-123",
        "CONFIRMED",
        undefined,
        "ws-123"
      );
    });
  });

  it("triggers DevPilot autonomous remediation and renders task link", async () => {
    render(<SecurityPage />);

    const findingRow = await screen.findByText("Hardcoded AWS Access Key Detected");
    await userEvent.click(findingRow);

    const remediateBtn = await screen.findByRole("button", { name: /Remediate with DevPilot/i });
    await userEvent.click(remediateBtn);

    await waitFor(() => {
      expect(secureflowModule.remediateFinding).toHaveBeenCalledWith(
        "repo-123",
        "find-123",
        "ws-123"
      );
    });

    expect(await screen.findByText("Remediate Hardcoded AWS Access Key")).toBeInTheDocument();
    expect(screen.getByText("View in DevPilot")).toBeInTheDocument();
  });

  it("navigates to Scanner Engine Status tab and renders scanner availability", async () => {
    render(<SecurityPage />);

    const scannersTab = await screen.findByRole("tab", { name: /Scanner Engine Status/i });
    await userEvent.click(scannersTab);

    expect(await screen.findByText("pip_audit")).toBeInTheDocument();
    expect(screen.getByText("All Scanners Available")).toBeInTheDocument();
  });
});
