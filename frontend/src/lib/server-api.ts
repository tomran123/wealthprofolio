import "server-only";

import { cookies } from "next/headers";

const backendUrl = (
  process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export async function serverGet<T>(path: string): Promise<T> {
  const cookieHeader = (await cookies()).toString();
  const response = await fetch(`${backendUrl}${path}`, {
    method: "GET",
    cache: "no-store",
    headers: cookieHeader ? { Cookie: cookieHeader } : undefined,
  });

  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Preserve the HTTP fallback for non-JSON failures.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export async function tryServerGet<T>(path: string): Promise<T | null> {
  try {
    return await serverGet<T>(path);
  } catch {
    // Client-side fetching retains the existing recoverable error and retry UI.
    return null;
  }
}
