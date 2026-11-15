import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as authModule from "../lib/auth";
import * as devmemoryApi from "../lib/devmemory";
import MemoryPage from "../app/memory/page";
import MemoryDetailPage from "../app/memory/[memoryId]/page";
import { AgentMemoryContext } from "../components/shared/agent-memory-context";

// ============================================================
// Mocks
// ============================================================

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ memoryId: "mem-test-001" }),
  usePathname: () => "/memory",
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockUser: authModule.CurrentUser = {
  id: "user-admin-01",
  email: "admin@orchestrix.ai",
  full_name: "Memory Admin",
  avatar_url: null,
  email_verified: true,
  workspaces: [
    {
      workspace_id: "ws-memory-001",
      name: "DevMemory Workspace",
      slug: "mem-ws",
      role: "ADMIN",
    },
  ],
};

const mockStats: devmemoryApi.MemoryStatsResponse = {
  total_count: 5,
  verified_count: 3,
  unverified_count: 1,
  outdated_count: 1,
  archived_count: 0,
  type_counts: {
    ARCHITECTURE_DECISION: 2,
    ENGINEERING_CONVENTION: 2,
    BUG_FIX: 1,
  },
};

const mockMemory: devmemoryApi.MemoryResponse = {
  id: "mem-test-001",
  workspace_id: "ws-memory-001",
  repository_id: "repo-001",
  memory_type: "ARCHITECTURE_DECISION",
  title: "Neon Postgres Connection Pooling with PgBouncer",
  content: "All database sessions in async FastAPI workers must pass through PgBouncer port 6543 to maintain connection budget.",
  summary: "Enforce PgBouncer connection pooling across async workers.",
  source_type: "USER_INPUT",
  source_reference: "docs/architecture/database.md",
  confidence_score: 0.95,
  verification_status: "VERIFIED",
  created_by: "user-admin-01",
  created_at: "2026-11-10T10:00:00Z",
  updated_at: "2026-11-15T12:00:00Z",
  expires_at: null,
  content_hash: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  evidence: [
    {
      id: "ev-001",
      memory_id: "mem-test-001",
      workspace_id: "ws-memory-001",
      evidence_type: "CODE_REFERENCE",
      source_reference: "backend/app/db/session.py:22",
      evidence_content: "async_engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)",
      created_at: "2026-11-10T10:05:00Z",
    },
  ],
};

const mockSearchResult: devmemoryApi.MemorySearchResult = {
  memory: mockMemory,
  relevance_score: 0.94,
  semantic_score: 0.96,
  lexical_score: 0.90,
  is_verified: true,
  evidence_count: 1,
};

const mockContext: devmemoryApi.MemoryContextResponse = {
  context_markdown: "### RELEVANT ORGANIZATIONAL ENGINEERING MEMORY\n- Neon Postgres Connection Pooling with PgBouncer",
  citations: ["mem-test-001"],
  memories_used: 1,
  verified_count: 1,
  unverified_count: 0,
};

// ============================================================
// Test Suites
// ============================================================

