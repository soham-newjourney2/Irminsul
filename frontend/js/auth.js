import { api } from "./api.js";

export const HOME = {
  farmer: "/farmer/",
  distributor: "/distributor/",
  storage_operator: "/storage/",
  admin: "/admin/",
};

/** Current user, or null when not logged in. Other errors propagate. */
export async function getMe() {
  try {
    return (await api("/users/me")).data;
  } catch (err) {
    if (err.status === 401) return null;
    throw err;
  }
}

export async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } finally {
    location.href = "/login.html";
  }
}

/**
 * Post-login redirect target. Parsed as a URL (browsers treat \\ and tabs like /),
 * so only same-origin paths survive; anything else falls back to defaultPath.
 */
export function sameOriginPath(next, origin, defaultPath) {
  if (!next || !next.startsWith("/") || /[\\\u0000-\u001f]/.test(next)) return defaultPath;
  try {
    const url = new URL(next, origin);
    return url.origin === origin ? url.pathname + url.search + url.hash : defaultPath;
  } catch {
    return defaultPath;
  }
}

export function safeNext(defaultPath) {
  return sameOriginPath(new URLSearchParams(location.search).get("next"), location.origin, defaultPath);
}
