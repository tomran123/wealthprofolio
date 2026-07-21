import { api } from "@/lib/api";
import type { UserInfo } from "@/lib/types";

export function login(username: string, password: string) {
  return api.post<UserInfo>("/api/auth/login", { username, password });
}

export function logout() {
  return api.post<{ ok: boolean }>("/api/auth/logout");
}

export function me() {
  return api.get<UserInfo>("/api/auth/me");
}
