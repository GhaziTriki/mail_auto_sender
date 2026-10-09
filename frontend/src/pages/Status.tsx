import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Database, Inbox, RefreshCw, Server, Users } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError, get } from "../api/client";
import type { RunStatus, SystemStatus } from "../api/types";
import { ErrorBanner, Notice, StatusChip, fmt } from "../components/ui";

const TONE: Record<SystemStatus["status"], string> = {
  ok: "border-emerald-200 bg-emerald-100 text-emerald-800",
  degraded: "border-amber-200 bg-amber-100 text-amber-900",
  error: "border-red-200 bg-red-100 text-red-800",
};

// A 503 still carries the status body: show it instead of a bare error.
async function fetchStatus(): Promise<SystemStatus> {
  try {
    return await get<SystemStatus>("/api/status");
  } catch (e) {
    if (e instanceof ApiError && e.body?.status) return e.body as SystemStatus;
    throw e;
  }
}

function duration(s: number): string {
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

function hint(s: SystemStatus): ReactNode {
  if (!s.database.ok)
    return (
      <>
        The database is unreachable ({s.database.error}). Check <code>docker compose ps mongo</code> and{" "}
        <code>docker compose logs mongo</code>.
      </>
    );
  const w = s.worker;
  if (w.state === "never")
    return (
      <>
        The worker has never reported. Nothing is prepared or sent until it runs:{" "}
        <code>docker compose up -d worker</code>.
      </>
    );
  if (w.state === "stale")
    return (
      <>
        The worker has been silent for {duration(w.age_s ?? 0)}. Check <code>docker compose logs worker</code> and
        restart it with <code>docker compose restart worker</code>.
      </>
    );
  if (w.last_error)
    return (
      <>
        The worker's last tick failed ({w.last_error}). See <code>docker compose logs worker</code>.
      </>
    );
  return null;
}

function Dot({ ok }: { ok: boolean | null }) {
  const cls = ok === null ? "bg-slate-300" : ok ? "bg-emerald-500" : "bg-red-500";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} aria-hidden="true" />;
}

function Card({
  icon,
  title,
  ok,
  children,
}: {
  icon: ReactNode;
  title: string;
  ok: boolean | null;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-slate-500">{icon}</span>
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        <Dot ok={ok} />
      </div>
      <dl className="space-y-1.5">{children}</dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium">{value ?? "-"}</dd>
    </div>
  );
}

export default function Status() {
  const q = useQuery({ queryKey: ["status"], queryFn: fetchStatus, refetchInterval: 5000 });
  if (q.error) return <ErrorBanner error={q.error} />;
  const s = q.data;
  if (!s) return <div className="card">Loading…</div>;
  const w = s.worker;
  const runs = s.runs ? (Object.entries(s.runs.by_status) as [RunStatus, number][]).filter(([, n]) => n > 0) : [];
  const total = runs.reduce((acc, [, n]) => acc + n, 0);
  const advice = hint(s);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Status</h1>
        <span className={`rounded-full border px-2.5 py-0.5 text-sm font-medium ${TONE[s.status]}`}>{s.status}</span>
        <span className="text-xs text-slate-500">checked {fmt(s.checked_at)} · refreshes every 5 s</span>
        <button type="button" className="btn ml-auto" onClick={() => q.refetch()} disabled={q.isFetching}>
          <RefreshCw size={14} className={q.isFetching ? "animate-spin" : ""} /> Refresh
        </button>
      </div>
      {advice && <Notice tone="warn">{advice}</Notice>}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card icon={<Server size={16} />} title="API" ok={true}>
          <Row label="Version" value={s.api.version} />
          <Row label="Python" value={s.api.python} />
          <Row label="Started" value={fmt(s.api.started_at)} />
          <Row label="Uptime" value={duration(s.api.uptime_s)} />
        </Card>

        <Card icon={<Database size={16} />} title="Database" ok={s.database.ok}>
          <Row label="MongoDB" value={s.database.ok ? "reachable" : "unreachable"} />
          <Row label="Database name" value={s.database.name} />
          <Row label="Ping" value={s.database.latency_ms === null ? null : `${s.database.latency_ms} ms`} />
          {s.database.error && <Row label="Error" value={<span className="text-red-700">{s.database.error}</span>} />}
        </Card>

        <Card icon={<Cpu size={16} />} title="Worker" ok={w.ok}>
          <Row label="State" value={<StatusChip status={w.state === "alive" ? "active" : w.state} />} />
          <Row
            label="Last tick"
            value={w.last_tick_at ? `${fmt(w.last_tick_at)} (${duration(w.age_s ?? 0)} ago)` : "never"}
          />
          <Row label="Started" value={fmt(w.started_at)} />
          <Row label="Tick interval" value={`${w.tick_s} s`} />
          <Row label="Host" value={w.host} />
          {w.last_error && <Row label="Last error" value={<span className="text-red-700">{w.last_error}</span>} />}
        </Card>

        <Card icon={<Activity size={16} />} title="Runs" ok={s.runs ? null : false}>
          <Row label="Total" value={s.runs ? total : null} />
          <Row label="Active (preparing or running)" value={s.runs?.active} />
          <div className="flex flex-wrap gap-1.5 pt-1">
            {runs.map(([st, n]) => (
              <span key={st} className="inline-flex items-center gap-1 text-xs">
                <StatusChip status={st} />
                {n}
              </span>
            ))}
            {s.runs && runs.length === 0 && <span className="text-xs text-slate-500">No runs yet.</span>}
          </div>
        </Card>

        <Card
          icon={<Inbox size={16} />}
          title="Emails"
          ok={s.items ? (s.items.sending === 0 || w.ok) && s.items.unknown === 0 : false}
        >
          <Row label="Pending" value={s.items?.pending} />
          <Row label="Sending now" value={s.items?.sending} />
          <Row label="Failed" value={s.items?.failed} />
          <Row label="Needs review" value={s.items?.needs_review} />
          <Row label="Unknown outcome" value={s.items?.unknown} />
        </Card>

        <Card
          icon={<Users size={16} />}
          title="Senders and providers"
          ok={s.senders ? (s.senders.total === 0 ? null : s.senders.available > 0) : false}
        >
          <Row label="Senders" value={s.senders?.total} />
          <Row label="Available now" value={s.senders?.available} />
          <Row label="Exhausted (24 h cap)" value={s.senders?.exhausted} />
          <Row label="Idle / auth failed" value={s.senders ? `${s.senders.idle} / ${s.senders.auth_failed}` : null} />
          <Row
            label="Providers"
            value={Object.entries(s.providers)
              .map(([name, on]) => `${name}: ${on ? "on" : "off"}`)
              .join(", ")}
          />
          <Row label="LLM" value={`${s.llm.model}${s.llm.fake ? " (fake)" : ""}`} />
        </Card>
      </div>
    </div>
  );
}
