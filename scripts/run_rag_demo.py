"""FastAPI RAG 演示页：展示真实 PostgreSQL 检索结果和基本面 Agent 报告。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from tradingagents.rag.embeddings import OllamaEmbeddingProvider
from tradingagents.rag.ingestion_pipeline import run_sec_ingestion_pipeline
from tradingagents.rag.online_fallback import OnlineSecFallback
from tradingagents.rag.postgres import create_postgres_engine
from tradingagents.rag.postgres_retrieval import PostgresRetriever
from tradingagents.reporting_schema import structure_fundamentals_report

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TradeAgent RAG 演示</title>
  <style>
    :root { --ink:#17212b; --muted:#687684; --line:#dce3e8; --blue:#1769aa; --blue-bg:#eaf4fb; --green:#19734a; --green-bg:#eaf7f0; --amber:#9a6411; --amber-bg:#fff6df; --red:#a33b32; --red-bg:#fff1ef; --paper:#f5f7f9; }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--ink); background:var(--paper); font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }
    .shell { max-width:1180px; margin:0 auto; padding:28px 20px 48px; }
    header { display:flex; justify-content:space-between; gap:20px; align-items:flex-end; margin-bottom:24px; }
    h1 { margin:0; font-size:28px; letter-spacing:0; }
    .subtitle { color:var(--muted); margin:6px 0 0; }
    .status { color:var(--green); background:var(--green-bg); border:1px solid #b8e0ca; padding:7px 11px; border-radius:6px; white-space:nowrap; }
    .panel { background:#fff; border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:16px; }
    .controls { display:grid; grid-template-columns:110px 150px 150px 1fr; gap:12px; align-items:end; }
    label { display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }
    input, select, textarea { width:100%; border:1px solid #c8d2da; border-radius:5px; padding:9px 10px; color:var(--ink); background:#fff; font:inherit; }
    textarea { min-height:74px; resize:vertical; }
    .question { grid-column:1 / -1; }
    .actions { display:flex; gap:10px; align-items:center; margin-top:14px; }
    button { border:0; border-radius:5px; padding:9px 14px; color:#fff; background:var(--blue); cursor:pointer; font:inherit; }
    button.secondary { background:#52616d; }
    button.outline { color:var(--blue); background:#fff; border:1px solid #a9c9df; }
    button:disabled { opacity:.55; cursor:wait; }
    .hint { color:var(--muted); font-size:12px; }
    .metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
    .metric { border-left:3px solid var(--blue); background:var(--blue-bg); padding:10px 12px; }
    .metric b { display:block; font-size:20px; }
    .metric span { color:var(--muted); font-size:12px; }
    .hidden { display:none; }
    .result-title { display:flex; justify-content:space-between; align-items:center; gap:12px; border-bottom:1px solid var(--line); padding-bottom:10px; margin-bottom:12px; }
    h2 { margin:0; font-size:18px; }
    .trace { color:var(--muted); font-size:12px; }
    .hit { border:1px solid var(--line); border-radius:6px; padding:13px; margin:10px 0; background:#fff; }
    .hit-head { display:flex; justify-content:space-between; gap:12px; }
    .hit h3 { margin:0; font-size:14px; }
    .badge { color:var(--blue); background:var(--blue-bg); border-radius:4px; padding:2px 7px; font-size:12px; white-space:nowrap; }
    .meta { color:var(--muted); font-size:12px; margin:5px 0; }
    .content { white-space:pre-wrap; color:#293640; }
    .source { color:var(--blue); overflow-wrap:anywhere; font-size:12px; }
    .report-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .report-card { border:1px solid var(--line); border-radius:7px; padding:15px; background:#fff; min-width:0; }
    .report-card.summary { grid-column:1 / -1; border-left:4px solid var(--blue); background:var(--blue-bg); }
    .report-card.metrics { border-left:4px solid var(--green); background:var(--green-bg); }
    .report-card.risk { border-left:4px solid var(--red); background:var(--red-bg); }
    .report-card.outlook { border-left:4px solid var(--amber); background:var(--amber-bg); }
    .report-card h3 { margin:0 0 8px; font-size:15px; }
    .report-card p { margin:0; white-space:pre-wrap; }
    .rating { display:inline-flex; align-items:center; justify-content:center; min-width:86px; padding:7px 14px; border-radius:999px; font-size:18px; font-weight:700; letter-spacing:.04em; }
    .rating.BUY { color:var(--green); background:var(--green-bg); }
    .rating.HOLD { color:var(--amber); background:var(--amber-bg); }
    .rating.SELL { color:var(--red); background:var(--red-bg); }
    .rating.UNKNOWN { color:var(--muted); background:#eef1f3; }
    .report-overview { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; border-bottom:1px solid var(--line); padding-bottom:14px; margin-bottom:14px; }
    .report-overview h3 { margin:0 0 4px; font-size:15px; }
    .report-overview p { margin:0; color:var(--muted); font-size:12px; }
    details { margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }
    summary { color:var(--muted); cursor:pointer; font-size:12px; }
    .raw-report { white-space:pre-wrap; color:#293640; margin-top:10px; }
    .coverage { display:flex; flex-wrap:wrap; gap:8px; }
    .coverage-item { border:1px solid var(--line); border-radius:6px; padding:8px 11px; background:#fbfcfd; }
    .coverage-item strong { color:var(--blue); margin-right:5px; }
    .error { color:#a33b32; background:#fff1ef; border:1px solid #efc4bf; padding:10px; border-radius:5px; }
    @media (max-width:760px) { header { display:block; } .status { display:inline-block; margin-top:12px; } .controls { grid-template-columns:1fr 1fr; } .question { grid-column:1 / -1; } .metrics { grid-template-columns:1fr 1fr; } .report-grid { grid-template-columns:1fr; } .report-card.summary { grid-column:auto; } .report-overview { display:block; } }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><h1>TradeAgent 投研工作台</h1><p class="subtitle">基本面 Agent · 财报检索 · 可追溯证据</p></div>
      <div class="status">本地优先 · PostgreSQL + pgvector</div>
    </header>
    <section class="panel">
      <div class="controls">
        <div><label for="ticker">股票代码</label><input id="ticker" value="TSLA"></div>
        <div><label for="asOf">分析日期</label><input id="asOf" type="date" value="2025-03-01"></div>
        <div><label for="strategy">检索策略</label><select id="strategy"><option value="hybrid">Hybrid</option><option value="keyword">关键词</option><option value="vector">向量</option></select></div>
        <div><label for="topK">返回数量</label><input id="topK" type="number" min="1" max="10" value="5"></div>
        <div class="question"><label for="question">研究问题</label><textarea id="question">TSLA 当前主要经营风险是什么？结合财报说明管理层对后续经营有什么展望？</textarea></div>
      </div>
      <div class="actions">
        <button id="searchBtn" onclick="searchRag()">检索真实财报</button>
        <button id="agentBtn" class="secondary" onclick="runAgent()">生成基本面 Agent 报告</button>
        <button id="ingestBtn" class="outline" onclick="startIngestion()">准备/更新财报</button>
        <span id="message" class="hint">先检索可以快速查看真实 Chunk；生成报告会调用 gpt-5.5。</span>
      </div>
      <div id="jobMessage" class="hint" style="margin-top:10px"></div>
    </section>
    <section class="panel"><div class="result-title"><h2>本地财报覆盖</h2><span id="coverageStatus" class="trace">正在读取数据库</span></div><div id="coverage" class="coverage"></div></section>
    <section id="metrics" class="panel hidden"><div class="metrics" id="metricGrid"></div></section>
    <section id="searchResult" class="panel hidden"><div class="result-title"><h2>检索证据</h2><span id="trace" class="trace"></span></div><div id="hits"></div></section>
    <section id="agentResult" class="panel hidden"><div class="result-title"><h2>基本面 Agent 报告</h2><span id="agentTrace" class="trace"></span></div><div id="report"></div></section>
  </main>
  <script>
    const $ = id => document.getElementById(id);
    const payload = () => ({ticker:$('ticker').value, as_of:$('asOf').value, strategy:$('strategy').value, top_k:Number($('topK').value), question:$('question').value});
    function busy(button, value) { button.disabled=value; }
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
    function showError(target, error) { target.innerHTML = `<div class="error">${escapeHtml(error)}</div>`; }
    async function loadCoverage() {
      try { const response=await fetch('/api/coverage'); const data=await response.json(); if(!response.ok) throw new Error(data.detail || '覆盖范围读取失败'); $('coverage').innerHTML=data.items.map(item=>`<div class="coverage-item"><strong>${escapeHtml(item.ticker)}</strong>${item.documents} 份文档 · ${item.chunks} 个 Chunk</div>`).join('') || '<span class="hint">数据库中暂无财报。</span>'; $('coverageStatus').textContent=`共 ${data.total_tickers} 个股票代码`; }
      catch(error) { $('coverageStatus').textContent='读取失败'; $('coverage').innerHTML=`<div class="error">${escapeHtml(error.message)}</div>`; }
    }
    async function searchRag() {
      const button=$('searchBtn'); busy(button,true); $('message').textContent='正在查询 PostgreSQL 和 pgvector...';
      try {
        const response=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});
        const data=await response.json(); if(!response.ok) throw new Error(data.detail || data.error || '检索失败');
        $('metrics').classList.remove('hidden'); $('searchResult').classList.remove('hidden');
        $('metricGrid').innerHTML=`<div class="metric"><b>${data.hits.length}</b><span>命中 Chunk</span></div><div class="metric"><b>${data.documents}</b><span>命中文档</span></div><div class="metric"><b>${data.elapsed_ms} ms</b><span>检索耗时</span></div><div class="metric"><b>${data.future_safe?'通过':'失败'}</b><span>日期边界检查</span></div>`;
        const sourceLabel = data.source === 'online_sec' ? 'SEC 在线兜底（当前未入库）' : 'PostgreSQL 本地知识库';
        $('trace').textContent=`来源：${sourceLabel} ｜ 策略：${escapeHtml(data.strategy)} ｜ 查询：${escapeHtml(data.expanded_query)} ｜ as_of：${escapeHtml(data.as_of)}`;
        $('hits').innerHTML=data.hits.length ? data.hits.map((hit,index)=>`<article class="hit"><div class="hit-head"><h3>${index+1}. ${escapeHtml(hit.section_title)}</h3><span class="badge">${escapeHtml(hit.document_type)}</span></div><div class="meta">${escapeHtml(hit.document_id)} ｜ available_at=${escapeHtml(hit.available_at)} ｜ vector=${hit.vector_score.toFixed(4)} ｜ keyword=${hit.keyword_score.toFixed(4)}</div><div class="content">${escapeHtml(hit.content)}</div><div class="source">来源：${escapeHtml(hit.source_url)}</div></article>`).join('') : '<p class="hint">没有命中证据。</p>';
        $('message').textContent='检索完成，可以展开查看每条真实 Chunk。';
      } catch(error) { $('searchResult').classList.remove('hidden'); showError($('hits'), error.message); $('message').textContent='检索失败，请查看错误信息。'; }
      finally { busy(button,false); }
    }
    function renderReport(data) {
      const report = data.report || {};
      const rating = escapeHtml(report.rating || 'UNKNOWN');
      const sections = Array.isArray(report.sections) ? report.sections : [];
      const cards = sections.map(section => `<article class="report-card ${escapeHtml(section.kind || 'detail')}"><h3>${escapeHtml(section.title)}</h3><p>${escapeHtml(section.content)}</p></article>`).join('');
      $('report').innerHTML=`<div class="report-overview"><div><h3>${escapeHtml(report.ticker || data.ticker)} 基本面判断</h3><p>分析日期：${escapeHtml(report.as_of || data.trade_date)} ｜ 证据来自基本面 Agent 工具循环</p></div><span class="rating ${rating}">${rating}</span></div><div class="report-grid">${cards || '<div class="hint">Agent 没有返回结构化章节。</div>'}</div><details><summary>查看原始 Agent 报告</summary><div class="raw-report">${escapeHtml(report.raw_markdown || data.fundamentals_report || '')}</div></details>`;
    }
    async function runAgent() {
      const button=$('agentBtn'); busy(button,true); $('message').textContent='Agent 正在调用基本面工具和 gpt-5.5，可能需要 1～2 分钟...';
      try { const response=await fetch('/api/agent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())}); const data=await response.json(); if(!response.ok) throw new Error(data.detail || data.error || 'Agent 执行失败'); $('agentResult').classList.remove('hidden'); $('agentTrace').textContent=`耗时：${data.total_seconds}s ｜ LLM：${data.llm_calls} ｜ 工具：${data.tool_node_runs} ｜ Token：${data.tokens_in} 入 / ${data.tokens_out} 出`; renderReport(data); $('message').textContent='Agent 报告生成完成。'; }
      catch(error) { $('agentResult').classList.remove('hidden'); showError($('report'), error.message); $('message').textContent='Agent 执行失败，请查看错误信息。'; }
      finally { busy(button,false); }
    }
    async function startIngestion() {
      const button=$('ingestBtn'); busy(button,true); $('jobMessage').textContent='正在创建财报增量任务...';
      try {
        const response=await fetch('/api/ingestion-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker:$('ticker').value,as_of:$('asOf').value,limit_per_form:1})});
        const data=await response.json(); if(!response.ok) throw new Error(data.detail || '任务创建失败');
        $('jobMessage').textContent=`任务 ${data.job_id}：${data.progress}`; pollIngestion(data.job_id);
      } catch(error) { $('jobMessage').textContent=`任务创建失败：${error.message}`; }
      finally { busy(button,false); }
    }
    async function pollIngestion(jobId) {
      const response=await fetch(`/api/ingestion-jobs/${jobId}`); const data=await response.json();
      if(!response.ok) { $('jobMessage').textContent=data.detail || '任务查询失败'; return; }
      $('jobMessage').textContent=`任务状态：${data.status} ｜ ${data.progress}`;
      if(data.status === 'queued' || data.status === 'running') { window.setTimeout(() => pollIngestion(jobId), 1500); return; }
      if(data.status === 'succeeded') { $('jobMessage').textContent=`财报准备完成：新增 ${data.summary?.documents_inserted ?? 0} 份文档、${data.summary?.chunks_inserted ?? 0} 个 Chunk`; loadCoverage(); }
      if(data.status === 'failed') { $('jobMessage').textContent=`财报准备失败：${data.error_message || '未知错误'}`; }
    }
    loadCoverage();
  </script>
</body>
</html>"""


