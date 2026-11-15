import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeAll } from "vitest";
import SecurityPage from "../app/security/page";

const itLive = process.env.RUN_LIVE_TESTS ? it : it.skip;

describe("Live SecureFlow Authenticated Integration Test", () => {
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
      headers.set("Referer", "http://localhost:3000/security");

      return originalFetch(urlStr, {
        ...init,
        headers,
      });
    };
  });

  itLive(
    "authenticates live session, loads live repositories and SecureFlow findings without errors",
    async () => {
      render(<SecurityPage />);

      expect(
        await screen.findByText("SecureFlow — Application Security Analysis")
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

      // Verify findings or empty state rendered with no [object Object]
      expect(screen.getByText("Latest Scan Status")).toBeInTheDocument();
      expect(screen.queryByText(/\[object Object\]/)).toBeNull();
    }
  );
});
