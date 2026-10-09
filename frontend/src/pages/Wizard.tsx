import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ExternalLink, FileText, GripVertical, Upload } from "lucide-react";
import { ApiError, errorText, get, patch, post, put, upload } from "../api/client";
import type { AppConfig, GreetingCfg, LlmKey, Run, Sender } from "../api/types";
import { LLM_QUOTA_WARNING, LLM_WARNING } from "../api/types";
import { Empty, ErrorBanner, Notice, Toggle, useDebounced } from "../components/ui";

const STEPS = ["Files", "Columns", "Filters", "Recipients", "Greeting", "Content", "Senders", "Review"];

export default function Wizard() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const run = useQuery({ queryKey: ["run", id], queryFn: () => get<Run>(`/api/runs/${id}`), enabled: !!id });
  const reload = async () => { await qc.invalidateQueries({ queryKey: ["run", id] }); };
  const setRun = (r: Run) => qc.setQueryData(["run", id], r);

  if (!id) return <CreateRun onCreated={(rid) => nav(`/runs/${rid}/edit`, { replace: true })} />;
  if (run.isLoading) return <div className="card">Loading…</div>;
  if (run.error || !run.data) return <ErrorBanner error={run.error ?? "Run not found"} />;
  const r = run.data;
  if (r.status !== "draft") {
    return (
      <div className="card">
        <h1 className="mb-2 text-lg font-semibold">{r.name}</h1>
        <Notice tone="warn">This run was already prepared ({r.status.replace(/_/g, " ")}). The wizard only edits drafts.</Notice>
        <div className="flex gap-2">
          <Link className="btn btn-primary" to={`/runs/${r.id}`}>Open the run</Link>
        </div>
      </div>
    );
  }
  const common = { run: r, reload, setRun, next: () => setStep((s) => Math.min(STEPS.length - 1, s + 1)), back: () => setStep((s) => Math.max(0, s - 1)) };

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{r.name} <span className="text-sm font-normal text-slate-500">(draft, saved automatically)</span></h1>
        <Link className="btn" to="/">Save and close</Link>
      </div>
      <ol className="mb-4 flex flex-wrap gap-1">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button onClick={() => setStep(i)} className={`rounded-full px-3 py-1 text-xs font-medium ${i === step ? "bg-indigo-600 text-white" : "bg-slate-200 text-slate-700 hover:bg-slate-300"}`}>{i + 1}. {s}</button>
          </li>
        ))}
      </ol>
      <div className="card">
        {step === 0 && <StepFiles {...common} />}
        {step === 1 && <StepColumns {...common} />}
        {step === 2 && <StepFilters {...common} />}
        {step === 3 && <StepRecipients {...common} />}
        {step === 4 && <StepGreeting {...common} />}
        {step === 5 && <StepContent {...common} />}
        {step === 6 && <StepSenders {...common} />}
        {step === 7 && <StepReview {...common} go={setStep} />}
      </div>
    </div>
  );
}

interface StepProps { run: Run; reload: () => Promise<void>; setRun: (r: Run) => void; next: () => void; back: () => void }

function CreateRun({ onCreated }: { onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true); setErr(null);
    try { const r = await post<Run>("/api/runs", { name }); onCreated(r.id); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="card max-w-lg">
      <h1 className="mb-3 text-xl font-semibold">New run</h1>
      <ErrorBanner error={err} />
      <label className="label">Run name</label>
      <input className="input mb-3" autoFocus value={name} placeholder="e.g. Summer internships – Tunis" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && name.trim() && create()} />
      <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={create}>Create draft</button>
    </div>
  );
}

