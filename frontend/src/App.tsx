import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Database,
  FileSearch,
  Gauge,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import {
  createIngestionJob,
  getCoverage,
  getIngestionJob,
  runAgent,
  searchDocuments,
} from "./api";
import type {
  AgentResponse,
  CoverageItem,
  IngestionJob,
  SearchPayload,
  SearchResponse,
  Strategy,
} from "./api";

const defaultQuestion = "TSLA 当前主要经营风险是什么？结合财报说明管理层对后续经营有什么展望？";

function App() {
  const [ticker, setTicker] = useState("TSLA");
  const [asOf, setAsOf] = useState("2025-03-01");
  const [question, setQuestion] = useState(defaultQuestion);
  const [strategy, setStrategy] = useState<Strategy>("hybrid");
  const [topK, setTopK] = useState(5);
  const [coverage, setCoverage] = useState<CoverageItem[]>([]);
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null);
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [busy, setBusy] = useState<"search" | "agent" | "ingest" | null>(null);
  const [message, setMessage] = useState("准备就绪。先检索证据，再生成 Agent 报告。");
  const [error, setError] = useState("");

  const payload = useMemo<SearchPayload>(() => ({
    ticker: ticker.trim().toUpperCase(),
    as_of: asOf,
    strategy,
    top_k: topK,
    question: question.trim(),
  }), [asOf, question, strategy, ticker, topK]);

  const refreshCoverage = async () => {
    try {
      const result = await getCoverage();
      setCoverage(result.items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "覆盖范围读取失败");
    }
  };

  useEffect(() => { void refreshCoverage(); }, []);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const timer = window.setTimeout(async () => {
      try { setJob(await getIngestionJob(job.job_id)); } catch (cause) {
        setError(cause instanceof Error ? cause.message : "任务状态读取失败");
      }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [job]);

  const doSearch = async () => {
    setBusy("search"); setError(""); setMessage("正在查询 PostgreSQL / pgvector...");
    try {
      const result = await searchDocuments(payload);
      setSearchResult(result);
      setMessage(result.source === "postgres" ? "本地财报检索完成。" : "SEC 在线兜底完成，结果尚未入库。注意延迟可能更高。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "检索失败"); setMessage("检索失败。"); }
    finally { setBusy(null); }
  };

  const doAgent = async () => {
    setBusy("agent"); setError(""); setMessage("基本面 Agent 正在执行工具循环，通常需要 1～2 分钟...");
    try { setAgentResult(await runAgent(payload)); setMessage("基本面 Agent 报告已生成。"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Agent 执行失败"); setMessage("Agent 执行失败。"); }
    finally { setBusy(null); }
  };

  const doIngest = async () => {
    setBusy("ingest"); setError(""); setMessage("正在创建财报增量任务...");
    try { setJob(await createIngestionJob(payload.ticker, payload.as_of)); setMessage("任务已创建，后台会完成下载、切分、入库和向量化。"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "任务创建失败"); }
    finally { setBusy(null); }
  };

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Sparkles size={18} /></div><div><strong>TradeAgent</strong><span>金融研究工作台</span></div></div>
      <div className="system-status"><span className="status-dot" /> FastAPI 服务正常 <a href="/docs" target="_blank" rel="noreferrer">API 文档 <ArrowUpRight size={13} /></a></div>
    </header>

    <main>
      <section className="page-intro"><div><p className="eyebrow">研究任务 / 基本面分析</p><h1>用证据驱动一份投研判断</h1><p className="lead">先从已校验的财报库检索，再让 Agent 组织结论、风险与管理层展望。</p></div><div className="data-badge"><Database size={16} /><span>PostgreSQL + pgvector</span></div></section>

      <section className="workspace-grid">
        <aside className="control-panel panel">
          <div className="panel-heading"><div><p className="eyebrow">任务配置</p><h2>开始一次研究</h2></div><Activity size={18} className="muted-icon" /></div>
          <label>股票代码<input value={ticker} onChange={(event) => setTicker(event.target.value)} placeholder="例如 TSLA" /></label>
          <div className="two-columns"><label>分析日期<input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label><label>返回数量<input type="number" min={1} max={10} value={topK} onChange={(event) => setTopK(Number(event.target.value))} /></label></div>
          <label>检索策略<select value={strategy} onChange={(event) => setStrategy(event.target.value as Strategy)}><option value="hybrid">Hybrid 混合检索</option><option value="vector">向量检索</option><option value="keyword">关键词检索</option></select></label>
          <label>研究问题<textarea value={question} onChange={(event) => setQuestion(event.target.value)} /></label>
          <div className="button-stack"><button className="primary-button" onClick={() => void doSearch()} disabled={busy !== null}><FileSearch size={17} />{busy === "search" ? "检索中..." : "检索财报证据"}</button><button className="dark-button" onClick={() => void doAgent()} disabled={busy !== null}><Sparkles size={17} />{busy === "agent" ? "Agent 执行中..." : "生成基本面报告"}</button><button className="outline-button" onClick={() => void doIngest()} disabled={busy !== null}><UploadCloud size={17} />{busy === "ingest" ? "创建任务..." : "准备 / 更新财报"}</button></div>
          {message && <p className="helper-text">{message}</p>}
          {error && <div className="error-box"><AlertTriangle size={16} />{error}</div>}
        </aside>

        <div className="results-column">
          <Coverage items={coverage} onRefresh={() => void refreshCoverage()} />
          {job && <JobStatus job={job} />}
          {searchResult && <SearchPanel result={searchResult} />}
          {agentResult && <AgentPanel result={agentResult} />}
          {!searchResult && !agentResult && !job && <EmptyState />}
        </div>
      </section>
    </main>
  </div>;
}

function Coverage({ items, onRefresh }: { items: CoverageItem[]; onRefresh: () => void }) {
  return <section className="panel coverage-panel"><div className="panel-heading"><div><p className="eyebrow">知识库状态</p><h2>已接入的股票</h2></div><button className="icon-button" onClick={onRefresh} title="刷新覆盖范围"><RefreshCw size={16} /></button></div><div className="coverage-list">{items.map((item) => <div className="coverage-row" key={item.ticker}><strong>{item.ticker}</strong><span>{item.documents} 份文档</span><span>{item.chunks} 个 Chunk</span><span className="coverage-date">更新至 {item.latest_available_at || "未知"}</span></div>)}{items.length === 0 && <p className="helper-text">数据库中还没有财报数据。</p>}</div></section>;
}

function SearchPanel({ result }: { result: SearchResponse }) {
  return <section className="panel"><div className="panel-heading"><div><p className="eyebrow">证据层</p><h2>检索到的财报片段</h2></div><span className={`source-pill ${result.source}`}>{result.source === "postgres" ? "本地知识库" : "SEC 在线兜底"}</span></div><div className="metric-strip"><Metric icon={<Gauge size={15} />} label="检索耗时" value={`${result.elapsed_ms} ms`} /><Metric icon={<BookOpen size={15} />} label="命中文档" value={String(result.documents)} /><Metric icon={<FileSearch size={15} />} label="命中 Chunk" value={String(result.hits.length)} /><Metric icon={<Database size={15} />} label="日期边界" value={result.future_safe ? "通过" : "失败"} /></div><div className="evidence-list">{result.hits.map((hit, index) => <article className="evidence-item" key={hit.chunk_id}><div className="evidence-title"><span className="rank">{String(index + 1).padStart(2, "0")}</span><strong>{hit.section_title}</strong><span className="doc-type">{hit.document_type}</span></div><p>{hit.content}</p><footer>{hit.document_id} · available_at {hit.available_at} · <a href={hit.source_url} target="_blank" rel="noreferrer">查看来源 <ArrowUpRight size={12} /></a></footer></article>)}</div></section>;
}

function AgentPanel({ result }: { result: AgentResponse }) {
  const report = result.report;
  return <section className="panel report-panel"><div className="panel-heading"><div><p className="eyebrow">Agent 输出</p><h2>{report.ticker} 基本面判断</h2><span className="helper-text">分析日期 {report.as_of} · LangGraph 基本面专项流程</span></div><span className={`rating ${report.rating}`}>{report.rating}</span></div><div className="metric-strip"><Metric icon={<Activity size={15} />} label="总耗时" value={`${result.total_seconds}s`} /><Metric icon={<Sparkles size={15} />} label="LLM 调用" value={String(result.llm_calls)} /><Metric icon={<FileSearch size={15} />} label="工具执行" value={String(result.tool_node_runs)} /><Metric icon={<Gauge size={15} />} label="步骤数" value={String(result.steps)} /></div><div className="report-sections">{report.sections.map((section) => <article className={`report-section ${section.kind}`} key={`${section.title}-${section.kind}`}><h3>{section.title}</h3><p>{section.content}</p></article>)}</div><details><summary>查看原始 Agent 报告</summary><pre>{report.raw_markdown}</pre></details></section>;
}

function JobStatus({ job }: { job: IngestionJob }) {
  const summary = job.summary;
  return <section className="panel job-panel"><div className="panel-heading"><div><p className="eyebrow">数据准备任务</p><h2>{job.ticker} 财报增量同步</h2></div><span className={`job-pill ${job.status}`}>{job.status}</span></div><div className="job-progress"><span>{job.progress}</span>{(job.status === "queued" || job.status === "running") && <LoaderCircle className="spin" size={16} />}</div>{job.status === "succeeded" && summary && <p className="helper-text">新增文档 {summary.documents_inserted ?? 0} 份 · 新增 Chunk {summary.chunks_inserted ?? 0} 个 · 写入向量 {summary.embedding_rows_written ?? 0} 条</p>}{job.status === "failed" && <div className="error-box"><AlertTriangle size={16} />{job.error_message || "任务失败"}</div>}</section>;
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) { return <div className="metric"><span>{icon}{label}</span><strong>{value}</strong></div>; }
function EmptyState() { return <section className="empty-state"><div className="empty-icon"><BookOpen size={24} /></div><h2>等待一项研究任务</h2><p>选择股票和日期后，先检索真实财报证据，再生成可追溯的基本面报告。</p></section>; }

export default App;
