const TOKEN_KEY = "ttdm.v2.operator-token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isOperatorAuthorizationError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}

export function getOperatorToken(): string {
  return typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setOperatorToken(token: string): void {
  if (typeof sessionStorage === "undefined") return;
  if (token.trim()) sessionStorage.setItem(TOKEN_KEY, token.trim());
  else sessionStorage.removeItem(TOKEN_KEY);
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getOperatorToken();
  if (token) headers.set("X-TTDM-Operator-Token", token);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(`/api/v2${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : "Network unavailable", 0);
  }

  const payload = response.status === 204 ? undefined : await response.json().catch(() => undefined);
  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export function endpointUnavailable(error: unknown): boolean {
  return error instanceof ApiError && [0, 404, 405, 501, 502, 503, 504].includes(error.status);
}

export function unpackItems<T>(payload: T[] | { items?: T[]; results?: T[]; data?: T[] }): T[] {
  if (Array.isArray(payload)) return payload;
  return payload.items ?? payload.results ?? payload.data ?? [];
}
