import { ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Pause, Play, Trash2, Undo2 } from "lucide-react";
import { ApiError, del, get, patch, post } from "../api/client";
import type { Item, Paged, Run, Sender } from "../api/types";
import { RUN_ACTIVE } from "../api/types";
import ItemsTable from "../components/ItemsTable";
import RunDetails from "../components/RunDetails";
import SendWindow from "../components/SendWindow";
import { ConfirmButton, ErrorBanner, Modal, Notice, StatusChip, Toggle, fmt, fmtTime } from "../components/ui";

type Tab = "queue" | "window" | "sent" | "failed" | "no_contact" | "review" | "unknown" | "skipped" | "details";

export default function RunPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab | null>(null);
  const [resolve, setResolve] = useState(false);
  const [problem, setProblem] = useState<ApiError | null>(null);
  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => get<Run>(`/api/runs/${id}`),
    refetchInterval: (q) => (q.state.data && RUN_ACTIVE.includes(q.state.data.status) ? 3000 : false),
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["run", id] }); qc.invalidateQueries({ queryKey: ["items", id] }); qc.invalidateQueries({ queryKey: ["next", id] }); };
  const act = useMutation({
    mutationFn: (a: { path: string; body?: object }) => post(`/api/runs/${id}/${a.path}`, a.body),
    onSuccess: () => { setProblem(null); refresh(); },
    onError: (e) => { if (e instanceof ApiError) setProblem(e); },
  });
  const setApproval = useMutation({ mutationFn: (approval: string) => patch(`/api/runs/${id}`, { approval }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => del(`/api/runs/${id}`), onSuccess: () => nav("/") });

  if (run.isLoading) return <div className="card">Loading…</div>;
  if (run.error || !run.data) return <ErrorBanner error={run.error ?? "Run not found"} />;
  const r = run.data;
  const c = r.counts;
  const done = c.total - c.pending - c.sending;
  const pct = c.total ? Math.round((done / c.total) * 100) : 0;
  const manual = r.approval === "manual";
  const current: Tab = tab ?? (manual && ["running", "paused_user", "paused_quota", "ready"].includes(r.status) ? "window" : "queue");
  const tabs: [Tab, string, number | null][] = [
    ["queue", "Preview / Queue", c.pending + c.sending],
    ...(manual ? ([["window", "Send window", null]] as [Tab, string, number | null][]) : []),
    ["sent", "Sent", c.sent],
    ["failed", "Failed", c.failed],
    ["no_contact", "No contact", c.no_contact],
    ["review", "Needs review", c.needs_review],
    ["unknown", "Unknown", c.unknown],
    ["skipped", "Skipped", c.skipped_duplicate + c.skipped_user],
    ["details", "Details", null],
  ];
  const startClick = () => (manual && c.needs_review > 0 ? setResolve(true) : act.mutate({ path: "start" }));
  const used = Array.from(new Set(r.senders_snapshot.map((s) => s.address))).join(", ");

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{r.name}</h1>
        <StatusChip status={r.status} />
        <span className="text-xs text-slate-500">senders: {used || "-"}</span>
        <div className="flex-1" />
        <Toggle checked={manual} onChange={(v) => setApproval.mutate(v ? "manual" : "auto")} label="Manual approval" />
        {r.status === "ready" && <>
          <button className="btn btn-primary" disabled={act.isPending} onClick={startClick}><Play size={14} /> Start</button>
          <ConfirmButton message="Unprepare this run? All prepared emails are deleted and the run goes back to a draft." onConfirm={() => act.mutate({ path: "unprepare" })}><Undo2 size={14} /> Unprepare</ConfirmButton>
        </>}
        {r.status === "running" && <button className="btn" onClick={() => act.mutate({ path: "pause" })}><Pause size={14} /> Pause</button>}
        {["paused_user", "paused_quota", "paused_llm", "paused_errors"].includes(r.status) && <button className="btn btn-primary" onClick={() => act.mutate({ path: "resume" })}><Play size={14} /> Resume</button>}
        <a className="btn" href={`/api/runs/${id}/export.csv`}><Download size={14} /> CSV</a>
        <ConfirmButton className="btn" message="Delete this run? Its files and emails are removed. Contacts that were already emailed stay locked, so they are never emailed twice by accident." onConfirm={() => remove.mutate()}><Trash2 size={14} /> Delete</ConfirmButton>
      </div>
      <ErrorBanner error={remove.error || setApproval.error || (problem && problem.code !== "no_sender_available" && problem.code !== "no_key_available" ? problem : null)} />

      <div className="mb-3">
        <div className="mb-1 flex justify-between text-xs text-slate-500"><span>{done} of {c.total} handled</span><span>{pct}%</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full bg-indigo-600 transition-all" style={{ width: `${pct}%` }} /></div>
      </div>

      <PauseBanner run={r} problem={problem} onAction={(path, body) => act.mutate({ path, body })} refresh={refresh} />
      {r.status === "preparing" && <Notice>Preparing: classifying contacts and rendering emails…</Notice>}
      {r.status === "ready" && manual && c.needs_review > 0 && <Notice tone="warn">{c.needs_review} contact(s) were already emailed in another run. Resolve them (Resend or Skip) before starting. <button className="underline" onClick={() => setResolve(true)}>Resolve now</button></Notice>}
      {r.status === "ready" && !manual && c.needs_review > 0 && <Notice tone="warn">{c.needs_review} already-emailed contact(s) will stay unsent unless you choose Resend in the Needs review tab.</Notice>}

      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
        {tabs.map(([t, label, n]) => (
          <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${current === t ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
            {label}{n !== null && <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-600">{n}</span>}
          </button>
        ))}
      </div>

      {current === "queue" && <ItemsTable run={r} statuses={["pending", "sending"]} columns={["email", "greeting", "subject", "warnings", "status"]}
        actions={manual ? [{ action: "approve", label: "Approve selected", primary: true }, { action: "skip", label: "Skip selected", confirm: "Skip the selected emails?" }] : [{ action: "skip", label: "Skip selected", confirm: "Skip the selected emails?" }]}
        empty={{ title: "Nothing in the queue", hint: r.status === "draft" ? "Prepare the run first." : "Every email has been handled." }} />}
      {current === "window" && <SendWindow run={r} />}
      {current === "sent" && <ItemsTable run={r} statuses={["sent"]} columns={["email", "sender", "sent_at", "subject"]} empty={{ title: "Nothing sent yet", hint: "Sent emails appear here with their sender and time. Click a row to read the email." }} />}
      {current === "failed" && <ItemsTable run={r} statuses={["failed"]} columns={["email", "error", "subject"]}
        actions={[{ action: "rerun", label: "Rerun selected", primary: true }, { action: "skip", label: "Skip selected" }]}
        empty={{ title: "No failed emails", hint: "Failed emails are never retried automatically. Select some and Rerun them." }} />}
      {current === "no_contact" && <ItemsTable run={r} statuses={["no_contact"]} columns={["email", "warnings"]} empty={{ title: "No rows without a contact", hint: "Rows whose email cell has no valid address show up here and are never sent." }} />}
      {current === "review" && <ItemsTable run={r} statuses={["needs_review"]} columns={["email", "prior", "subject"]}
        actions={[{ action: "resend", label: "Resend selected", primary: true, confirm: "These contacts were already emailed. Send to them again?" }, { action: "skip", label: "Skip selected" }]}
        empty={{ title: "Nothing to review", hint: "Contacts already emailed in another run appear here instead of being sent again." }} />}
      {current === "unknown" && <ItemsTable run={r} statuses={["unknown"]} columns={["email", "sender", "error", "subject"]}
        actions={[{ action: "mark_sent", label: "Mark as sent", primary: true }, { action: "rerun", label: "Rerun selected", confirm: "The email may already have been delivered. Send it again?" }]}
        empty={{ title: "No uncertain emails", hint: "An email is “unknown” when the connection dropped while sending: check your Sent folder, then mark it as sent or rerun it." }} />}
      {current === "skipped" && <ItemsTable run={r} statuses={["skipped_duplicate", "skipped_user"]} columns={["email", "status", "prior"]} empty={{ title: "Nothing skipped" }} />}
      {current === "details" && <RunDetails run={r} />}

      {resolve && <ResolveDialog run={r} onClose={() => { setResolve(false); refresh(); }} onStart={() => { setResolve(false); act.mutate({ path: "start" }); }} />}
    </div>
  );
}

function PauseBanner({ run, problem, onAction, refresh }: { run: Run; problem: ApiError | null; onAction: (path: string, body?: object) => void; refresh: () => void }) {
  const [editSenders, setEditSenders] = useState(false);
  const d = run.pause_detail ?? {};
  const senders = useQuery({ queryKey: ["senders"], queryFn: () => get<Sender[]>("/api/senders"), enabled: run.status === "paused_quota" });
  const setIds = useMutation({ mutationFn: (ids: string[]) => patch(`/api/runs/${run.id}`, { sender_ids: ids }), onSuccess: refresh });
  const switchRules = useMutation({
    mutationFn: async () => { await patch(`/api/runs/${run.id}`, { mode: "rules" }); await post(`/api/runs/${run.id}/resume`); },
    onSuccess: refresh,
  });
  const detail = problem?.code === "no_sender_available" || problem?.code === "no_key_available" ? problem.body : d;
  const reset = detail?.earliest_reset_at as string | undefined;
  const why = (list: { address?: string; id: string; reason: string }[] | undefined) => list?.map((x) => `${x.address ?? x.id.slice(-4)}: ${x.reason}`).join(" · ");

  if (run.status === "paused_quota") {
    return (
      <div className="mb-4 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
        <div className="font-semibold">All senders exhausted{reset ? ` — resets at ${fmtTime(reset)} (${fmt(reset)})` : ""}</div>
        <div className="mt-1 text-xs">{why(detail?.senders)}</div>
        {problem?.code === "no_sender_available" && <div className="mt-1 text-xs font-medium">Still no sender is available. Add one or wait for the reset, then click Resume again.</div>}
        <div className="mt-2 flex flex-wrap gap-2">
          <Link className="btn" to="/settings/senders">Add sender</Link>
          <button className="btn" onClick={() => setEditSenders((v) => !v)}>Choose senders for this run</button>
          <button className="btn btn-primary" onClick={() => onAction("resume")}>Resume</button>
        </div>
        {editSenders && (
          <div className="mt-2 rounded-sm bg-white p-2">
            {senders.data?.map((s) => (
              <label key={s.id} className="mr-4 inline-flex items-center gap-1 text-sm text-slate-800">
                <input type="checkbox" checked={run.sender_ids.includes(s.id)} onChange={() => setIds.mutate(run.sender_ids.includes(s.id) ? run.sender_ids.filter((x) => x !== s.id) : [...run.sender_ids, s.id])} />{s.address} <span className="text-xs text-slate-500">{s.quota.used}/{s.quota.cap} {s.quota.state}</span>
              </label>
            ))}
            <ErrorBanner error={setIds.error} />
          </div>
        )}
      </div>
    );
  }
  if (run.status === "paused_llm") {
    return (
      <div className="mb-4 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
        <div className="font-semibold">Gemini keys exhausted or unusable{reset ? ` — quota resets at ${fmtTime(reset)}` : ""}</div>
        <div className="mt-1 text-xs">{why(detail?.keys)}</div>
        {problem?.code === "no_key_available" && <div className="mt-1 text-xs font-medium">Still no key is available.</div>}
        <ErrorBanner error={switchRules.error} />
        <div className="mt-2 flex flex-wrap gap-2">
          <Link className="btn" to="/settings/llm">Add key</Link>
          <ConfirmButton message="Switch this run to rules mode? The remaining contacts are classified by fixed rules (tagged decided by rules)." onConfirm={() => switchRules.mutate()}>Switch to rules</ConfirmButton>
          <button className="btn btn-primary" onClick={() => onAction("resume")}>Resume</button>
        </div>
      </div>
    );
  }
  if (run.status === "paused_errors") {
    return (
      <div className="mb-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
        <div className="font-semibold">Paused after {run.consecutive_failures} consecutive failures</div>
        <ul className="mt-1 list-disc pl-5 text-xs">{(d.last_errors as string[] | undefined)?.map((e, i) => <li key={i}>{e}</li>)}</ul>
        <div className="mt-2"><button className="btn btn-primary" onClick={() => onAction("resume")}>Resume</button></div>
      </div>
    );
  }
  if (run.status === "paused_user") return <Notice tone="warn">Paused by you. Click Resume to continue.</Notice>;
  return null;
}

function ResolveDialog({ run, onClose, onStart }: { run: Run; onClose: () => void; onStart: () => void }) {
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["items", run.id, "resolve"], queryFn: () => get<Paged<Item>>(`/api/runs/${run.id}/items?status=needs_review&page_size=200`) });
  const act = useMutation({
    mutationFn: (b: { action: string; item_ids?: string[]; status_filter?: string }) => post(`/api/runs/${run.id}/items/bulk`, b),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["items", run.id] }); qc.invalidateQueries({ queryKey: ["run", run.id] }); },
  });
  const items = data.data?.items ?? [];
  const left = data.data?.total ?? 0;
  return (
    <Modal title="Resolve already-emailed contacts" onClose={onClose} wide>
      <p className="mb-3 text-sm text-slate-600">These contacts were already emailed in another run. Nothing is sent to them without your decision. Manual runs cannot start until all of them are resolved.</p>
      <ErrorBanner error={act.error || data.error} />
      <div className="mb-3 flex gap-2">
        <button className="btn" disabled={!left || act.isPending} onClick={() => act.mutate({ action: "resend", status_filter: "needs_review" })}>Resend all</button>
        <button className="btn" disabled={!left || act.isPending} onClick={() => act.mutate({ action: "skip", status_filter: "needs_review" })}>Skip all</button>
      </div>
      <div className="max-h-96 overflow-auto rounded-sm border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50"><tr><th className="th">Email</th><th className="th">Previously sent</th><th className="th"></th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((i) => (
              <tr key={i.id}>
                <td className="td font-medium">{i.email_norm}</td>
                <td className="td text-xs">{i.prior_send ? `${i.prior_send.run_name} · ${i.prior_send.sender_address} · ${fmt(i.prior_send.sent_at)}` : "-"}</td>
                <td className="td text-right"><button className="btn mr-1" onClick={() => act.mutate({ action: "resend", item_ids: [i.id] })}>Resend</button><button className="btn" onClick={() => act.mutate({ action: "skip", item_ids: [i.id] })}>Skip</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <div className="p-4 text-center text-sm text-slate-500">All resolved.</div>}
      </div>
      <div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={onClose}>Close</button><button className="btn btn-primary" disabled={left > 0} onClick={onStart}>Start run</button></div>
    </Modal>
  );
}
