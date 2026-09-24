export type Strategy = "keyword" | "vector" | "hybrid";

export interface SearchPayload {
  ticker: string;
  as_of: string;
  strategy: Strategy;
  top_k: number;
  question: string;
}

export interface CoverageItem {
  ticker: string;
  documents: number;
  chunks: number;
  embedded_chunks: number;
  latest_available_at: string | null;
}

export interface Hit {
  chunk_id: string;
  document_id: string;
  document_type: string;
  section_title: string;
  content: string;
  source_url: string;
  available_at: string;
  vector_score: number;
  keyword_score: number;
}

export interface SearchResponse {
  ticker: string;
  as_of: string;
  strategy: Strategy;
  source: "postgres" | "online_sec";
  persisted: boolean;
  expanded_query: string;
  elapsed_ms: number;
  documents: number;
  future_safe: boolean;
  hits: Hit[];
}

export interface ReportSection {
  title: string;
  content: string;
  kind: "summary" | "metrics" | "risk" | "outlook" | "detail";
}

export interface AgentReport {
  ticker: string;
  as_of: string;
  rating: "BUY" | "HOLD" | "SELL" | "UNKNOWN";
  summary: string;
  sections: ReportSection[];
  raw_markdown: string;
}

export interface AgentResponse {
  ticker: string;
  trade_date: string;
  fundamentals_report: string;
  report: AgentReport;
  total_seconds: number;
  steps: number;
  llm_calls: number;
  tool_node_runs: number;
  tokens_in: number;
  tokens_out: number;
}

export interface IngestionJob {
  job_id: string;
  ticker: string;
  as_of: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: string;
  summary?: Record<string, number | string> | null;
  error_message?: string | null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body as T;
}

export const getCoverage = () => request<{ total_tickers: number; items: CoverageItem[] }>("/api/coverage");

export const searchDocuments = (payload: SearchPayload) =>
  request<SearchResponse>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const runAgent = (payload: SearchPayload) =>
  request<AgentResponse>("/api/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

export const createIngestionJob = (ticker: string, asOf: string) =>
  request<IngestionJob>("/api/ingestion-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, as_of: asOf, limit_per_form: 1 }),
  });

export const getIngestionJob = (id: string) => request<IngestionJob>(`/api/ingestion-jobs/${id}`);