def _expand_query(query: str) -> str:
    """补充英文财报词，帮助英文 SEC 语料承接中文问题。"""
    replacements = {
        "经营风险": "business risk risk factors",
        "风险": "risk factors",
        "经营": "business operations",
        "展望": "outlook guidance management discussion",
        "管理层": "management",
        "营收": "revenue",
        "利润": "profit income margin",
        "财报": "annual report 10-k financial statements",
    }
    expanded = query.strip()
    for source, target in replacements.items():
        expanded = expanded.replace(source, f" {target} ")
    return " ".join(expanded.split())


class DemoService:
    """演示页的真实检索服务；数据库和模型只在服务启动时创建一次。"""

    def __init__(self) -> None:
        self.engine = create_postgres_engine()
        self.provider = OllamaEmbeddingProvider()
        self.retriever = PostgresRetriever(engine=self.engine, embedding_provider=self.provider)
        self.online_fallback = None
        if os.getenv("TRADINGAGENTS_ENABLE_ONLINE_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}:
            self.online_fallback = OnlineSecFallback(self.provider)
        self.lock = threading.Lock()

    def search(self, payload: dict) -> dict:
        ticker = str(payload.get("ticker", "")).strip().upper()
        as_of = date.fromisoformat(str(payload.get("as_of")))
        query = str(payload.get("question", "")).strip()
        strategy = str(payload.get("strategy", "hybrid"))
        top_k = int(payload.get("top_k", 5))
        if not ticker or not query:
            raise ValueError("股票代码和研究问题不能为空")
        if strategy not in {"keyword", "vector", "hybrid"}:
            raise ValueError("不支持的检索策略")
        if not 1 <= top_k <= 10:
            raise ValueError("返回数量必须在 1 到 10 之间")
        expanded = _expand_query(query)
        started = time.perf_counter()
        source = "postgres"
        with self.lock:
            hits = getattr(self.retriever, f"{strategy}_search")(
                expanded, ticker=ticker, as_of=as_of, top_k=top_k
            )
            if not hits and self.online_fallback is not None:
                hits = self.online_fallback.search(
                    expanded, ticker=ticker, as_of=as_of, top_k=top_k
                )
                source = "online_sec"
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        documents = tuple(dict.fromkeys(hit.document_id for hit in hits))
        return {
            "ticker": ticker,
            "as_of": as_of.isoformat(),
            "strategy": strategy,
            "source": source,
            "persisted": source == "postgres",
            "expanded_query": expanded,
            "elapsed_ms": elapsed_ms,
            "documents": len(documents),
            "future_safe": all(hit.available_at <= as_of for hit in hits),
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "document_id": hit.document_id,
                    "document_type": hit.document_type,
                    "section_title": hit.section_title,
                    "content": hit.content,
                    "source_url": hit.source_url,
                    "available_at": hit.available_at.isoformat(),
                    "vector_score": hit.vector_score,
                    "keyword_score": hit.keyword_score,
                }
                for hit in hits
            ],
        }

    def run_agent(self, payload: dict) -> dict:
        """调用现有基本面专项 Agent，不另写一套回答逻辑。"""
        from tradingagents.observability.runner import InstrumentedRunner

        ticker = str(payload.get("ticker", "")).strip().upper()
        trade_date = str(payload.get("as_of", ""))
        question = str(payload.get("question", "")).strip()
        if not ticker or not question:
            raise ValueError("股票代码和研究问题不能为空")
        # 必须在构造 TradingAgentsGraph 之前开启 RAG，图初始化时会读取这个开关。
        os.environ["TRADINGAGENTS_ENABLE_POSTGRES_RAG"] = "true"
        from tradingagents.default_config import DEFAULT_CONFIG

        temp_root = tempfile.mkdtemp(prefix="tradeagent_demo_")
        config = DEFAULT_CONFIG.copy()
        config.update(
            {
                "llm_provider": "openai",
                "deep_think_llm": os.getenv("TRADINGAGENTS_DEEP_THINK_LLM", "gpt-5.5"),
                "quick_think_llm": os.getenv("TRADINGAGENTS_QUICK_THINK_LLM", "gpt-5.5"),
                "backend_url": os.getenv(
                    "TRADINGAGENTS_LLM_BACKEND_URL", "https://gptch.cloud/v1"
                ),
                "openai_reasoning_effort": "low",
                "llm_max_retries": 0,
                "llm_max_tokens": 1200,
                "max_debate_rounds": 0,
                "max_risk_discuss_rounds": 0,
                "news_article_limit": 5,
                "global_news_article_limit": 3,
                "checkpoint_enabled": False,
                "memory_log_path": f"{temp_root}/trading_memory.md",
                "data_cache_dir": f"{temp_root}/cache",
                "results_dir": f"{temp_root}/results",
            }
        )
        runner = InstrumentedRunner(
            config=config,
            selected_analysts=("fundamentals",),
            fixture_data=True,
            verbose=False,
        )
        result = runner.run_fundamentals_only(ticker, trade_date, question)
        result["report"] = structure_fundamentals_report(
            result.get("fundamentals_report", ""),
            ticker=ticker,
            as_of=trade_date,
        ).model_dump(mode="json")
        return result


