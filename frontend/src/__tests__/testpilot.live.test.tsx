import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeAll } from "vitest";
import TestingPage from "../app/testing/page";

const itLive = process.env.RUN_LIVE_TESTS ? it : it.skip;

describe("Live TestPilot Authenticated Integration Test", () => {
  const SESSION_COOKIE = "OzDC_32Q1zQTbvCHuqY8RLJ07YpiYrN75F-dI6JJ3qU";
  const CSRF_COOKIE = "M2LXcouv5w0jLadRM_sSJXZJMatdJonQu0UquSxcLIQ.7a84b9659c5e3a4b54104fd5cd7c5a02a9125765f675e30136edeb486092a297";

  beforeAll(() => {
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: `orchestrix_session=${SESSION_COOKIE}; orchestrix_csrf=${CSRF_COOKIE}`,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const urlStr = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = new Headers(init?.headers || {});
      headers.set("Cookie", `orchestrix_session=${SESSION_COOKIE}; orchestrix_csrf=${CSRF_COOKIE}`);
      headers.set("X-CSRF-Token", CSRF_COOKIE);
      headers.set("Origin", "http://localhost:3000");
      headers.set("Referer", "http://localhost:3000/testing");

      return originalFetch(urlStr, {
        ...init,
        headers,
      });
    };
  });

  itLive(
    "authenticates live session, loads live repositories and TestPilot suites without errors",
    async () => {
      render(<TestingPage />);

      expect(
        await screen.findByText("TestPilot — Autonomous Software Testing")
      ).toBeInTheDocument();

      // Wait for real repository to be loaded
      await waitFor(
        () => {
          expect(
            screen.getByText("nandakumar-123/time-tracker")
          ).toBeInTheDocument();
        },
        { timeout: 10000 }
      );

      // Verify overview cards render numbers
      expect(screen.getByText("Test Suites Created")).toBeInTheDocument();
      expect(screen.getByText("Line Coverage")).toBeInTheDocument();
      expect(screen.getByText("Branch Coverage")).toBeInTheDocument();
    }
  );
});
