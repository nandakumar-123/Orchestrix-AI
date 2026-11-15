import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeAll } from "vitest";
import DevPilotPage from "../app/devpilot/page";

const itLive = process.env.RUN_LIVE_TESTS ? it : it.skip;

describe("Live DevPilot Authenticated Integration Test", () => {
  const SESSION_COOKIE = "OzDC_32Q1zQTbvCHuqY8RLJ07YpiYrN75F-dI6JJ3qU";
  const CSRF_COOKIE = "M2LXcouv5w0jLadRM_sSJXZJMatdJonQu0UquSxcLIQ.7a84b9659c5e3a4b54104fd5cd7c5a02a9125765f675e30136edeb486092a297";

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

  itLive(
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
            screen.getAllByText(/time-tracker|AI-breakup-Recovery-chatbot/i).length
          ).toBeGreaterThan(0);
        },
        { timeout: 15000 }
      );

      // Select time-tracker repository if not already selected
      const selectRepo = screen.getByLabelText(/Repository Selection/i);
      const timeTrackerOption = Array.from((selectRepo as HTMLSelectElement).options).find((opt) =>
        opt.text.includes("time-tracker")
      );
      if (timeTrackerOption && (selectRepo as HTMLSelectElement).value !== timeTrackerOption.value) {
        (selectRepo as HTMLSelectElement).value = timeTrackerOption.value;
        selectRepo.dispatchEvent(new Event("change", { bubbles: true }));
      }

      // 3. Verify task history rendered live tasks
      await waitFor(
        () => {
          expect(
            screen.getAllByText(/Add Input Validation Helper|Add CSV Export Utility|Security Remediation/i).length
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
