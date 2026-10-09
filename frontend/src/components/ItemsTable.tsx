import { type ReactNode, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../api/client";
import type { Item, ItemStatus, Paged, Run } from "../api/types";
import { RUN_ACTIVE } from "../api/types";
import ItemDrawer from "./ItemDrawer";
import { Empty, ErrorBanner, StatusChip, fmt, useDebounced } from "./ui";

export interface BulkAction {
  action: "approve" | "skip" | "rerun" | "resend" | "mark_sent";
  label: string;
  primary?: boolean;
  confirm?: string;
}

interface Props {
  run: Run;
  statuses: ItemStatus[];
  columns: ("email" | "greeting" | "subject" | "sender" | "sent_at" | "error" | "prior" | "status" | "warnings")[];
  actions?: BulkAction[];
  empty: { title: string; hint?: string };
  extraHeader?: ReactNode;
}

export default function ItemsTable({ run, statuses, columns, actions = [], empty, extraHeader }: Props) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Item | null>(null);
  const key = statuses.join(",");
  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [key, dq]);
  const live = RUN_ACTIVE.includes(run.status);
  const data = useQuery({
    queryKey: ["items", run.id, key, dq, page],
    queryFn: () =>
      get<Paged<Item>>(`/api/runs/${run.id}/items?status=${key}&page=${page}&page_size=50&q=${encodeURIComponent(dq)}`),
    refetchInterval: live ? 3000 : false,
    placeholderData: (prev) => prev,
  });
  const bulk = useMutation({
    mutationFn: (b: { action: string; item_ids?: string[]; status_filter?: string }) =>
      post(`/api/runs/${run.id}/items/bulk`, b),
    onSuccess: () => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["items", run.id] });
      qc.invalidateQueries({ queryKey: ["run", run.id] });
      qc.invalidateQueries({ queryKey: ["next", run.id] });
    },
  });
  const items = data.data?.items ?? [];
  const total = data.data?.total ?? 0;
  const allOnPage = items.length > 0 && items.every((i) => selected.has(i.id));
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const run_ = (a: BulkAction) => {
    if (a.confirm && !window.confirm(a.confirm)) return;
    bulk.mutate({ action: a.action, item_ids: Array.from(selected) });
  };
  const lastErr = (i: Item) => {
    const a = i.attempts[i.attempts.length - 1];
    return a && a.outcome !== "sent" ? `${a.outcome}: ${a.detail}` : "";
  };
  const head: Record<string, string> = {
    email: "Email",
    greeting: "Greeting",
    subject: "Subject",
    sender: "Sender",
    sent_at: "Sent at",
    error: "Last error",
    prior: "Previously sent",
    status: "Status",
    warnings: "Warnings",
  };
  const cell = (i: Item, c: string): ReactNode => {
    switch (c) {
      case "email":
        return (
          <span className="font-medium">
            {i.email_norm ?? <span className="text-slate-400">{i.email_raw || "(empty cell)"}</span>}
          </span>
        );
      case "greeting":
        return <span className="text-slate-600">{i.greeting_text}</span>;
      case "subject":
        return i.subject;
      case "sender":
        return i.sender_address ?? "-";
      case "sent_at":
        return fmt(i.sent_at);
      case "error":
        return <span className="text-xs text-red-700">{lastErr(i)}</span>;
      case "prior":
        return i.prior_send ? (
          <span className="text-xs">
            {i.prior_send.run_name} · {i.prior_send.sender_address} · {fmt(i.prior_send.sent_at)}
            {i.prior_send.uncertain ? " (uncertain)" : ""}
          </span>
        ) : (
          <span className="text-xs text-slate-400">
            {i.duplicate_reason === "duplicate_in_run" ? "duplicate in this run" : "-"}
          </span>
        );
      case "status":
        return <StatusChip status={i.status} />;
      case "warnings":
        return i.warnings.map((w) => (
          <span key={w} className="mr-1 rounded-sm bg-amber-100 px-1.5 text-xs text-amber-800">
            {w}
          </span>
        ));
      default:
        return null;
    }
  };
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input max-w-xs"
          placeholder="Search email, name, subject…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-sm text-slate-500">{total} item(s)</span>
        <div className="flex-1" />
        {extraHeader}
        {actions.map((a) => (
          <button
            type="button"
            key={a.action + a.label}
            className={`btn ${a.primary ? "btn-primary" : ""}`}
            disabled={selected.size === 0 || bulk.isPending}
            onClick={() => run_(a)}
          >
            {a.label}
            {selected.size ? ` (${selected.size})` : ""}
          </button>
        ))}
      </div>
      <ErrorBanner error={data.error || bulk.error} />
      {items.length === 0 && !data.isLoading ? (
        <Empty {...empty} />
      ) : (
        <div className="overflow-x-auto rounded-sm border border-slate-200 bg-white">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                {actions.length > 0 && (
                  <th className="th w-8">
                    <input
                      type="checkbox"
                      checked={allOnPage}
                      onChange={() => setSelected(allOnPage ? new Set() : new Set(items.map((i) => i.id)))}
                    />
                  </th>
                )}
                <th className="th w-12">Row</th>
                {columns.map((c) => (
                  <th key={c} className="th">
                    {head[c]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((i) => (
                <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(i)}>
                  {actions.length > 0 && (
                    <td className="td" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={selected.has(i.id)} onChange={() => toggle(i.id)} />
                    </td>
                  )}
                  <td className="td text-slate-400">{i.row_index + 2}</td>
                  {columns.map((c) => (
                    <td key={c} className="td max-w-xs truncate">
                      {cell(i, c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > 50 && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm">
          <button type="button" className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>
            Page {page} / {Math.ceil(total / 50)}
          </span>
          <button
            type="button"
            className="btn"
            disabled={page >= Math.ceil(total / 50)}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      )}
      {open && <ItemDrawer run={run} item={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
