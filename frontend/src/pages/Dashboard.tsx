import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api/client";
import type { Paged, Run, Sender } from "../api/types";
import { Empty, ErrorBanner, QuotaBar, StatusChip, fmt, useDebounced } from "../components/ui";

interface Summary {
  kpis: { runs: number; sent: number; failed: number; needs_review: number; no_contact: number; unknown: number };
  sent_per_day: { date: string; sent: number }[];
  senders: (Pick<Sender, "id" | "provider" | "address" | "status" | "quota">)[];
}

const day = (d: Date) => d.toISOString().slice(0, 10);

export default function Dashboard() {
  const [from, setFrom] = useState(() => day(new Date(Date.now() - 30 * 864e5)));
  const [to, setTo] = useState(() => day(new Date()));
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  // date inputs are local days: convert to inclusive local-day UTC bounds
  const fromIso = useMemo(() => new Date(`${from}T00:00:00`).toISOString(), [from]);
  const toIso = useMemo(() => new Date(`${to}T23:59:59.999`).toISOString(), [to]);

  const summary = useQuery({
    queryKey: ["summary", fromIso, toIso, tz],
    queryFn: () => get<Summary>(`/api/dashboard/summary?from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}&tz=${encodeURIComponent(tz)}`),
    refetchInterval: 15000,
  });
  const runs = useQuery({
    queryKey: ["runs", fromIso, toIso, status, dq],
    queryFn: () => {
      const p = new URLSearchParams({ from: fromIso, to: toIso, page_size: "100" });
      if (status) p.set("status", status);
      if (dq) p.set("q", dq);
      return get<Paged<Run>>(`/api/runs?${p}`);
    },
    refetchInterval: 5000,
  });
  const k = summary.data?.kpis;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div><label className="label">From</label><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div><label className="label">To</label><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <div>
          <label className="label">Status</label>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {["draft", "preparing", "ready", "running", "paused_user", "paused_quota", "paused_llm", "paused_errors", "completed"].map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </select>
        </div>
        <div className="flex-1"><label className="label">Search</label><input className="input" placeholder="Run name…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Link to="/runs/new" className="btn btn-primary">New run</Link>
      </div>
      <ErrorBanner error={summary.error || runs.error} />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          ["Runs", k?.runs], ["Sent", k?.sent], ["Failed", k?.failed], ["Needs review", k?.needs_review], ["No contact", k?.no_contact],
        ].map(([label, val]) => (
          <div key={label as string} className="card">
            <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
            <div className="text-2xl font-semibold">{val ?? "-"}</div>
          </div>
        ))}
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="mb-2 text-sm font-semibold">Sent per day</div>
          {summary.data?.sent_per_day.length ? (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={summary.data.sent_per_day}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" fontSize={11} />
                  <YAxis allowDecimals={false} fontSize={11} />
                  <Tooltip />
                  <Bar dataKey="sent" fill="#4f46e5" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty title="No emails sent in this period" hint="Create a run and start it to see activity here." />
          )}
        </div>
        <div className="card">
          <div className="mb-2 text-sm font-semibold">Sender quota (rolling 24 h)</div>
          {summary.data?.senders.length ? (
            <div className="space-y-3">
              {summary.data.senders.map((s) => (
                <div key={s.id}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="truncate">{s.address} <span className="text-xs text-slate-400">({s.provider})</span></span>
                    <StatusChip status={s.quota.state} />
                  </div>
                  <QuotaBar q={s.quota} />
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No senders yet" hint="Add a Gmail account under Senders to start sending." />
          )}
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="min-w-full divide-y divide-slate-200">
          <thead>
            <tr><th className="th">Name</th><th className="th">Status</th><th className="th">Sent</th><th className="th">Pending</th><th className="th">Failed</th><th className="th">Review</th><th className="th">No contact</th><th className="th">Senders</th><th className="th">Created</th><th className="th"></th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.data?.items.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="td font-medium"><Link className="text-indigo-700 hover:underline" to={r.status === "draft" ? `/runs/${r.id}/edit` : `/runs/${r.id}`}>{r.name}</Link></td>
                <td className="td"><StatusChip status={r.status} /></td>
                <td className="td">{r.counts.sent}</td>
                <td className="td">{r.counts.pending}</td>
                <td className="td">{r.counts.failed}</td>
                <td className="td">{r.counts.needs_review}</td>
                <td className="td">{r.counts.no_contact}</td>
                <td className="td text-xs">{r.senders_snapshot.map((s) => s.address).join(", ") || "-"}</td>
                <td className="td text-xs">{fmt(r.created_at)}</td>
                <td className="td text-right">{r.status === "draft" ? <Link className="btn" to={`/runs/${r.id}/edit`}>Continue</Link> : <Link className="btn" to={`/runs/${r.id}`}>Open</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.data && runs.data.items.length === 0 && (
          <div className="p-4"><Empty title="No runs match" hint="Adjust the filters, or create a new run." /></div>
        )}
      </div>
    </div>
  );
}
