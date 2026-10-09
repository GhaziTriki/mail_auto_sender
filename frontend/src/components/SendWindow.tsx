import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Send, SkipForward } from "lucide-react";
import { get, patch, post } from "../api/client";
import type { Item, Run } from "../api/types";
import { Empty, ErrorBanner, Notice, StatusChip } from "./ui";

interface Next { item: Item | null; sender: { address: string; provider: string } | null; remaining_pending: number; sender_problem: any }

export default function SendWindow({ run }: { run: Run }) {
  const qc = useQueryClient();
  const next = useQuery({
    queryKey: ["next", run.id],
    queryFn: () => get<Next>(`/api/runs/${run.id}/next`),
    refetchInterval: 1500,
  });
  const item = next.data?.item ?? null;
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  useEffect(() => { if (item) { setSubject(item.subject); setBody(item.body); } }, [item?.id]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["next", run.id] }); qc.invalidateQueries({ queryKey: ["run", run.id] }); qc.invalidateQueries({ queryKey: ["items", run.id] }); };
  const send = useMutation({
    mutationFn: async () => {
      if (!item) return;
      if (subject !== item.subject || body !== item.body) await patch(`/api/items/${item.id}`, { subject, body });
      await post(`/api/runs/${run.id}/items/bulk`, { action: "approve", item_ids: [item.id] });
    },
    onSuccess: refresh,
  });
  const skip = useMutation({ mutationFn: () => post(`/api/runs/${run.id}/items/bulk`, { action: "skip", item_ids: [item!.id] }), onSuccess: refresh });
  const approveAll = useMutation({ mutationFn: () => post(`/api/runs/${run.id}/approve-all`), onSuccess: refresh });
  const canSend = run.status === "running";

  if (run.approval !== "manual") return <Notice>This run uses automatic approval, so there is no send window. Switch the approval toggle to manual to approve emails one by one.</Notice>;
  if (!item) return <Empty title={run.status === "completed" ? "All done" : "Nothing waiting for approval"} hint="Pending emails appear here one at a time." />;
  const editable = !item.approved;

  return (
    <div className="mx-auto max-w-3xl">
      {!canSend && <Notice tone="warn">The run is {run.status.replace(/_/g, " ")}. You can review emails now, but sending only happens while the run is running.</Notice>}
      <ErrorBanner error={send.error || skip.error || approveAll.error} />
      <div className="card">
        <div className="mb-3 flex items-center justify-between text-sm"><span>{next.data?.remaining_pending} pending</span>{item.approved && <StatusChip status="sending" />}</div>
        <div className="mb-3 grid gap-3 text-sm md:grid-cols-2">
          <div className="rounded bg-slate-50 p-3"><div className="label">To (contact line used)</div><div className="text-base font-semibold">{item.contact_line.email}</div><div className="text-xs text-slate-500">column “{item.contact_line.column}”, cell “{item.contact_line.raw}”</div></div>
          <div className="rounded bg-slate-50 p-3"><div className="label">From</div>{next.data?.sender ? <div className="text-base font-semibold">{next.data.sender.address}</div> : <div className="text-orange-700">No sender available</div>}<div className="text-xs text-slate-500">{item.kind} · decided by {item.decided_by}{item.warnings.length ? ` · warnings: ${item.warnings.join(", ")}` : ""}</div></div>
        </div>
        <label className="label">Subject</label>
        <input className="input mb-3" value={subject} readOnly={!editable} onChange={(e) => setSubject(e.target.value)} />
        <label className="label">Body</label>
        <textarea className="input mb-4 h-72 font-mono" value={body} readOnly={!editable} onChange={(e) => setBody(e.target.value)} />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-2">
            <button className="btn btn-primary" disabled={item.approved || send.isPending || !next.data?.sender} onClick={() => send.mutate()}><Send size={14} /> {item.approved ? "Sending…" : "Send"}</button>
            <button className="btn" disabled={item.approved || skip.isPending} onClick={() => skip.mutate()}><SkipForward size={14} /> Skip</button>
          </div>
          <button className="btn" disabled={approveAll.isPending} onClick={() => window.confirm(`Approve all ${next.data?.remaining_pending} remaining emails and send them automatically with delays?`) && approveAll.mutate()}><CheckCheck size={14} /> Approve all remaining</button>
        </div>
      </div>
    </div>
  );
}
