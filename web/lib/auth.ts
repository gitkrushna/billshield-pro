// Authentication is isolated here. Only public Supabase configuration reaches this client.
export type AuthConfig = { auth_url: string; auth_publishable_key: string };
type Session = { access_token: string; refresh_token: string; expires_at: number };
type AuthResponse = Partial<Session> & { expires_in?: number; error_description?: string; msg?: string; message?: string };
const STORAGE_KEY = "billshield.auth.v1";
let config: AuthConfig | null = null;
let refreshing: Promise<Session> | null = null;

export const apiUrl = (path: string) => path;

export async function loadAuthConfig(): Promise<AuthConfig> {
  if (config) return config;
  const response = await fetch(apiUrl("/api/config"), { cache: "no-store" });
  if (!response.ok) throw new Error("Sign-in is temporarily unavailable. Please try again.");
  const value = await response.json() as AuthConfig;
  if (!value.auth_url || !value.auth_publishable_key) throw new Error("Sign-in has not been configured yet.");
  config = value;
  return value;
}

function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Session;
    return value.access_token && value.refresh_token && Number.isFinite(value.expires_at) ? value : null;
  } catch { return null; }
}

function saveSession(value: AuthResponse): Session {
  if (!value.access_token || !value.refresh_token) throw new Error("Please confirm your email, then sign in.");
  const session = {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    expires_at: value.expires_at || Math.floor(Date.now() / 1000) + (value.expires_in || 3600),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  return session;
}

async function authRequest(path: string, body: object): Promise<AuthResponse> {
  const settings = await loadAuthConfig();
  const response = await fetch(`${settings.auth_url.replace(/\/$/, "")}/auth/v1/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", apikey: settings.auth_publishable_key },
    body: JSON.stringify(body),
  });
  const result = await response.json() as AuthResponse;
  if (!response.ok) {
    if (response.status === 429) throw new Error("Too many sign-in attempts. Please wait a moment and try again.");
    if (response.status >= 500) throw new Error("The sign-in service is temporarily unavailable. Please try again.");
    const message = result.msg || result.message || result.error_description || "Unable to sign in. Check your email and password.";
    throw new Error(message);
  }
  return result;
}

export async function signIn(email: string, password: string): Promise<void> {
  saveSession(await authRequest("token?grant_type=password", { email, password }));
}

export async function signUp(email: string, password: string): Promise<boolean> {
  const result = await authRequest("signup", { email, password });
  if (!result.access_token) return false;
  saveSession(result);
  return true;
}

export async function accessToken(): Promise<string | null> {
  // Supabase confirmation links can return an implicit session in the fragment.
  const callback = new URLSearchParams(window.location.hash.slice(1));
  if (callback.has("access_token") || callback.has("error_description")) {
    window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}`);
    if (callback.has("error_description")) throw new Error(callback.get("error_description") || "This confirmation link could not be used. Please sign in.");
    saveSession({ access_token: callback.get("access_token") || undefined, refresh_token: callback.get("refresh_token") || undefined, expires_in: Number(callback.get("expires_in")) || 3600 });
  }
  const session = readSession();
  if (!session) return null;
  if (session.expires_at > Date.now() / 1000 + 60) return session.access_token;
  if (!refreshing) {
    refreshing = authRequest("token?grant_type=refresh_token", { refresh_token: session.refresh_token })
      .then(saveSession)
      .catch((error) => { localStorage.removeItem(STORAGE_KEY); throw error; })
      .finally(() => { refreshing = null; });
  }
  return (await refreshing).access_token;
}

export function clearSession(): void { localStorage.removeItem(STORAGE_KEY); }

export async function signOut(): Promise<void> {
  const session = readSession();
  clearSession();
  if (!session) return;
  const settings = await loadAuthConfig();
  await fetch(`${settings.auth_url.replace(/\/$/, "")}/auth/v1/logout`, {
    method: "POST", headers: { apikey: settings.auth_publishable_key, Authorization: `Bearer ${session.access_token}` },
  }).catch(() => undefined);
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await accessToken();
  if (!token) throw new Error("Your session has ended. Please sign in again.");
  const response = await fetch(apiUrl(path), {
    ...init, cache: "no-store",
    headers: { ...init?.headers, Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  if (response.status === 401) {
    clearSession();
    throw new Error("Your session has ended. Please sign in again.");
  }
  if (!response.ok) {
    if (response.status === 404) throw new Error("This check could not be found in your account.");
    if (response.status === 409) throw new Error("A check with this request is still processing. Wait a moment, then retry.");
    if (response.status === 422) throw new Error("Some details could not be accepted. Review the product and bill fields, then try again.");
    if (response.status === 429) throw new Error("Too many requests. Please wait a moment, then retry.");
    throw new Error("We could not complete this request. Please try again.");
  }
  return response.json() as Promise<T>;
}
