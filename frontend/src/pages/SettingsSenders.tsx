import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Pencil, Plug, Trash2 } from "lucide-react";
import { del, errorText, get, patch, post } from "../api/client";
import type { AppConfig, Provider, Sender } from "../api/types";
import { ConfirmButton, Empty, ErrorBanner, Modal, Notice, QuotaBar, StatusChip, Toggle } from "../components/ui";

export default function SettingsSenders() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState<"gmail" | "outlook">(
    params.get("connected") === "outlook" || params.get("error") === "outlook" ? "outlook" : "gmail",
  );
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => get<Provider[]>("/api/providers") });
  const senders = useQuery({
    queryKey: ["senders"],
    queryFn: () => get<Sender[]>("/api/senders"),
    refetchInterval: 10000,
  });
  const outlookEnabled = providers.data?.find((p) => p.name === "outlook")?.enabled ?? false;

  return (
    <div>
      <h1 className="mb-3 text-xl font-semibold">Senders</h1>
      {params.get("connected") === "outlook" && <Notice>Outlook account connected.</Notice>}
      {params.get("error") === "outlook" && (
        <ErrorBanner error={`Outlook sign-in failed: ${params.get("detail") ?? "unknown error"}`} />
      )}
      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {(["gmail", "outlook"] as const).map((t) => (
          <button
            type="button"
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize ${tab === t ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}
          >
            {t}
          </button>
        ))}
      </div>
      <ErrorBanner error={senders.error} />
      {tab === "gmail" ? (
        <GmailTab senders={(senders.data ?? []).filter((s) => s.provider === "gmail")} />
      ) : (
        <OutlookTab enabled={outlookEnabled} senders={(senders.data ?? []).filter((s) => s.provider === "outlook")} />
      )}
    </div>
  );
}

