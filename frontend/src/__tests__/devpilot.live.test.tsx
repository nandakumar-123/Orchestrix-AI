import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import DevPilotPage from "../app/devpilot/page";

describe("Live DevPilot Authenticated Integration Test", () => {
  const SESSION_COOKIE = "vAMSFb6fj7YZrikx2ywNsy3GJjkM5f2UHgeH0S7d8ws";
  const CSRF_COOKIE = "34eiA8wxuSh-cdSOrXCzHTSP3OBWZHxJVllNyAUs3pM.b80108b95b54fec3b9e0c999fe9492a29a283c05eeb15a537423479a85aa0c4e";
  const LIVE_API_URL = "http://localhost:8000";

  beforeAll(() => {
    // Set cookie on JSDOM document
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: `orchestrix_session=${SESSION_COOKIE}; orchestrix_csrf=${CSRF_COOKIE}`,
    });

    // Wire global fetch to include credentials header when calling localhost:8000
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const urlStr = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = new Headers(init?.headers || {});
      headers.set("Cookie", `orchestrix_session=${SESSION_COOKIE}; orchestrix_csrf=${CSRF_COOKIE}`);
      headers.set("X-CSRF-Token", CSRF_COOKIE);
      headers.set("Origin", "http://localhost:3000");
      headers.set("Referer", "http://localhost:3000/devpilot");

      return originalFetch(urlStr, {
        ...init,
        headers,
      });
    };
  });

  it(
    "authenticates live session, lists real repositories, and populates DevPilot tasks without [object Object]",
    async () => {
      render(<DevPilotPage />);

      // 1. Verify header
      expect(
        screen.getByText("DevPilot — Autonomous AI Software Engineer")
      ).toBeInTheDocument();

      // 2. Wait for live repositories to load from live backend
      await waitFor(
        () => {
          expect(
            screen.getByText("nandakumar-123/time-tracker")
          ).toBeInTheDocument();
        },
        { timeout: 15000 }
      );

      // 3. Verify task history rendered live tasks
      await waitFor(
        () => {
          expect(
            screen.getAllByText(/Add Input Validation Helper|Add CSV Export Utility/i).length
          ).toBeGreaterThanOrEqual(1);
        },
        { timeout: 15000 }
      );

      // 4. Verify no "[object Object]" exists anywhere in the entire document
      const bodyText = document.body.textContent || "";
      expect(bodyText).not.toContain("[object Object]");

      const htmlContent = document.body.innerHTML;
      expect(htmlContent).not.toContain("[object Object]");
    },
    25000
  );
});
