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

/** Only same-origin relative paths are accepted as a post-login redirect. */
export function safeNext(defaultPath) {
  const next = new URLSearchParams(location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : defaultPath;
}