function SenderRow({ s }: { s: Sender }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["senders"] });
  const [cap, setCap] = useState(String(s.daily_cap));
  const [edit, setEdit] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const upd = useMutation({ mutationFn: (b: object) => patch(`/api/senders/${s.id}`, b), onSuccess: refresh });
  const check = useMutation({
    mutationFn: () => post(`/api/senders/${s.id}/check`),
    onSuccess: (r: any) => {
      setMsg({ ok: r.ok, text: r.detail });
      refresh();
    },
    onError: (e) => setMsg({ ok: false, text: errorText(e) }),
  });
  const remove = useMutation({ mutationFn: () => del(`/api/senders/${s.id}`), onSuccess: refresh });
  const reconnect = useMutation({
    mutationFn: () => get<{ url: string }>(`/api/oauth/outlook/start?sender_id=${s.id}`),
    onSuccess: (r) => {
      window.location.href = r.url;
    },
  });

  return (
    <div className="card mb-3">
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-[220px] flex-1">
          <div className="font-medium">{s.address}</div>
          <div className="text-xs text-slate-500">{s.display_name ?? "no display name"}</div>
        </div>
        <StatusChip status={s.quota.state === "exhausted" ? "exhausted" : s.status} />
        <QuotaBar q={s.quota} label="Last 24 h" />
        <Toggle
          checked={s.status !== "idle"}
          label="Active"
          onChange={(v) => upd.mutate({ status: v ? "active" : "idle" })}
        />
        <div className="flex items-center gap-1">
          <span className="text-xs text-slate-500">Cap</span>
          <input
            className="input w-20"
            type="number"
            min={1}
            value={cap}
            onChange={(e) => setCap(e.target.value)}
            onBlur={() => Number(cap) !== s.daily_cap && upd.mutate({ daily_cap: Number(cap) })}
          />
        </div>
        <div className="flex gap-2">
          {s.provider === "gmail" && (
            <button type="button" className="btn" onClick={() => setEdit(true)}>
              <Pencil size={14} /> Edit
            </button>
          )}
          <button type="button" className="btn" onClick={() => check.mutate()} disabled={check.isPending}>
            <CheckCircle2 size={14} /> Check login
          </button>
          {s.provider === "outlook" && s.status === "auth_failed" && (
            <button type="button" className="btn btn-primary" onClick={() => reconnect.mutate()}>
              <Plug size={14} /> Reconnect
            </button>
          )}
          <ConfirmButton
            className="btn"
            message={`Delete ${s.address}? Runs using it will no longer be able to send from it.`}
            onConfirm={() => remove.mutate()}
          >
            <Trash2 size={14} /> Delete
          </ConfirmButton>
        </div>
      </div>
      {s.last_error && <div className="mt-2 text-xs text-red-700">Last error: {s.last_error}</div>}
      {msg && <div className={`mt-2 text-xs ${msg.ok ? "text-green-700" : "text-red-700"}`}>{msg.text}</div>}
      <ErrorBanner error={upd.error || remove.error || reconnect.error} />
      {edit && (
        <EditGmail
          s={s}
          onClose={() => setEdit(false)}
          onSaved={() => {
            setEdit(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function EditGmail({ s, onClose, onSaved }: { s: Sender; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(s.display_name ?? "");
  const [pw, setPw] = useState("");
  const save = useMutation({
    mutationFn: () => patch(`/api/senders/${s.id}`, { display_name: name, ...(pw ? { app_password: pw } : {}) }),
    onSuccess: onSaved,
  });
  return (
    <Modal title={`Edit ${s.address}`} onClose={onClose}>
      <ErrorBanner error={save.error} />
      <label className="label">Display name</label>
      <input className="input mb-3" value={name} onChange={(e) => setName(e.target.value)} />
      <label className="label">New app password (leave empty to keep the current one)</label>
      <input
        className="input mb-1"
        type="password"
        autoComplete="off"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
      />
      <p className="mb-3 text-xs text-slate-500">
        Secrets are write-only: the current password is never shown. After changing it, click Check login.
      </p>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn" onClick={onClose}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={() => save.mutate()}>
          Save
        </button>
      </div>
    </Modal>
  );
}

function GmailTab({ senders }: { senders: Sender[] }) {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => get<AppConfig>("/api/config") });
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [cap, setCap] = useState("");
  const add = useMutation({
    mutationFn: () =>
      post("/api/senders/gmail", {
        address,
        display_name: name || null,
        app_password: pw,
        daily_cap: cap ? Number(cap) : null,
      }),
    onSuccess: () => {
      setAddress("");
      setName("");
      setPw("");
      setCap("");
      qc.invalidateQueries({ queryKey: ["senders"] });
    },
  });
  return (
    <div>
      {senders.length === 0 ? (
        <div className="mb-4">
          <Empty
            title="No Gmail accounts yet"
            hint="Add one below. You need a Google app password (2-Step Verification must be on)."
          />
        </div>
      ) : (
        senders.map((s) => <SenderRow key={s.id} s={s} />)
      )}
      <div className="card">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-semibold">Add Gmail account</h2>
          <a
            className="inline-flex items-center gap-1 text-sm text-indigo-700 hover:underline"
            href="/docs-static/providers/gmail.md"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={14} /> How to create an app password
          </a>
        </div>
        <ErrorBanner error={add.error} />
        <div className="grid gap-3 md:grid-cols-4">
          <div>
            <label className="label">Gmail address</label>
            <input
              className="input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="you@gmail.com"
            />
          </div>
          <div>
            <label className="label">Display name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your Name" />
          </div>
          <div>
            <label className="label">App password (16 characters)</label>
            <input
              className="input"
              type="password"
              autoComplete="off"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Daily cap</label>
            <input
              className="input"
              type="number"
              min={1}
              value={cap}
              onChange={(e) => setCap(e.target.value)}
              placeholder={String(cfg.data?.defaults.gmail_daily_cap ?? 100)}
            />
          </div>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Max {cfg.data?.limits.max_gmail_daily_cap ?? 400}/day. Gmail allows about 500 per rolling 24 h for personal
          accounts; a lower cap avoids spam flags. After adding, click “Check login”.
        </p>
        <button
          type="button"
          className="btn btn-primary mt-3"
          disabled={!address || !pw || add.isPending}
          onClick={() => add.mutate()}
        >
          Add
        </button>
      </div>
    </div>
  );
}

function OutlookTab({ enabled, senders }: { enabled: boolean; senders: Sender[] }) {
  const connect = useMutation({
    mutationFn: () => get<{ url: string }>("/api/oauth/outlook/start"),
    onSuccess: (r) => {
      window.location.href = r.url;
    },
  });
  if (!enabled) {
    return (
      <div className="card">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="font-semibold">Outlook is not activated</h2>
          <StatusChip status="idle" />
        </div>
        <p className="mb-2 text-sm text-slate-600">
          Outlook sends through Microsoft Graph with OAuth2, so you register your own free app first (Gmail needs none
          of this):
        </p>
        <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-slate-700">
          <li>Create an app registration in the Azure portal (personal Microsoft accounts allowed, public client).</li>
          <li>Add the redirect URI shown in the guide and allow public client flows.</li>
          <li>
            Add delegated permissions <code>Mail.Send</code>, <code>User.Read</code>, <code>offline_access</code>.
          </li>
          <li>
            Put the Application (client) ID in <code>.env</code> as <code>OUTLOOK_CLIENT_ID</code> and run{" "}
            <code>docker compose up -d</code>.
          </li>
        </ol>
        <a className="btn" href="/docs-static/providers/outlook.md" target="_blank" rel="noreferrer">
          <ExternalLink size={14} /> Open the Outlook setup guide
        </a>
      </div>
    );
  }
  return (
    <div>
      <ErrorBanner error={connect.error} />
      {senders.length === 0 ? (
        <div className="mb-4">
          <Empty title="No Outlook accounts yet" hint="Connect one with the button below." />
        </div>
      ) : (
        senders.map((s) => <SenderRow key={s.id} s={s} />)
      )}
      <div className="flex items-center gap-3">
        <button type="button" className="btn btn-primary" onClick={() => connect.mutate()} disabled={connect.isPending}>
          <Plug size={14} /> Connect Outlook account
        </button>
        <a
          className="inline-flex items-center gap-1 text-sm text-indigo-700 hover:underline"
          href="/docs-static/providers/outlook.md"
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={14} /> Setup guide
        </a>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Personal-account daily limits are not documented; the default cap is conservative and editable per account.
      </p>
    </div>
  );
}
