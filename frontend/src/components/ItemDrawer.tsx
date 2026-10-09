import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { errorText, get, patch, post } from "../api/client";
import type { Item, Run } from "../api/types";
import { ErrorBanner, Modal, StatusChip, fmt } from "./ui";

interface NextInfo {
  sender: { address: string; provider: string } | null;
  sender_problem: unknown;
}

export default function ItemDrawer({ run, item, onClose }: { run: Run; item: Item; onClose: () => void }) {
  const qc = useQueryClient();
  const editable = ["pending", "needs_review", "failed"].includes(item.status);
  const [subject, setSubject] = useState(item.subject);
  const [body, setBody] = useState(item.body);
  const [kind, setKind] = useState(item.kind ?? "company");
  const [name, setName] = useState(item.name ?? "");
  const [company, setCompany] = useState(item.company ?? "");
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    setSubject(item.subject);
    setBody(item.body);
    setKind(item.kind ?? "company");
    setName(item.name ?? "");
    setCompany(item.company ?? "");
  }, [item.id, item.subject, item.body]);
  const next = useQuery({
    queryKey: ["next", run.id],
    queryFn: () => get<NextInfo>(`/api/runs/${run.id}/next`),
    enabled: item.status === "pending",
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["items", run.id] });
    qc.invalidateQueries({ queryKey: ["run", run.id] });
    qc.invalidateQueries({ queryKey: ["next", run.id] });
  };
  const save = useMutation({
    mutationFn: () => {
      const b: Record<string, string> = {};
      if (subject !== item.subject) b.subject = subject;
      if (body !== item.body) b.body = body;
      if (kind !== (item.kind ?? "company")) b.kind = kind;
      if (name !== (item.name ?? "")) b.name = name;
      if (company !== (item.company ?? "")) b.company = company;
      return patch<Item>(`/api/items/${item.id}`, b);
    },
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  const test = useMutation({
    mutationFn: () =>
      post<{ ok: boolean; detail: string; to: string }>(`/api/runs/${run.id}/test-send`, { item_id: item.id }),
    onSuccess: (r) => setTestMsg({ ok: r.ok, text: r.ok ? `Test email sent to ${r.to}` : r.detail }),
    onError: (e) => setTestMsg({ ok: false, text: errorText(e) }),
  });
  const lastAttempt = item.attempts[item.attempts.length - 1];
  const dirty =
    subject !== item.subject ||
    body !== item.body ||
    kind !== (item.kind ?? "company") ||
    name !== (item.name ?? "") ||
    company !== (item.company ?? "");

  return (
    <Modal title={item.email_norm ?? `Row ${item.row_index + 2}`} onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <StatusChip status={item.status} />
        {item.edited && <span className="rounded-sm bg-sky-100 px-2 text-xs text-sky-800">edited</span>}
        {item.approved && <span className="rounded-sm bg-emerald-100 px-2 text-xs text-emerald-800">approved</span>}
      </div>
      <div className="mb-4 grid gap-3 text-sm md:grid-cols-2">
        <div className="rounded-sm bg-slate-50 p-3">
          <div className="label">Contact line used</div>
          <div>
            Column: <b>{item.contact_line.column}</b>
          </div>
          <div className="break-all">
            Raw cell: <code>{item.contact_line.raw || "(empty)"}</code>
          </div>
          <div>
            Extracted address: <b>{item.contact_line.email ?? "none"}</b>
          </div>
        </div>
        <div className="rounded-sm bg-slate-50 p-3">
          <div className="label">Greeting decision</div>
          <div>
            Kind: <b>{item.kind ?? "-"}</b> · decided by <b>{item.decided_by ?? "-"}</b>
          </div>
          <div>
            Name: {item.name ?? "-"} · Company: {item.company ?? "-"} · Honorific: {item.honorific ?? "-"}
          </div>
          <div>
            Warnings:{" "}
            {item.warnings.length
              ? item.warnings.map((w) => (
                  <span key={w} className="mr-1 rounded-sm bg-amber-100 px-1.5 text-xs text-amber-800">
                    {w}
                  </span>
                ))
              : "none"}
          </div>
        </div>
        {item.status === "pending" && (
          <div className="rounded-sm bg-slate-50 p-3 md:col-span-2">
            <div className="label">Sender that will be used</div>
            {next.data?.sender ? (
              <b>
                {next.data.sender.address}{" "}
                <span className="text-xs font-normal text-slate-500">({next.data.sender.provider})</span>
              </b>
            ) : (
              <span className="text-orange-700">No sender is available right now.</span>
            )}
          </div>
        )}
        {item.prior_send && (
          <div className="rounded-sm bg-amber-50 p-3 md:col-span-2 text-amber-900">
            Already sent{item.prior_send.uncertain ? " (uncertain)" : ""} in run <b>{item.prior_send.run_name}</b> from{" "}
            {item.prior_send.sender_address} on {fmt(item.prior_send.sent_at)}.
          </div>
        )}
        {item.status === "sent" && (
          <div className="rounded-sm bg-green-50 p-3 md:col-span-2 text-green-900">
            Sent from {item.sender_address} at {fmt(item.sent_at)}.
          </div>
        )}
        {lastAttempt && ["failed", "unknown", "pending"].includes(item.status) && (
          <div className="rounded-sm bg-red-50 p-3 md:col-span-2 text-red-900">
            Last attempt: {lastAttempt.outcome} — {lastAttempt.detail}
          </div>
        )}
      </div>
      {editable && (
        <div className="mb-3 grid gap-3 md:grid-cols-3">
          <div>
            <label className="label">Kind</label>
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as "human" | "company")}>
              <option value="human">human</option>
              <option value="company">company</option>
            </select>
          </div>
          <div>
            <label className="label">Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">Company</label>
            <input className="input" value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
          <div className="md:col-span-3 text-xs text-slate-500">
            Changing kind/name/company re-renders the greeting when you save (unless you also edit the text yourself).
          </div>
        </div>
      )}
      <label className="label">Subject</label>
      <input className="input mb-3" value={subject} readOnly={!editable} onChange={(e) => setSubject(e.target.value)} />
      <label className="label">Body</label>
      <textarea
        className="input h-56 font-mono"
        value={body}
        readOnly={!editable}
        onChange={(e) => setBody(e.target.value)}
      />
      <ErrorBanner error={save.error} />
      {testMsg && (
        <div className={`mt-2 text-sm ${testMsg.ok ? "text-green-700" : "text-red-700"}`}>{testMsg.text}</div>
      )}
      <div className="mt-4 flex items-center justify-between">
        <button type="button" className="btn" disabled={test.isPending} onClick={() => test.mutate()}>
          <Send size={14} /> Send me a test
        </button>
        <div className="flex gap-2">
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          {editable && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate()}
            >
              Save changes
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