describe("DevMemory Main Interface: Memory Overview & Catalog", () => {
  beforeEach(() => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(devmemoryApi, "getMemoryStats").mockResolvedValue(mockStats);
    vi.spyOn(devmemoryApi, "listMemories").mockResolvedValue([mockMemory]);
  });

  it("renders page header and stats metrics from backend", async () => {
    render(<MemoryPage />);
    await waitFor(() => {
      expect(screen.getByText("DevMemory: Persistent Engineering Memory")).toBeInTheDocument();
      expect(screen.getByText("Total Stored")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
    });
  });

  it("renders memory cards with verification status badges", async () => {
    render(<MemoryPage />);
    await waitFor(() => {
      expect(screen.getByText("Neon Postgres Connection Pooling with PgBouncer")).toBeInTheDocument();
      expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
    });
  });

  it("renders empty state when no memories exist in workspace", async () => {
    vi.spyOn(devmemoryApi, "listMemories").mockResolvedValue([]);
    render(<MemoryPage />);
    await waitFor(() => {
      expect(screen.getByText("No memories found")).toBeInTheDocument();
    });
  });

  it("triggers semantic search and renders search results with relevance scores", async () => {
    const user = userEvent.setup();
    const searchSpy = vi.spyOn(devmemoryApi, "searchMemories").mockResolvedValue([mockSearchResult]);

    render(<MemoryPage />);
    await waitFor(() => {
      expect(screen.getByText("Neon Postgres Connection Pooling with PgBouncer")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/search semantic engineering knowledge/i);
    await user.type(input, "connection pooling");
    const searchBtn = screen.getByRole("button", { name: "Semantic Search" });
    await user.click(searchBtn);

    await waitFor(() => {
      expect(searchSpy).toHaveBeenCalledWith(
        "ws-memory-001",
        expect.objectContaining({ query: "connection pooling" })
      );
      expect(screen.getByText(/Score: 94%/)).toBeInTheDocument();
    });
  });

  it("handles search error gracefully without crashing", async () => {
    const user = userEvent.setup();
    vi.spyOn(devmemoryApi, "searchMemories").mockRejectedValue(new Error("Vector database unreachable"));

    render(<MemoryPage />);
    await waitFor(() => {
      expect(screen.getByText("Neon Postgres Connection Pooling with PgBouncer")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/search semantic engineering knowledge/i);
    await user.type(input, "fail query");
    const searchBtn = screen.getByRole("button", { name: "Semantic Search" });
    await user.click(searchBtn);

    await waitFor(() => {
      expect(screen.getByText("Vector database unreachable")).toBeInTheDocument();
    });
  });
});

describe("DevMemory Detail Interface: Details, Evidence, and Relationships", () => {
  beforeEach(() => {
    vi.spyOn(authModule, "fetchCurrentUser").mockResolvedValue(mockUser);
    vi.spyOn(devmemoryApi, "getMemory").mockResolvedValue(mockMemory);
    vi.spyOn(devmemoryApi, "listEvidence").mockResolvedValue(mockMemory.evidence);
    vi.spyOn(devmemoryApi, "listRelationships").mockResolvedValue([
      {
        id: "rel-001",
        workspace_id: "ws-memory-001",
        source_memory_id: "mem-test-001",
        target_memory_id: "mem-test-002",
        relationship_type: "EXTENDS",
        confidence_score: 0.9,
        created_at: "2026-11-11T10:00:00Z",
      },
    ]);
  });

  it("renders memory details, content, and evidence list", async () => {
    render(<MemoryDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Neon Postgres Connection Pooling with PgBouncer")).toBeInTheDocument();
      expect(screen.getByText(/All database sessions in async FastAPI workers/)).toBeInTheDocument();
      expect(screen.getByText("Supporting Evidence (1)")).toBeInTheDocument();
      expect(screen.getByText("CODE_REFERENCE")).toBeInTheDocument();
      expect(screen.getByText("Source: backend/app/db/session.py:22")).toBeInTheDocument();
    });
  });

  it("renders semantic relationship connections", async () => {
    render(<MemoryDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Connected Memories & Graph (1)")).toBeInTheDocument();
      expect(screen.getByText("EXTENDS")).toBeInTheDocument();
    });
  });

  it("triggers archiveMemory when Archive button is clicked by admin", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const archiveSpy = vi.spyOn(devmemoryApi, "archiveMemory").mockResolvedValue({
      ...mockMemory,
      verification_status: "ARCHIVED",
    });

    render(<MemoryDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Archive")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Archive"));
    await waitFor(() => {
      expect(archiveSpy).toHaveBeenCalledWith("mem-test-001", "ws-memory-001", "Archived by user");
    });
  });
});

describe("Agent Integration Component: AgentMemoryContext", () => {
  it("renders retrieved memory context in agent interfaces", async () => {
    vi.spyOn(devmemoryApi, "getMemoryContext").mockResolvedValue(mockContext);

    render(
      <AgentMemoryContext
        agent="DEVPILOT"
        query="Database connection pooling"
        workspaceId="ws-memory-001"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Institutional Knowledge (DevMemory)")).toBeInTheDocument();
      expect(screen.getByText("1 active context")).toBeInTheDocument();
      expect(screen.getByText("1 verified")).toBeInTheDocument();
    });
  });

  it("degrades gracefully to null when no memory context is used", async () => {
    vi.spyOn(devmemoryApi, "getMemoryContext").mockResolvedValue({
      context_markdown: "",
      citations: [],
      memories_used: 0,
      verified_count: 0,
      unverified_count: 0,
    });

    const { container } = render(
      <AgentMemoryContext
        agent="TESTPILOT"
        query="Unrelated topic"
        workspaceId="ws-memory-001"
      />
    );

    await waitFor(() => {
      expect(container.firstChild).toBeNull();
    });
  });
});
