/* Browser API client. Same-origin (Next rewrites /api → backend); session cookie + double-submit CSRF. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: any) {
    super(message);
  }
}

function csrf(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|; )isc_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; signal?: AbortSignal } = {}): Promise<T> {
  const method = opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-CSRF-Token"] = csrf();
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method, headers, credentials: "same-origin", signal: opts.signal,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    });
  } catch (e: any) {
    if (e?.name === "AbortError") throw e;
    throw new ApiError(0, "network", "Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = data?.error || {};
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
    }
    throw new ApiError(res.status, err.code || "error", err.message || `Request failed (${res.status})`, err.details);
  }
  return data as T;
}

function safeJson(t: string) {
  try { return JSON.parse(t); } catch { return { raw: t }; }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
