import type { HealthInfo } from "./types";

const TOKEN_KEY = "steer_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  fields: { field: string; message: string }[];
  code?: string;

  constructor(
    status: number,
    message: string,
    fields: { field: string; message: string }[] = [],
    code?: string,
  ) {
    super(message);
    this.status = status;
    this.fields = fields;
    this.code = code;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* not json */
  }
  const detail = body?.detail;
  const message =
    typeof detail === "string" && detail
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: any) => d.msg ?? String(d)).join("; ")
        : `Request failed (${res.status})`;
  return new ApiError(res.status, message, body?.errors ?? [], body?.code);
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(path, {
    method: opts.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    signal: opts.signal,
  });

  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ?? {} }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: "POST", formData }),
  health: () => request<HealthInfo>("/api/health"),
};

/** Authenticated URL for an asset (fetch with token is used instead for previews). */
export function assetUrl(assetId: string): string {
  return `/api/assets/${assetId}`;
}
export function assetInlineUrl(assetId: string): string {
  return `/api/assets/${assetId}/inline`;
}

/** Fetch an asset as a blob URL (auth header needed). */
export async function fetchAssetBlobUrl(assetId: string): Promise<string> {
  const token = getToken();
  const res = await fetch(assetUrl(assetId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/** Trigger a browser download of an authenticated asset. */
export async function downloadAsset(assetId: string, filename: string): Promise<void> {
  const url = await fetchAssetBlobUrl(assetId);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