function Nav({ back, next, onNext, nextLabel = "Next", disabled, extra }: { back?: () => void; next?: () => void; onNext?: () => Promise<void>; nextLabel?: string; disabled?: boolean; extra?: ReactNode }) {
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="mt-5 border-t border-slate-100 pt-3">
      <ErrorBanner error={err} />
      <div className="flex items-center justify-between">
        <div>{back && <button className="btn" onClick={back}>Back</button>}</div>
        <div className="flex items-center gap-2">
          {extra}
          {next && (
            <button className="btn btn-primary" disabled={disabled || busy} onClick={async () => {
              setBusy(true); setErr(null);
              try { if (onNext) await onNext(); next(); } catch (e) { setErr(e); } finally { setBusy(false); }
            }}>{nextLabel}</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ 1. files
function StepFiles({ run, reload, setRun, next }: StepProps) {
  const [name, setName] = useState(run.name);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [sheets, setSheets] = useState<string[]>(run.sheets ?? []);
  const [encoding, setEncoding] = useState("");
  const [delimiter, setDelimiter] = useState("");
  const sf = run.source_file;
  const run_ = async <T,>(fn: () => Promise<T>) => { setBusy(true); setErr(null); try { return await fn(); } catch (e) { setErr(e); } finally { setBusy(false); } };

  const onSource = (f: File | undefined) => f && run_(async () => {
    const r = await upload<Run>(`/api/runs/${run.id}/source`, f);
    setSheets(r.sheets ?? []);
    setRun(r);
  });
  const onCv = (f: File | undefined) => f && run_(async () => { setRun(await upload<Run>(`/api/runs/${run.id}/cv`, f)); });
  const reparse = (body: object) => run_(async () => {
    const r = await put<Run>(`/api/runs/${run.id}/source/options`, body);
    setSheets(r.sheets ?? sheets);
    setRun(r);
  });
  const saveName = async () => { if (name.trim() && name !== run.name) { setRun(await patch<Run>(`/api/runs/${run.id}`, { name })); } };
  const cols = run.columns;
  const preview = run.preview_rows ?? [];

  return (
    <div>
      <ErrorBanner error={err} />
      <div className="grid gap-4 md:grid-cols-3">
        <div><label className="label">Run name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => saveName().catch(setErr)} /></div>
        <div>
          <label className="label">Contacts file (.csv or .xlsx)</label>
          <label className="btn cursor-pointer"><Upload size={14} /> {sf ? "Replace file" : "Choose file"}<input type="file" className="hidden" accept=".csv,.xlsx" onChange={(e) => onSource(e.target.files?.[0])} /></label>
          {sf && <div className="mt-1 text-xs text-slate-600"><FileText size={12} className="mr-1 inline" />{sf.original_name} · {run.row_count} rows</div>}
        </div>
        <div>
          <label className="label">CV (PDF, max 3 MB)</label>
          <label className="btn cursor-pointer"><Upload size={14} /> {run.cv_file ? "Replace CV" : "Choose PDF"}<input type="file" className="hidden" accept="application/pdf,.pdf" onChange={(e) => onCv(e.target.files?.[0])} /></label>
          {run.cv_file && <div className="mt-1 text-xs text-slate-600"><FileText size={12} className="mr-1 inline" />{run.cv_file.original_name} · {(run.cv_file.size / 1024).toFixed(0)} KB</div>}
        </div>
      </div>
      {busy && <div className="mt-2 text-sm text-slate-500">Working…</div>}
      {sf && (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap items-end gap-3 text-sm">
            <div className="text-slate-600">Detected: {sf.format === "csv" ? <>encoding <b>{sf.encoding}</b>, delimiter <b>{sf.delimiter === "\t" ? "tab" : sf.delimiter}</b></> : <>sheet <b>{sf.sheet}</b></>}</div>
            {sf.format === "csv" ? (
              <>
                <div><label className="label">Delimiter</label>
                  <select className="input" value={delimiter} onChange={(e) => { setDelimiter(e.target.value); reparse({ delimiter: e.target.value || null, encoding: encoding || null }); }}>
                    <option value="">auto</option><option value=",">comma ,</option><option value=";">semicolon ;</option><option value={"\t"}>tab</option><option value="|">pipe |</option>
                  </select></div>
                <div><label className="label">Encoding</label>
                  <select className="input" value={encoding} onChange={(e) => { setEncoding(e.target.value); reparse({ encoding: e.target.value || null, delimiter: delimiter || null }); }}>
                    <option value="">auto</option><option value="utf-8-sig">UTF-8</option><option value="latin-1">Latin-1</option><option value="cp1252">Windows-1252</option>
                  </select></div>
              </>
            ) : (
              sheets.length > 1 && <div><label className="label">Sheet</label>
                <select className="input" value={sf.sheet ?? ""} onChange={(e) => reparse({ sheet: e.target.value })}>{sheets.map((s) => <option key={s}>{s}</option>)}</select></div>
            )}
          </div>
          {preview.length > 0 && (
            <div className="overflow-x-auto rounded-sm border border-slate-200">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50"><tr>{cols.map((c) => <th key={c} className="th whitespace-nowrap">{c}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-100">{preview.slice(0, 20).map((row, i) => <tr key={i}>{cols.map((c) => <td key={c} className="px-3 py-1 whitespace-nowrap">{row[c]}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
          <div className="mt-1 text-xs text-slate-500">First {Math.min(20, preview.length)} rows shown.</div>
        </div>
      )}
      <Nav next={next} disabled={!sf || !run.cv_file} onNext={async () => { await saveName(); await reload(); }} />
    </div>
  );
}

// ------------------------------------------------------------------ 2. columns
function StepColumns({ run, setRun, next, back }: StepProps) {
  const [chosen, setChosen] = useState<string[]>(run.filters.map((f) => f.column));
  const samples = useMemo(() => {
    const s: Record<string, string[]> = {};
    for (const c of run.columns) s[c] = (run.preview_rows ?? []).map((r) => r[c]).filter(Boolean).slice(0, 3);
    return s;
  }, [run.columns, run.preview_rows]);
  const toggle = (c: string) => setChosen((cur) => (cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c]));
  const save = async () => {
    const existing = new Map(run.filters.map((f) => [f.column, f.values]));
    const filters = chosen.map((c) => ({ column: c, values: existing.get(c) ?? [] }));
    setRun(await patch<Run>(`/api/runs/${run.id}`, { filters }));
  };
  return (
    <div>
      <p className="mb-3 text-sm text-slate-600">Pick the columns you want to filter on (optional). You choose the values in the next step. No filter columns means every row is used.</p>
      {run.columns.length === 0 ? <Empty title="No columns yet" hint="Upload a contacts file in step 1." /> : (
        <div className="grid gap-2 md:grid-cols-2">
          {run.columns.map((c) => (
            <label key={c} className={`flex cursor-pointer items-start gap-2 rounded-sm border p-2 text-sm ${chosen.includes(c) ? "border-indigo-400 bg-indigo-50" : "border-slate-200"}`}>
              <input type="checkbox" className="mt-1" checked={chosen.includes(c)} onChange={() => toggle(c)} />
              <span><span className="font-medium">{c}</span><span className="block text-xs text-slate-500">{samples[c]?.join(" · ") || "(no sample)"}</span></span>
            </label>
          ))}
        </div>
      )}
      <Nav back={back} next={next} onNext={save} />
    </div>
  );
}

// ------------------------------------------------------------------ 3. filters
function ValueFilter({ run, column, selected, onChange }: { run: Run; column: string; selected: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const vals = useQuery({
    queryKey: ["values", run.id, column, dq],
    queryFn: () => get<{ total: number; values: { value: string; count: number }[]; all_values: string[] | null }>(`/api/runs/${run.id}/columns/${encodeURIComponent(column)}/values?limit=200&q=${encodeURIComponent(dq)}`),
  });
  const sel = new Set(selected);
  const label = (v: string) => (v === "__EMPTY__" ? "(empty)" : v);
  const toggle = (v: string) => onChange(sel.has(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  const all = vals.data?.all_values ?? vals.data?.values.map((v) => v.value) ?? [];
  return (
    <div className="rounded-sm border border-slate-200 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="font-medium">{column}</div>
        <input className="input max-w-xs" placeholder="Search values…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn" onClick={() => onChange(Array.from(new Set([...selected, ...all])))}>Select all matches ({vals.data?.total ?? 0})</button>
        <button className="btn" onClick={() => onChange([])}>Clear</button>
        <span className="text-xs text-slate-500">{selected.length} selected</span>
      </div>
      <ErrorBanner error={vals.error} />
      <div className="grid max-h-64 gap-1 overflow-auto sm:grid-cols-2 lg:grid-cols-3">
        {vals.data?.values.map((v) => (
          <label key={v.value} className="flex cursor-pointer items-center gap-2 rounded-sm px-1 text-sm hover:bg-slate-50">
            <input type="checkbox" checked={sel.has(v.value)} onChange={() => toggle(v.value)} />
            <span className="truncate">{label(v.value)}</span><span className="ml-auto text-xs text-slate-400">{v.count}</span>
          </label>
        ))}
      </div>
      {vals.data && vals.data.total > vals.data.values.length && <div className="mt-1 text-xs text-slate-500">Showing the first {vals.data.values.length} of {vals.data.total}. Use the search box to narrow down.</div>}
    </div>
  );
}

function StepFilters({ run, setRun, next, back }: StepProps) {
  const [filters, setFilters] = useState(run.filters);
  const dfilters = useDebounced(filters, 400);
  const [count, setCount] = useState<{ matching_rows: number; with_valid_email: number } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    post(`/api/runs/${run.id}/filters/preview`, { filters: dfilters, email_column: run.recipient.email_column }).then(setCount).catch(setErr);
  }, [dfilters, run.id]);
  const save = async () => { setRun(await patch<Run>(`/api/runs/${run.id}`, { filters })); };
  return (
    <div>
      <ErrorBanner error={err} />
      <div className="mb-3 rounded-sm bg-slate-50 p-3 text-sm">
        Matching rows: <b>{count?.matching_rows ?? "…"}</b> of {run.row_count}
        {run.recipient.email_column && count && <> · with a valid email: <b>{count.with_valid_email}</b></>}
        <div className="text-xs text-slate-500">A row matches when, for every filter column, its value is one of the selected values. Columns with nothing selected are ignored.</div>
      </div>
      {filters.length === 0 ? <Empty title="No filter columns chosen" hint="Go back to step 2 to choose some, or continue to use every row." /> : (
        <div className="space-y-3">{filters.map((f, i) => <ValueFilter key={f.column} run={run} column={f.column} selected={f.values} onChange={(v) => setFilters((cur) => cur.map((x, j) => (j === i ? { ...x, values: v } : x)))} />)}</div>
      )}
      <Nav back={back} next={next} onNext={save} />
    </div>
  );
}

// ------------------------------------------------------------------ 4. recipients
function MultiSelect({ label, options, value, onChange, hint }: { label: string; options: string[]; value: string[]; onChange: (v: string[]) => void; hint?: string }) {
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex max-h-40 flex-wrap gap-1 overflow-auto rounded-sm border border-slate-200 p-2">
        {options.map((o) => (
          <button key={o} type="button" onClick={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
            className={`rounded-full px-2 py-0.5 text-xs ${value.includes(o) ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>{o}</button>
        ))}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function StepRecipients({ run, setRun, next, back }: StepProps) {
  const [email, setEmail] = useState(run.recipient.email_column ?? "");
  const [human, setHuman] = useState(run.recipient.human_name_columns);
  const [company, setCompany] = useState(run.recipient.company_name_columns);
  const save = async () => {
    setRun(await patch<Run>(`/api/runs/${run.id}`, { recipient: { email_column: email || null, human_name_columns: human, company_name_columns: company } }));
  };
  return (
    <div className="space-y-4">
      <div className="max-w-sm"><label className="label">Email column</label>
        <select className="input" value={email} onChange={(e) => setEmail(e.target.value)}><option value="">Choose…</option>{run.columns.map((c) => <option key={c}>{c}</option>)}</select>
        <div className="mt-1 text-xs text-slate-500">If a cell holds several addresses, the first valid one is used. Rows without a valid address are listed as “no contact” and never sent.</div></div>
      <MultiSelect label="Person-name column(s)" options={run.columns} value={human} onChange={setHuman} hint="Joined with a space, e.g. First name + Last name." />
      <MultiSelect label="Company-name column(s)" options={run.columns} value={company} onChange={setCompany} hint="The first non-empty value is used. Leave empty to derive it from the email domain." />
      <Nav back={back} next={next} disabled={!email} onNext={save} />
    </div>
  );
}

// ------------------------------------------------------------------ 5. greeting
export function previewGreeting(g: GreetingCfg, kind: "human" | "company" | "fallback"): string {
  const hon = g.use_honorific ? "Ms" : "";
  const tpl = kind === "human" ? g.human_template : kind === "company" ? g.company_template : g.fallback_template;
  return tpl.replace("{salutation}", g.salutation).replace("{honorific}", hon).replace("{name}", "Jane Doe").replace("{company}", "Acme")
    .replace(/\s+/g, " ").replace(/\s+([,.;:!])/g, "$1").trim();
}

function StepGreeting({ run, setRun, next, back }: StepProps) {
  const keys = useQuery({ queryKey: ["llm-keys"], queryFn: () => get<LlmKey[]>("/api/llm-keys") });
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => get<AppConfig>("/api/config") });
  const [mode, setMode] = useState(run.mode);
  const [rule, setRule] = useState(run.rules.kind);
  const [keyIds, setKeyIds] = useState(run.llm_key_ids);
  const [g, setG] = useState<GreetingCfg>(run.greeting);
  const set = (p: Partial<GreetingCfg>) => setG((x) => ({ ...x, ...p }));
  const save = async () => {
    setRun(await patch<Run>(`/api/runs/${run.id}`, { mode, rules: { kind: rule }, llm_key_ids: keyIds, greeting: g }));
  };
  const noKeys = mode === "llm" && !cfg.data?.llm_fake && keyIds.length === 0;
  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        {(["rules", "llm"] as const).map((m) => (
          <label key={m} className={`flex-1 cursor-pointer rounded-sm border p-3 text-sm ${mode === m ? "border-indigo-500 bg-indigo-50" : "border-slate-200"}`}>
            <input type="radio" className="mr-2" checked={mode === m} onChange={() => setMode(m)} />
            <b>{m === "rules" ? "Rules" : "LLM (Gemini)"}</b>
            <div className="mt-1 text-xs text-slate-600">{m === "rules" ? "Fixed rules, no external service. Nothing leaves your machine." : "Gemini decides person vs company and cleans names (never writes the email body)."}</div>
          </label>
        ))}
      </div>
      {mode === "rules" ? (
        <div className="space-y-1 text-sm">
          <label className="flex items-center gap-2"><input type="radio" checked={rule === "always_company"} onChange={() => setRule("always_company")} /> Always address the company team</label>
          <label className="flex items-center gap-2"><input type="radio" checked={rule === "human_if_available"} onChange={() => setRule("human_if_available")} /> Use the person’s name when a person-name column has a value, otherwise the company</label>
        </div>
      ) : (
        <div>
          <Notice tone="warn"><div>{LLM_WARNING}</div><div className="mt-1 text-xs">{LLM_QUOTA_WARNING}</div></Notice>
          {cfg.data?.llm_fake && <Notice>Fake LLM mode is on (development): no keys are needed.</Notice>}
          <label className="label">Gemini keys (fill-first, in this order)</label>
          {keys.data?.length ? keys.data.map((k) => (
            <label key={k.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={keyIds.includes(k.id)} onChange={() => setKeyIds((c) => (c.includes(k.id) ? c.filter((x) => x !== k.id) : [...c, k.id]))} />{k.label} <span className="text-xs text-slate-500">{k.quota.used}/{k.quota.cap} today · {k.quota.state}</span></label>
          )) : <div className="text-sm text-slate-500">No keys yet. <Link className="text-indigo-700 underline" to="/settings/llm">Add a Gemini key</Link> <ExternalLink size={12} className="inline" /></div>}
          <div className="mt-2"><Toggle checked={g.use_honorific} onChange={(v) => set({ use_honorific: v })} label="Use honorifics (Mr / Ms) when the first name is unambiguous" /></div>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <div><label className="label">Salutation</label><input className="input" value={g.salutation} onChange={(e) => set({ salutation: e.target.value })} /></div>
        <div className="flex items-end">{mode === "rules" && <Toggle checked={g.use_honorific} onChange={(v) => set({ use_honorific: v })} label="Use honorific if available" />}</div>
        <div><label className="label">Company template</label><input className="input" value={g.company_template} onChange={(e) => set({ company_template: e.target.value })} /><div className="mt-1 text-xs text-slate-500">Example: <i>{previewGreeting(g, "company")}</i></div></div>
        <div><label className="label">Person template</label><input className="input" value={g.human_template} onChange={(e) => set({ human_template: e.target.value })} /><div className="mt-1 text-xs text-slate-500">Example: <i>{previewGreeting(g, "human")}</i></div></div>
        <div><label className="label">Fallback template</label><input className="input" value={g.fallback_template} onChange={(e) => set({ fallback_template: e.target.value })} /><div className="mt-1 text-xs text-slate-500">Example: <i>{previewGreeting(g, "fallback")}</i></div></div>
      </div>
      <div className="text-xs text-slate-500">Placeholders: {"{salutation} {honorific} {name} {company}"}</div>
      <Nav back={back} next={next} onNext={save} disabled={noKeys} extra={noKeys ? <span className="text-xs text-amber-700">Pick at least one key for LLM mode</span> : null} />
    </div>
  );
}

// ------------------------------------------------------------------ 6. content
function StepContent({ run, setRun, next, back }: StepProps) {
  const [subject, setSubject] = useState(run.template.subject);
  const [body, setBody] = useState(run.template.body);
  const [replyTo, setReplyTo] = useState(run.reply_to ?? "");
  const subjRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [last, setLast] = useState<"subject" | "body">("body");
  const insert = (token: string) => {
    if (last === "subject" && subjRef.current) {
      const el = subjRef.current; const s = el.selectionStart ?? subject.length; const e = el.selectionEnd ?? s;
      setSubject(subject.slice(0, s) + token + subject.slice(e));
    } else if (bodyRef.current) {
      const el = bodyRef.current; const s = el.selectionStart ?? body.length; const e = el.selectionEnd ?? s;
      setBody(body.slice(0, s) + token + body.slice(e));
    }
  };
  const save = async () => { setRun(await patch<Run>(`/api/runs/${run.id}`, { template: { subject, body }, reply_to: replyTo.trim() || null })); };
  const tokens = ["{{greeting}}", "{{name}}", "{{company}}", "{{email}}", ...run.columns.map((c) => `{{col:${c}}}`)];
  return (
    <div>
      <div className="mb-3">
        <div className="label">Insert placeholder (into the field you last clicked)</div>
        <div className="flex max-h-28 flex-wrap gap-1 overflow-auto">{tokens.map((t) => <button key={t} type="button" className="rounded-sm bg-slate-100 px-2 py-0.5 font-mono text-xs hover:bg-indigo-100" onClick={() => insert(t)}>{t}</button>)}</div>
      </div>
      <label className="label">Subject</label>
      <input ref={subjRef} className="input mb-3" value={subject} onFocus={() => setLast("subject")} onChange={(e) => setSubject(e.target.value)} />
      <label className="label">Body (plain text)</label>
      <textarea ref={bodyRef} className="input mb-3 h-64 font-mono" value={body} onFocus={() => setLast("body")} onChange={(e) => setBody(e.target.value)} />
      <div className="max-w-sm"><label className="label">Reply-to (optional)</label><input className="input" value={replyTo} onChange={(e) => setReplyTo(e.target.value)} placeholder="Defaults to the sender address" /></div>
      <p className="mt-2 text-xs text-slate-500">Your CV is attached automatically. Empty values become empty text and add a warning on that email.</p>
      <Nav back={back} next={next} onNext={save} disabled={!subject.trim() || !body.trim()} />
    </div>
  );
}

// ------------------------------------------------------------------ 7. senders
function StepSenders({ run, setRun, next, back }: StepProps) {
  const senders = useQuery({ queryKey: ["senders"], queryFn: () => get<Sender[]>("/api/senders") });
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => get<AppConfig>("/api/config") });
  const [ids, setIds] = useState<string[]>(run.sender_ids);
  const [approval, setApproval] = useState(run.approval);
  const [dmin, setDmin] = useState(String(run.delay_min_s));
  const [dmax, setDmax] = useState(String(run.delay_max_s));
  const [drag, setDrag] = useState<number | null>(null);
  const byId = new Map((senders.data ?? []).map((s) => [s.id, s]));
  const available = (senders.data ?? []).filter((s) => !ids.includes(s.id));
  const move = (i: number, d: number) => setIds((cur) => { const a = [...cur]; const j = i + d; if (j < 0 || j >= a.length) return a; [a[i], a[j]] = [a[j], a[i]]; return a; });
  const save = async () => { setRun(await patch<Run>(`/api/runs/${run.id}`, { sender_ids: ids, approval, delay_min_s: Number(dmin), delay_max_s: Number(dmax) })); };
  return (
    <div className="space-y-4">
      <div>
        <div className="label">Chosen senders (the first available one is used until it is exhausted, then the next)</div>
        {ids.length === 0 && <div className="text-sm text-slate-500">None chosen yet.</div>}
        {ids.map((id, i) => {
          const s = byId.get(id);
          return (
            <div key={id} draggable onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()}
              onDrop={() => { if (drag === null || drag === i) return; setIds((cur) => { const a = [...cur]; const [m] = a.splice(drag, 1); a.splice(i, 0, m); return a; }); setDrag(null); }}
              className="mb-1 flex items-center gap-2 rounded-sm border border-slate-200 bg-white px-2 py-1.5 text-sm">
              <GripVertical size={14} className="cursor-grab text-slate-400" />
              <span className="w-5 text-slate-400">{i + 1}.</span>
              <span className="flex-1">{s?.address ?? "(deleted sender)"} <span className="text-xs text-slate-400">{s?.provider}</span></span>
              {s && <span className="text-xs text-slate-500">{s.quota.used}/{s.quota.cap} · {s.quota.state}</span>}
              <button className="btn px-1.5 py-0.5" onClick={() => move(i, -1)}><ArrowUp size={12} /></button>
              <button className="btn px-1.5 py-0.5" onClick={() => move(i, 1)}><ArrowDown size={12} /></button>
              <button className="btn px-1.5 py-0.5" onClick={() => setIds((c) => c.filter((x) => x !== id))}>Remove</button>
            </div>
          );
        })}
      </div>
      <div>
        <div className="label">Add a sender</div>
        <div className="flex flex-wrap gap-2">
          {available.map((s) => <button key={s.id} className="btn" onClick={() => setIds((c) => [...c, s.id])}>+ {s.address}</button>)}
          <Link className="btn" to="/settings/senders">Add Gmail account <ExternalLink size={12} /></Link>
          {cfg.data?.providers.outlook ? <Link className="btn" to="/settings/senders">Connect Outlook</Link> : <span className="self-center text-xs text-slate-500">Outlook is not activated (see Senders → Outlook).</span>}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <div><label className="label">Min delay between emails (s)</label><input className="input" type="number" min={0} value={dmin} onChange={(e) => setDmin(e.target.value)} /></div>
        <div><label className="label">Max delay (s)</label><input className="input" type="number" min={0} value={dmax} onChange={(e) => setDmax(e.target.value)} /></div>
      </div>
      <div>
        <div className="label">Approval</div>
        <label className="mr-4 text-sm"><input type="radio" className="mr-1" checked={approval === "manual"} onChange={() => setApproval("manual")} />Manual: I approve each email in the send window</label>
        <label className="text-sm"><input type="radio" className="mr-1" checked={approval === "auto"} onChange={() => setApproval("auto")} />Automatic: send everything with delays</label>
      </div>
      <Nav back={back} next={next} onNext={save} disabled={ids.length === 0 || Number(dmin) > Number(dmax)} />
    </div>
  );
}

// ------------------------------------------------------------------ 8. review
function StepReview({ run, back, go, reload }: StepProps & { go: (i: number) => void }) {
  const nav = useNavigate();
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const prepare = async () => {
    setBusy(true); setErr(null); setFields({});
    try {
      await post(`/api/runs/${run.id}/prepare`);
      await reload();
      nav(`/runs/${run.id}`);
    } catch (e) {
      setErr(e);
      if (e instanceof ApiError && e.body?.fields) setFields(e.body.fields);
    } finally { setBusy(false); }
  };
  const rows: [string, ReactNode, number][] = [
    ["Contacts file", run.source_file ? `${run.source_file.original_name} (${run.row_count} rows)` : "-", 0],
    ["CV", run.cv_file?.original_name ?? "-", 0],
    ["Filters", run.filters.filter((f) => f.values.length).map((f) => `${f.column}: ${f.values.length} value(s)`).join("; ") || "none (all rows)", 2],
    ["Email column", run.recipient.email_column ?? "-", 3],
    ["Person columns", run.recipient.human_name_columns.join(", ") || "-", 3],
    ["Company columns", run.recipient.company_name_columns.join(", ") || "-", 3],
    ["Greeting", run.mode === "llm" ? `LLM (${run.llm_key_ids.length} key(s))` : `Rules: ${run.rules.kind === "always_company" ? "always company" : "person name if available"}`, 4],
    ["Subject", run.template.subject, 5],
    ["Senders", run.senders_snapshot.map((s) => s.address).join(" → ") || "-", 6],
    ["Approval", run.approval === "manual" ? "Manual" : `Automatic (delay ${run.delay_min_s}–${run.delay_max_s}s)`, 6],
  ];
  return (
    <div>
      <ErrorBanner error={err} />
      {Object.keys(fields).length > 0 && <ul className="mb-3 list-disc pl-5 text-sm text-red-700">{Object.entries(fields).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>}
      <table className="mb-3 w-full text-sm"><tbody>{rows.map(([k, v, s]) => (
        <tr key={k} className="border-b border-slate-100"><td className="w-44 py-1.5 text-slate-500">{k}</td><td className="py-1.5">{v}</td><td className="w-16 text-right"><button className="text-xs text-indigo-700 hover:underline" onClick={() => go(s)}>Edit</button></td></tr>
      ))}</tbody></table>
      <Notice>Preparing builds one email per contact and classifies names. Nothing is sent until you start the run.</Notice>
      <div className="flex items-center justify-between"><button className="btn" onClick={back}>Back</button><button className="btn btn-primary" disabled={busy} onClick={prepare}>{busy ? "Preparing…" : "Prepare"}</button></div>
    </div>
  );
}
