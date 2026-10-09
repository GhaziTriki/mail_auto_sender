export type RunStatus =
  | "draft"
  | "preparing"
  | "ready"
  | "running"
  | "paused_user"
  | "paused_quota"
  | "paused_llm"
  | "paused_errors"
  | "completed";

export type ItemStatus =
  | "pending"
  | "sending"
  | "sent"
  | "failed"
  | "no_contact"
  | "needs_review"
  | "skipped_duplicate"
  | "skipped_user"
  | "unknown";

export interface Quota {
  used: number;
  cap: number;
  exhausted: boolean;
  resets_at: string | null;
  state: "active" | "idle" | "auth_failed" | "exhausted" | "deleted";
}

export interface Sender {
  id: string;
  provider: "gmail" | "outlook";
  address: string;
  display_name: string | null;
  daily_cap: number;
  status: "active" | "idle" | "auth_failed";
  last_error: string | null;
  has_secret: boolean;
  quota: Quota;
}

export interface LlmKey {
  id: string;
  label: string;
  daily_cap: number;
  status: "active" | "idle" | "auth_failed";
  last_error: string | null;
  has_secret: boolean;
  quota: Quota;
}

export interface Provider {
  name: "gmail" | "outlook";
  enabled: boolean;
  setup_doc: string;
}

export interface AppConfig {
  limits: {
    max_rows: number;
    max_source_mb: number;
    max_cv_mb: number;
    max_gmail_daily_cap: number;
    max_outlook_daily_cap: number;
  };
  defaults: {
    gmail_daily_cap: number;
    outlook_daily_cap: number;
    llm_daily_cap: number;
    delay_min_s: number;
    delay_max_s: number;
    max_retries: number;
    llm_batch_size: number;
  };
  providers: Record<string, boolean>;
  llm_fake: boolean;
  gemini_model: string;
}

export interface GreetingCfg {
  salutation: string;
  use_honorific: boolean;
  company_template: string;
  human_template: string;
  fallback_template: string;
}

export interface Counts {
  pending: number;
  sending: number;
  sent: number;
  failed: number;
  no_contact: number;
  needs_review: number;
  skipped_duplicate: number;
  skipped_user: number;
  unknown: number;
  total: number;
}

export interface Run {
  id: string;
  name: string;
  status: RunStatus;
  pause_reason: string | null;
  pause_detail: any;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  first_send_at: string | null;
  source_file: {
    original_name: string;
    sha256: string;
    size: number;
    format: "csv" | "xlsx";
    delimiter: string | null;
    encoding: string | null;
    sheet: string | null;
  } | null;
  columns: string[];
  row_count: number;
  cv_file: { original_name: string; sha256: string; size: number } | null;
  filters: { column: string; values: string[] }[];
  recipient: { email_column: string | null; human_name_columns: string[]; company_name_columns: string[] };
  mode: "llm" | "rules";
  rules: { kind: "always_company" | "human_if_available" };
  greeting: GreetingCfg;
  template: { subject: string; body: string };
  reply_to: string | null;
  approval: "manual" | "auto";
  sender_ids: string[];
  senders_snapshot: { id: string; provider: string; address: string }[];
  llm_key_ids: string[];
  delay_min_s: number;
  delay_max_s: number;
  max_retries: number;
  breaker_threshold: number;
  consecutive_failures: number;
  counts: Counts;
  preview_rows?: Record<string, string>[];
  sheets?: string[];
}

export interface Item {
  id: string;
  run_id: string;
  row_index: number;
  row: Record<string, string>;
  email_source_column: string;
  email_raw: string;
  email_norm: string | null;
  contact_line: { column: string; raw: string; email: string | null };
  classified: boolean;
  kind: "human" | "company" | null;
  name: string | null;
  company: string | null;
  honorific: string | null;
  decided_by: "llm" | "rules" | "user" | null;
  greeting_text: string;
  subject: string;
  body: string;
  edited: boolean;
  warnings: string[];
  status: ItemStatus;
  approved: boolean;
  duplicate_reason: string | null;
  attempt_count: number;
  attempts: { at: string; sender_id: string | null; outcome: string; detail: string }[];
  sender_address: string | null;
  sent_at: string | null;
  prior_send?: {
    run_name: string;
    sender_address: string;
    sent_at: string | null;
    subject: string;
    uncertain: boolean;
  } | null;
}

export interface Paged<T> {
  total: number;
  page: number;
  items: T[];
}

export const RUN_ACTIVE: RunStatus[] = [
  "preparing",
  "running",
  "paused_user",
  "paused_quota",
  "paused_llm",
  "paused_errors",
];

export const LLM_WARNING =
  "In LLM mode, contact names and email addresses are sent to Google Gemini. On the free tier, Google may use prompts to improve its products.";
export const LLM_QUOTA_WARNING =
  "~200 requests/day per Google project; keys in the same project share quota; contact data is sent to Gemini; free-tier prompts may be used by Google.";
