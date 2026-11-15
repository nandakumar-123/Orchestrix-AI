/**
 * Orchestrix AI - API Error Normalization Utility
 * Safely parses API errors, FastAPI 422 validation payloads, network failures,
 * and HTTP status codes into human-readable strings.
 * Guarantees that "[object Object]" is never rendered.
 */

export interface FastApiValidationErrorItem {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
  ctx?: Record<string, unknown>;
}

export interface FastApiErrorPayload {
  detail?: string | FastApiValidationErrorItem[] | Record<string, unknown>;
  message?: string;
  error?: string;
}

/**
 * Format a single FastAPI validation item into a user-friendly string.
 * Example: loc=["query", "workspace_id"], msg="Field required" -> "Field 'workspace_id': Field required"
 */
function formatValidationItem(item: FastApiValidationErrorItem): string {
  if (!item || typeof item !== "object") {
    return "Invalid request parameter";
  }

  const msg = typeof item.msg === "string" ? item.msg.trim() : "Invalid parameter";
  if (!Array.isArray(item.loc) || item.loc.length === 0) {
    return msg;
  }

  // Filter out noisy prefixes like "query", "body", "path" when locating the field name
  const locParts = item.loc.map(String);
  const relevantParts = locParts.filter((p) => p !== "body" && p !== "query" && p !== "path");
  const fieldName = relevantParts.length > 0 ? relevantParts.join(".") : locParts.join(".");

  return `Field '${fieldName}': ${msg}`;
}

/**
 * Normalizes any error object, HTTP response body, or exception into a clean string.
 * Ensures "[object Object]" is never returned.
 */
export function normalizeApiError(
  err: unknown,
  fallbackMessage: string = "An unexpected error occurred. Please try again."
): string {
  if (err === null || err === undefined) {
    return fallbackMessage;
  }

  // 1. Direct string
  if (typeof err === "string") {
    const trimmed = err.trim();
    if (!trimmed || trimmed === "[object Object]" || trimmed.includes("[object Object]")) {
      return fallbackMessage;
    }
    return trimmed;
  }

  // 2. JavaScript Error instance
  if (err instanceof Error) {
    const msg = err.message ? err.message.trim() : "";
    if (!msg || msg === "[object Object]" || msg.includes("[object Object]")) {
      // Check if the Error was thrown with a serialized JSON detail
      return fallbackMessage;
    }
    return msg;
  }

  // 3. Array of errors (e.g. raw FastAPI 422 detail array)
  if (Array.isArray(err)) {
    if (err.length === 0) return fallbackMessage;
    const formattedItems = err.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) {
        return formatValidationItem(item as FastApiValidationErrorItem);
      }
      return JSON.stringify(item);
    });
    return formattedItems.join("; ");
  }

  // 4. Object payload (FastAPI / standard JSON response)
  if (typeof err === "object") {
    const payload = err as FastApiErrorPayload;

    // detail field
    if (payload.detail !== undefined && payload.detail !== null) {
      if (typeof payload.detail === "string") {
        const trimmed = payload.detail.trim();
        if (trimmed && trimmed !== "[object Object]" && !trimmed.includes("[object Object]")) {
          return trimmed;
        }
      } else if (Array.isArray(payload.detail)) {
        if (payload.detail.length > 0) {
          const items = payload.detail.map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object" && "msg" in item) {
              return formatValidationItem(item as FastApiValidationErrorItem);
            }
            return JSON.stringify(item);
          });
          return items.join("; ");
        }
      } else if (typeof payload.detail === "object") {
        try {
          return JSON.stringify(payload.detail);
        } catch {
          return fallbackMessage;
        }
      }
    }

    // message field
    if (typeof payload.message === "string" && payload.message.trim()) {
      const msg = payload.message.trim();
      if (msg !== "[object Object]" && !msg.includes("[object Object]")) {
        return msg;
      }
    }

    // error field
    if (typeof payload.error === "string" && payload.error.trim()) {
      const errStr = payload.error.trim();
      if (errStr !== "[object Object]" && !errStr.includes("[object Object]")) {
        return errStr;
      }
    }

    // Fallback serialization if non-empty object
    try {
      const serialized = JSON.stringify(payload);
      if (serialized && serialized !== "{}" && serialized !== "[]") {
        return serialized;
      }
    } catch {
      // Ignore serialization error and fall through
    }
  }

  return fallbackMessage;
}

/**
 * Helper to extract and normalize error message directly from an HTTP Response object.
 */
export async function getResponseErrorMessage(
  res: Response,
  fallbackMessage?: string
): Promise<string> {
  const statusFallbacks: Record<number, string> = {
    400: "Invalid request. Please verify your input parameters.",
    401: "Authentication required. Please sign in again.",
    403: "Access denied. You do not have permission to access this resource or workspace.",
    404: "Requested resource or repository was not found.",
    409: "Conflict detected with existing state.",
    422: "Validation error: Missing or invalid request parameters.",
    500: "Internal server error. Please try again later.",
    502: "Bad gateway. The backend service may be starting or unreachable.",
    503: "Service temporarily unavailable. Please retry shortly.",
  };

  const defaultStatusMsg = statusFallbacks[res.status] || `Request failed (${res.status})`;

  try {
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await res.json();
      return normalizeApiError(data, fallbackMessage || defaultStatusMsg);
    }
    const text = await res.text();
    return normalizeApiError(text, fallbackMessage || defaultStatusMsg);
  } catch {
    return fallbackMessage || defaultStatusMsg;
  }
}