class SearchRequest(BaseModel):
    """浏览器检索请求；Pydantic 负责入口参数校验。"""

    ticker: str = Field(min_length=1, max_length=32)
    as_of: date
    strategy: Literal["keyword", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=10)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("ticker", "question")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class IngestionRequest(BaseModel):
    """新增股票财报同步请求。"""

    ticker: str = Field(min_length=1, max_length=32)
    as_of: date
    limit_per_form: int = Field(default=1, ge=1, le=5)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("股票代码不能为空")
        return value


app = FastAPI(title="TradeAgent RAG Demo", version="0.1.0")
load_dotenv(".env")
_service: DemoService | None = None
_service_lock = threading.Lock()
_ingestion_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-ingest")


def get_service() -> DemoService:
    """首次收到业务请求时再建立数据库和 Embedding 客户端。"""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = DemoService()
    return _service


def _update_ingestion_job(
    job_id: UUID,
    *,
    status: str,
    progress: str,
    summary: dict | None = None,
    error: str | None = None,
) -> None:
    """后台任务每个阶段更新一次状态，页面无需猜测当前执行位置。"""
    with get_service().engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE ingestion_jobs
                SET status = :status,
                    progress = :progress,
                    summary = CAST(:summary AS jsonb),
                    error_message = :error,
                    started_at = CASE WHEN :status = 'running' AND started_at IS NULL
                                      THEN CURRENT_TIMESTAMP ELSE started_at END,
                    finished_at = CASE WHEN :status IN ('succeeded', 'failed')
                                       THEN CURRENT_TIMESTAMP ELSE finished_at END
                WHERE job_id = :job_id
                """
            ),
            {
                "job_id": job_id,
                "status": status,
                "progress": progress,
                "summary": json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                "error": error,
            },
        )


def _run_ingestion_job(job_id: UUID, ticker: str, as_of: date, limit_per_form: int) -> None:
    """后台执行完整增量链路；失败只更新任务，不影响 API 进程。"""
    try:
        _update_ingestion_job(job_id, status="running", progress="正在从 SEC 发现财报")
        summary = run_sec_ingestion_pipeline(ticker, as_of, limit_per_form=limit_per_form)
        _update_ingestion_job(
            job_id,
            status="succeeded",
            progress="下载、切分、入库和向量化完成",
            summary=summary,
        )
    except Exception as exc:  # noqa: BLE001 - 状态必须持久化给页面
        _update_ingestion_job(
            job_id,
            status="failed",
            progress="任务失败，请查看错误信息",
            error=f"{type(exc).__name__}: {exc}"[:4000],
        )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """返回演示页面。"""
    return HTML


@app.get("/health")
def health() -> dict[str, str]:
    """提供容器或浏览器的最小健康检查。"""
    return {"status": "ok", "service": "rag-demo"}


@app.get("/api/coverage")
def coverage() -> dict:
    """返回当前 PostgreSQL 中已经具备财报 Chunk 的股票覆盖范围。"""
    try:
        with get_service().engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT d.ticker,
                           COUNT(DISTINCT d.document_id) AS documents,
                           COUNT(c.chunk_id) AS chunks,
                           COUNT(*) FILTER (WHERE c.embedding_status = 'succeeded') AS embedded_chunks,
                           MAX(d.available_at) AS latest_available_at
                    FROM documents AS d
                    JOIN document_chunks AS c ON c.document_id = d.document_id
                    GROUP BY d.ticker
                    ORDER BY d.ticker
                    """
                )
            ).mappings().all()
        return {
            "total_tickers": len(rows),
            "items": [
                {
                    "ticker": row["ticker"],
                    "documents": row["documents"],
                    "chunks": row["chunks"],
                    "embedded_chunks": row["embedded_chunks"],
                    "latest_available_at": (
                        row["latest_available_at"].isoformat()
                        if row["latest_available_at"]
                        else None
                    ),
                }
                for row in rows
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/ingestion-jobs", status_code=202)
def create_ingestion_job(request: IngestionRequest) -> dict:
    """创建 SEC 财报增量任务，立即返回 job_id，不阻塞浏览器请求。"""
    try:
        job_id = uuid4()
        with get_service().engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO ingestion_jobs (job_id, ticker, as_of, status, source, progress)
                    VALUES (:job_id, :ticker, :as_of, 'queued', 'sec', '等待后台 Worker 执行')
                    """
                ),
                {"job_id": job_id, "ticker": request.ticker, "as_of": request.as_of},
            )
        executor_name = os.getenv("TRADINGAGENTS_TASK_EXECUTOR", "thread").lower()
        if executor_name == "celery":
            # 只有显式选择 Celery 时才导入 celery，默认本地学习环境无需安装它。
            from tradingagents.tasks.ingestion_tasks import run_sec_ingestion_task

            run_sec_ingestion_task.delay(
                str(job_id), request.ticker, request.as_of.isoformat(), request.limit_per_form
            )
        elif executor_name == "thread":
            _ingestion_executor.submit(
                _run_ingestion_job,
                job_id,
                request.ticker,
                request.as_of,
                request.limit_per_form,
            )
        else:
            raise ValueError("TRADINGAGENTS_TASK_EXECUTOR must be 'thread' or 'celery'")
        return {"job_id": str(job_id), "status": "queued", "progress": "等待后台 Worker 执行"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/api/ingestion-jobs/{job_id}")
def get_ingestion_job(job_id: UUID) -> dict:
    """查询财报发现、处理和向量化任务的持久化状态。"""
    try:
        with get_service().engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT job_id, ticker, as_of, status, source, progress,
                           summary, error_message, created_at, started_at, finished_at
                    FROM ingestion_jobs WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in row.items()
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/search")
def search(request: SearchRequest) -> dict:
    """执行真实关键词、向量或 Hybrid 检索。"""
    try:
        return get_service().search(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/agent")
def agent(request: SearchRequest) -> dict:
    """调用已有基本面专项 Agent，返回真实报告和运行指标。"""
    try:
        return get_service().run_agent(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc


def main() -> None:
    """使用 Uvicorn 启动 FastAPI 应用。"""
    import argparse

    parser = argparse.ArgumentParser(description="启动 TradeAgent FastAPI RAG 演示")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
