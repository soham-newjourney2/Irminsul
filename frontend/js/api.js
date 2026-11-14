// Single fetch wrapper for /api/v1. Pages only render; no business rules here.

export class ApiError extends Error {
  constructor(status, code, message, details = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const newIdempotencyKey = () => crypto.randomUUID();

export async function api(path, { method = "GET", body, idempotencyKey, signal } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  let res;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Network error");
  }

  if (res.status === 204) return null;
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = json?.error ?? {};
    throw new ApiError(res.status, e.code ?? "http_error", e.message ?? res.statusText, e.details);
  }
  return json;
}

/** Multipart upload (e.g. crop photo). Same error envelope handling as api(). */
export async function apiUpload(path, formData, { idempotencyKey } = {}) {
  const headers = { Accept: "application/json" };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  let res;
  try {
    res = await fetch(`/api/v1${path}`, { method: "POST", headers, credentials: "same-origin", body: formData });
  } catch {
    throw new ApiError(0, "network_error", "Network error");
  }
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = json?.error ?? {};
    throw new ApiError(res.status, e.code ?? "http_error", e.message ?? res.statusText, e.details);
  }
  return json;
}
