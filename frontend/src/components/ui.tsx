import { type ReactNode, useState } from "react";
import { AlertTriangle, Info, X } from "lucide-react";
import { errorText } from "../api/client";
import type { Quota } from "../api/types";

const CHIP: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  preparing: "bg-sky-100 text-sky-800",
  ready: "bg-indigo-100 text-indigo-800",
  running: "bg-emerald-100 text-emerald-800",
  paused_user: "bg-amber-100 text-amber-800",
  paused_quota: "bg-orange-100 text-orange-800",
  paused_llm: "bg-orange-100 text-orange-800",
  paused_errors: "bg-red-100 text-red-800",
  completed: "bg-green-100 text-green-800",
  pending: "bg-slate-100 text-slate-700",
  sending: "bg-sky-100 text-sky-800",
  sent: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  no_contact: "bg-zinc-100 text-zinc-700",
  needs_review: "bg-amber-100 text-amber-800",
  skipped_duplicate: "bg-zinc-100 text-zinc-600",
  skipped_user: "bg-zinc-100 text-zinc-600",
  unknown: "bg-purple-100 text-purple-800",
  active: "bg-emerald-100 text-emerald-800",
  idle: "bg-slate-200 text-slate-700",
  auth_failed: "bg-red-100 text-red-800",
  exhausted: "bg-orange-100 text-orange-800",
};

export function StatusChip({ status }: { status: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${CHIP[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function fmt(dt: string | null | undefined): string {
  return dt ? new Date(dt).toLocaleString() : "-";
}

export function fmtTime(dt: string | null | undefined): string {
  return dt ? new Date(dt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-";
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="mb-3 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{errorText(error)}</span>
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const cls = tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-sky-200 bg-sky-50 text-sky-900";
  return (
    <div className={`mb-3 flex items-start gap-2 rounded-md border p-3 text-sm ${cls}`}>
      <Info size={16} className="mt-0.5 shrink-0" />
      <div>{children}</div>
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center">
      <div className="font-medium text-slate-700">{title}</div>
      {hint && <div className="mt-1 text-sm text-slate-500">{hint}</div>}
    </div>
  );
}

export function QuotaBar({ q, label }: { q: Quota; label?: string }) {
  const pct = q.cap ? Math.min(100, Math.round((q.used / q.cap) * 100)) : 0;
  const color = q.exhausted ? "bg-orange-500" : pct > 80 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="min-w-[140px]">
      <div className="mb-1 flex justify-between text-xs text-slate-600">
        <span>{label ?? "Used"}</span>
        <span>
          {q.used}/{q.cap}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      {q.resets_at && q.exhausted && <div className="mt-1 text-xs text-slate-500">resets {fmt(q.resets_at)}</div>}
    </div>
  );
}

export function Modal({ title, children, onClose, wide }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className={`max-h-[90vh] w-full overflow-auto rounded-lg bg-white p-5 shadow-xl ${wide ? "max-w-4xl" : "max-w-lg"}`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button type="button" className="rounded-sm p-1 hover:bg-slate-100" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmButton({
  children, message, onConfirm, className = "btn", disabled,
}: { children: ReactNode; message: string; onConfirm: () => void; className?: string; disabled?: boolean }) {
  return (
    <button type="button"
      className={className}
      disabled={disabled}
      onClick={() => {
        if (window.confirm(message)) onConfirm();
      }}
    >
      {children}
    </button>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useStateEffect(value, ms, setV);
  return v;
}

import { useEffect } from "react";
function useStateEffect<T>(value: T, ms: number, set: (v: T) => void) {
  useEffect(() => {
    const t = setTimeout(() => set(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
}
