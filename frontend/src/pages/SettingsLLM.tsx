import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Trash2 } from "lucide-react";
import { del, errorText, get, patch, post } from "../api/client";
import type { AppConfig, LlmKey } from "../api/types";
import { LLM_QUOTA_WARNING, LLM_WARNING } from "../api/types";
import { ConfirmButton, Empty, ErrorBanner, Notice, QuotaBar, StatusChip, Toggle, fmt } from "../components/ui";

export default function SettingsLLM() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["llm-keys"] });
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => get<AppConfig>("/api/config") });
  const keys = useQuery({ queryKey: ["llm-keys"], queryFn: () => get<LlmKey[]>("/api/llm-keys"), refetchInterval: 10000 });
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [cap, setCap] = useState("");
  const add = useMutation({
    mutationFn: () => post("/api/llm-keys", { label, api_key: apiKey, daily_cap: cap ? Number(cap) : null }),
    onSuccess: () => { setLabel(""); setApiKey(""); setCap(""); refresh(); },
  });

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Gemini API keys</h1>
        <a className="inline-flex items-center gap-1 text-sm text-indigo-700 hover:underline" href="/docs-static/llm/gemini.md" target="_blank" rel="noreferrer"><ExternalLink size={14} /> Setup guide</a>
      </div>
      <Notice tone="warn"><div>{LLM_WARNING}</div><div className="mt-1 text-xs">{LLM_QUOTA_WARNING}</div></Notice>
      <p className="mb-3 text-sm text-slate-600">Keys are optional: rules mode needs none. The daily quota resets at midnight Pacific time; the reset time below is shown in your local time.</p>
      <ErrorBanner error={keys.error} />
      {keys.data?.length === 0 && <div className="mb-4"><Empty title="No keys yet" hint="Add a Gemini key to use LLM greetings, or choose rules mode in the run wizard." /></div>}
      {keys.data?.map((k) => <KeyRow key={k.id} k={k} onChange={refresh} />)}
      <div className="card">
        <h2 className="mb-2 font-semibold">Add key</h2>
        <ErrorBanner error={add.error} />
        <div className="grid gap-3 md:grid-cols-3">
          <div><label className="label">Label</label><input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Project A" /></div>
          <div><label className="label">API key</label><input className="input" type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></div>
          <div><label className="label">Daily cap (requests)</label><input className="input" type="number" min={1} value={cap} onChange={(e) => setCap(e.target.value)} placeholder={String(cfg.data?.defaults.llm_daily_cap ?? 200)} /></div>
        </div>
        <button type="button" className="btn btn-primary mt-3" disabled={!label || !apiKey || add.isPending} onClick={() => add.mutate()}>Add key</button>
      </div>
    </div>
  );
}

function KeyRow({ k, onChange }: { k: LlmKey; onChange: () => void }) {
  const [cap, setCap] = useState(String(k.daily_cap));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const upd = useMutation({ mutationFn: (b: object) => patch(`/api/llm-keys/${k.id}`, b), onSuccess: onChange });
  const check = useMutation({
    mutationFn: () => post(`/api/llm-keys/${k.id}/check`),
    onSuccess: (r: any) => { setMsg({ ok: r.ok, text: r.detail }); onChange(); },
    onError: (e) => setMsg({ ok: false, text: errorText(e) }),
  });
  const remove = useMutation({ mutationFn: () => del(`/api/llm-keys/${k.id}`), onSuccess: onChange });
  return (
    <div className="card mb-3">
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-[160px] flex-1"><div className="font-medium">{k.label}</div><div className="text-xs text-slate-500">resets {fmt(k.quota.resets_at)}</div></div>
        <StatusChip status={k.quota.state === "exhausted" ? "exhausted" : k.status} />
        <QuotaBar q={k.quota} label="Used today" />
        <Toggle checked={k.status !== "idle"} label="Active" onChange={(v) => upd.mutate({ status: v ? "active" : "idle" })} />
        <div className="flex items-center gap-1">
          <span className="text-xs text-slate-500">Cap</span>
          <input className="input w-20" type="number" min={1} value={cap} onChange={(e) => setCap(e.target.value)} onBlur={() => Number(cap) !== k.daily_cap && upd.mutate({ daily_cap: Number(cap) })} />
        </div>
        <div className="flex gap-2">
          <button type="button" className="btn" onClick={() => check.mutate()} disabled={check.isPending}><CheckCircle2 size={14} /> Check</button>
          <ConfirmButton message={`Delete key "${k.label}"?`} onConfirm={() => remove.mutate()}><Trash2 size={14} /> Delete</ConfirmButton>
        </div>
      </div>
      {k.last_error && <div className="mt-2 text-xs text-red-700">Last error: {k.last_error}</div>}
      {msg && <div className={`mt-2 text-xs ${msg.ok ? "text-green-700" : "text-red-700"}`}>{msg.text}</div>}
      <ErrorBanner error={upd.error || remove.error} />
    </div>
  );
}
