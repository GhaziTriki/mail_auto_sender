export class ApiError extends Error {
  status: number;
  code: string;
  body: any;
  constructor(status: number, body: any) {
    super(typeof body?.detail === "string" ? body.detail : `Request failed (${status})`);
    this.status = status;
    this.code = body?.code ?? "error";
    this.body = body;
  }
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.json || opts.form ? "POST" : "GET") };
  if (opts.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    init.body = opts.form;
  }
  const res = await fetch(path, init);
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text.slice(0, 200) };
  }
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, json?: unknown) => api<T>(p, { method: "POST", json: json ?? {} });
export const patch = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PATCH", json });
export const put = <T = any>(p: string, json: unknown) => api<T>(p, { method: "PUT", json });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });
export const upload = <T = any>(p: string, file: File, method = "POST") => {
  const form = new FormData();
  form.append("file", file);
  return api<T>(p, { method, form });
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : String(e);
}
