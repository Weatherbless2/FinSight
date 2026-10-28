# R-13：Airflow 调度边界

新增 `deploy/airflow/dags/tradeagent_rag_ingestion.py`。DAG 每日 03:00 运行，先执行 SEC 发现，再执行仓库已有的幂等 SEC 下载、解析、Chunk、PostgreSQL 入库和 Embedding pipeline；任务失败最多重试 3 次，单次只允许一个 active run，关闭 catchup 避免一次性补跑历史日期。

Airflow 只保存调度元数据和任务状态，不保存原文、Chunk、向量或引用事实。任务通过 `ticker` 和 `limit_per_form` 参数运行，实际状态继续写入现有 `ingestion_jobs`/`ingestion_runs`，MinIO 和 PostgreSQL 分别承担原始对象和可信数据源。

验证：`tests/test_airflow_dag_contract.py` 检查 DAG ID、任务顺序、重试边界和并发边界。目标部署环境还需要安装 Airflow provider、配置 DAG import path 和 Secret backend 后执行一次真实调度验收。
