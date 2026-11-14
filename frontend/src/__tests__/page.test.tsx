import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Home from "../app/page";

describe("Frontend Home Page", () => {
  it("renders the Orchestrix AI branding", () => {
    render(<Home />);
    expect(screen.getByText("Orchestrix AI")).toBeInTheDocument();
  });

  it("displays the operational backend health badge", () => {
    render(<Home />);
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("GET /api/v1/health")).toBeInTheDocument();
  });

  it("displays the platform foundation version tag", () => {
    render(<Home />);
    expect(
      screen.getByText("Platform Foundation v0.1.0")
    ).toBeInTheDocument();
  });
});

