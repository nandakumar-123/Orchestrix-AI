import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import DashboardPage from "../app/dashboard/page";

describe("Orchestrix AI Dashboard Experience", () => {
  it("renders the primary dashboard page header and branding", () => {
    render(<DashboardPage />);
    expect(screen.getByText("Engineering Overview")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Monitor your repositories, AI agents, and autonomous engineering activity."
      )
    ).toBeInTheDocument();
  });

  it("renders central orchestration control panel", () => {
    render(<DashboardPage />);
    expect(screen.getByText("Orchestration Control")).toBeInTheDocument();
    expect(screen.getByText("Orchestrator Online")).toBeInTheDocument();
  });

  it("renders the specialist engineering agents", () => {
    render(<DashboardPage />);
    expect(screen.getAllByText("DevPilot").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ImpactMind").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TestPilot").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SecureFlow").length).toBeGreaterThan(0);
    expect(screen.getAllByText("FlowForge").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DevMemory").length).toBeGreaterThan(0);
  });

  it("renders engineering activity and task lists", () => {
    render(<DashboardPage />);
    expect(screen.getByText("Recent Engineering Activity")).toBeInTheDocument();
    expect(screen.getByText("Active Tasks & Queue")).toBeInTheDocument();
  });
});
