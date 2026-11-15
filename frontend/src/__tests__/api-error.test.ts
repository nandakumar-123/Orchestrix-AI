import { describe, it, expect } from "vitest";
import { normalizeApiError, getResponseErrorMessage } from "../lib/api-error";

describe("normalizeApiError Utility", () => {
  it("normalizes a simple string error", () => {
    expect(normalizeApiError("Something broke")).toBe("Something broke");
  });

  it("handles null and undefined with fallback", () => {
    expect(normalizeApiError(null)).toBe("An unexpected error occurred. Please try again.");
    expect(normalizeApiError(undefined, "Custom fallback")).toBe("Custom fallback");
  });

  it("handles standard Error instances", () => {
    expect(normalizeApiError(new Error("Database connection lost"))).toBe(
      "Database connection lost"
    );
  });

  it("safely intercepts and replaces literal [object Object] strings with fallback", () => {
    expect(normalizeApiError("[object Object]")).toBe(
      "An unexpected error occurred. Please try again."
    );
    expect(normalizeApiError("[object Object],[object Object]")).toBe(
      "An unexpected error occurred. Please try again."
    );
    expect(normalizeApiError(new Error("[object Object]"))).toBe(
      "An unexpected error occurred. Please try again."
    );
  });

  it("normalizes FastAPI 422 validation array with field locations and messages", () => {
    const fastApi422 = {
      detail: [
        {
          loc: ["query", "workspace_id"],
          msg: "Field required",
          type: "missing",
        },
        {
          loc: ["body", "title"],
          msg: "String should have at least 3 characters",
          type: "string_too_short",
        },
      ],
    };

    const result = normalizeApiError(fastApi422);
    expect(result).toContain("Field 'workspace_id': Field required");
    expect(result).toContain("Field 'title': String should have at least 3 characters");
    expect(result).not.toContain("[object Object]");
  });

  it("handles direct array of validation items", () => {
    const rawArray = [
      {
        loc: ["query", "limit"],
        msg: "Input should be greater than 0",
        type: "greater_than",
      },
    ];

    const result = normalizeApiError(rawArray);
    expect(result).toBe("Field 'limit': Input should be greater than 0");
    expect(result).not.toContain("[object Object]");
  });

  it("handles FastAPI string detail payload", () => {
    const fastApiError = {
      detail: "Repository not found in workspace",
    };
    expect(normalizeApiError(fastApiError)).toBe("Repository not found in workspace");
  });

  it("handles message or error payload properties", () => {
    expect(normalizeApiError({ message: "Unauthorized token" })).toBe("Unauthorized token");
    expect(normalizeApiError({ error: "Access denied" })).toBe("Access denied");
  });

  it("handles empty object by JSON serializing or fallback", () => {
    expect(normalizeApiError({})).toBe("An unexpected error occurred. Please try again.");
  });

  it("extracts error message from Response object with status fallback", async () => {
    const mockResponse404 = new Response(JSON.stringify({ detail: "Repository missing" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
    const msg = await getResponseErrorMessage(mockResponse404);
    expect(msg).toBe("Repository missing");

    const mockResponse422 = new Response(
      JSON.stringify({
        detail: [
          {
            loc: ["query", "workspace_id"],
            msg: "Field required",
            type: "missing",
          },
        ],
      }),
      {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }
    );
    const msg422 = await getResponseErrorMessage(mockResponse422);
    expect(msg422).toBe("Field 'workspace_id': Field required");

    const mockResponse500 = new Response("Internal Server Error", {
      status: 500,
      headers: { "Content-Type": "text/plain" },
    });
    const msg500 = await getResponseErrorMessage(mockResponse500);
    expect(msg500).toBe("Internal Server Error");
  });
});
