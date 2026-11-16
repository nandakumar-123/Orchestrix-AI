import { fetchWithAuth } from "./auth";
import { getResponseErrorMessage } from "./api-error";

export type TicketPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TicketStatus = "OPEN" | "IN_PROGRESS" | "UNDER_REVIEW" | "RESOLVED" | "CLOSED";
export type TicketActivityType =
  | "CREATED"
  | "STATUS_CHANGED"
  | "ASSIGNED"
  | "PRIORITY_CHANGED"
  | "COMMENTED"
  | "UPDATED";

export interface TicketActivityItem {
  id: string;
  ticket_id: string;
  workspace_id: string;
  actor_id?: string | null;
  actor_name?: string | null;
  actor_email?: string | null;
  activity_type: TicketActivityType;
  old_value?: string | null;
  new_value?: string | null;
  comment?: string | null;
  created_at: string;
}

export interface TicketItem {
  id: string;
  workspace_id: string;
  repository_id?: string | null;
  repository_name?: string | null;
  title: string;
  description?: string | null;
  priority: TicketPriority;
  status: TicketStatus;
  creator_id?: string | null;
  creator_name?: string | null;
  creator_email?: string | null;
  assignee_id?: string | null;
  assignee_name?: string | null;
  assignee_email?: string | null;
  due_date?: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
  activities: TicketActivityItem[];
}

export interface TicketListResponse {
  items: TicketItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TicketCreatePayload {
  workspace_id: string;
  title: string;
  description?: string;
  priority?: TicketPriority;
  repository_id?: string;
  assignee_id?: string;
  due_date?: string;
  tags?: string[];
}

export interface TicketUpdatePayload {
  title?: string;
  description?: string;
  priority?: TicketPriority;
  repository_id?: string;
  due_date?: string;
  tags?: string[];
}

function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== null && val !== "") {
      q.set(key, String(val));
    }
  }
  const str = q.toString();
  return str ? `?${str}` : "";
}

export async function listTickets(
  workspaceId: string,
  params?: {
    repository_id?: string;
    status?: TicketStatus;
    priority?: TicketPriority;
    assignee_id?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }
): Promise<TicketListResponse> {
  const query = buildQuery({
    workspace_id: workspaceId,
    repository_id: params?.repository_id,
    status: params?.status,
    priority: params?.priority,
    assignee_id: params?.assignee_id,
    search: params?.search,
    limit: params?.limit ?? 50,
    offset: params?.offset ?? 0,
  });

  const res = await fetchWithAuth(`/api/v1/tickets${query}`);
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to load tickets (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function getTicket(workspaceId: string, ticketId: string): Promise<TicketItem> {
  const res = await fetchWithAuth(`/api/v1/tickets/${ticketId}?workspace_id=${workspaceId}`);
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to load ticket (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function createTicket(
  workspaceId: string,
  payload: Omit<TicketCreatePayload, "workspace_id">
): Promise<TicketItem> {
  const res = await fetchWithAuth("/api/v1/tickets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_id: workspaceId,
      ...payload,
    }),
  });
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to create ticket (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function updateTicket(
  workspaceId: string,
  ticketId: string,
  payload: TicketUpdatePayload
): Promise<TicketItem> {
  const res = await fetchWithAuth(`/api/v1/tickets/${ticketId}?workspace_id=${workspaceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to update ticket (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function updateTicketStatus(
  workspaceId: string,
  ticketId: string,
  newStatus: TicketStatus,
  comment?: string
): Promise<TicketItem> {
  const res = await fetchWithAuth(`/api/v1/tickets/${ticketId}/status?workspace_id=${workspaceId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: newStatus, comment }),
  });
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to update ticket status (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function assignTicket(
  workspaceId: string,
  ticketId: string,
  assigneeId: string | null,
  comment?: string
): Promise<TicketItem> {
  const res = await fetchWithAuth(`/api/v1/tickets/${ticketId}/assign?workspace_id=${workspaceId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assignee_id: assigneeId, comment }),
  });
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to assign ticket (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}

export async function addTicketComment(
  workspaceId: string,
  ticketId: string,
  comment: string
): Promise<TicketActivityItem> {
  const res = await fetchWithAuth(`/api/v1/tickets/${ticketId}/comments?workspace_id=${workspaceId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ comment }),
  });
  if (!res.ok) {
    const err = await getResponseErrorMessage(res, `Failed to add comment (${res.status})`);
    throw new Error(err);
  }
  return res.json();
}
