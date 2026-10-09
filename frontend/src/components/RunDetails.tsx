import type { ReactNode } from "react";
import { Download } from "lucide-react";
import type { Run } from "../api/types";
import { fmt } from "./ui";

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <tr className="border-b border-slate-100 align-top"><td className="w-52 py-2 pr-3 text-sm text-slate-500">{k}</td><td className="py-2 text-sm">{children}</td></tr>;
}

export default function RunDetails({ run }: { run: Run }) {
  const sf = run.source_file;
  return (
    <div className="card">
      <table className="w-full"><tbody>
        <Row k="Created / started / first send">{fmt(run.created_at)} / {fmt(run.started_at)} / {fmt(run.first_send_at)}</Row>
        <Row k="Contacts file">{sf ? <>
          {sf.original_name} ({(sf.size / 1024).toFixed(1)} KB, {sf.format}{sf.delimiter ? `, delimiter "${sf.delimiter === "\t" ? "tab" : sf.delimiter}"` : ""}{sf.encoding ? `, ${sf.encoding}` : ""}{sf.sheet ? `, sheet ${sf.sheet}` : ""})
          <div className="break-all font-mono text-xs text-slate-500">sha256 {sf.sha256}</div>
          <a className="mt-1 inline-flex items-center gap-1 text-indigo-700 hover:underline" href={`/api/runs/${run.id}/files/source`}><Download size={13} /> Download</a>
        </> : "-"}</Row>
        <Row k="CV">{run.cv_file ? <>
          {run.cv_file.original_name} ({(run.cv_file.size / 1024).toFixed(0)} KB)
          <div className="break-all font-mono text-xs text-slate-500">sha256 {run.cv_file.sha256}</div>
          <a className="mt-1 inline-flex items-center gap-1 text-indigo-700 hover:underline" href={`/api/runs/${run.id}/files/cv`}><Download size={13} /> Download</a>
        </> : "-"}</Row>
        <Row k="Rows in file">{run.row_count}</Row>
        <Row k="Columns">{run.columns.join(", ")}</Row>
        <Row k="Filters">{run.filters.filter((f) => f.values.length).length ? run.filters.filter((f) => f.values.length).map((f) => <div key={f.column}><b>{f.column}</b>: {f.values.map((v) => (v === "__EMPTY__" ? "(empty)" : v)).join(", ")}</div>) : "none (all rows)"}</Row>
        <Row k="Recipients">Email: <b>{run.recipient.email_column}</b> · person: {run.recipient.human_name_columns.join(", ") || "-"} · company: {run.recipient.company_name_columns.join(", ") || "-"}</Row>
        <Row k="Greeting mode">{run.mode === "llm" ? "LLM (Gemini)" : `Rules (${run.rules.kind})`}</Row>
        <Row k="Greeting templates"><div>Salutation: {run.greeting.salutation} · honorific: {run.greeting.use_honorific ? "on" : "off"}</div><div className="font-mono text-xs">company: {run.greeting.company_template}</div><div className="font-mono text-xs">person: {run.greeting.human_template}</div><div className="font-mono text-xs">fallback: {run.greeting.fallback_template}</div></Row>
        <Row k="Subject template"><span className="font-mono text-xs">{run.template.subject}</span></Row>
        <Row k="Body template"><pre className="whitespace-pre-wrap font-mono text-xs">{run.template.body}</pre></Row>
        <Row k="Reply-to">{run.reply_to ?? "(sender address)"}</Row>
        <Row k="Senders (priority order)">{run.senders_snapshot.map((s, i) => <div key={s.id}>{i + 1}. {s.address} <span className="text-xs text-slate-400">({s.provider})</span></div>)}</Row>
        <Row k="Gemini keys">{run.mode === "llm" ? `${run.llm_key_ids.length} key(s) selected` : "not used"}</Row>
        <Row k="Sending">approval: {run.approval} · delay {run.delay_min_s}–{run.delay_max_s}s · retries {run.max_retries} · breaker after {run.breaker_threshold} consecutive failures</Row>
      </tbody></table>
      <div className="mt-3"><a className="btn" href={`/api/runs/${run.id}/export.csv`}><Download size={14} /> Export results (CSV)</a></div>
    </div>
  );
}
