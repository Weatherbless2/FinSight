# R-17：安全部署和持续交付

## 实施范围

R-17 固化 TradeAgent 容器和 RAG 依赖的部署契约：应用镜像使用非 root 用户 `appuser`；PostgreSQL、Redis 使用独立持久卷和健康检查；密钥从 `.env` 或部署平台 Secret 注入，不复制到镜像；GitHub Actions 在多版本 Python 上执行测试、干净安装导入检查和 Ruff 检查。

当前 Compose 的 `rag` profile 提供 PostgreSQL、Redis、MinIO 和 OpenSearch；`rag-model` profile 单独提供 BGE-M3/TEI。默认密码仅是本地学习环境占位值。生产环境必须覆盖 `POSTGRES_PASSWORD`、MinIO 凭证、端口和外部服务地址，并禁止把 `.env` 复制到镜像或提交到 Git。

## 发布顺序

1. `docker compose --profile rag config` 检查变量展开结果，确认生产 Secret 已注入。
2. `docker compose --profile rag up -d postgres redis`，等待 `docker compose --profile rag ps` 显示 `healthy`。
3. 在应用发布前按文件名顺序执行 `db/migrations/*.sql`（例如在 PostgreSQL 容器中使用 `psql -v ON_ERROR_STOP=1`），保存已执行文件名和 migration 校验值。
4. 启动应用并检查 `GET /health` 返回 `{"status":"ok","service":"rag-demo"}`。
5. 使用固定评测集执行 R-15；只有真实模型、OpenSearch 和数据服务可用时才记录线上指标。

## 备份、回滚和验收

- PostgreSQL：使用 `pg_dump` 生成带时间戳的备份，保留 migration 版本和备份校验值；恢复前停止写入任务。
- Redis：只保存短期缓存和任务协同状态，不能作为 PostgreSQL 原文、Chunk 或引用的唯一副本。
- 应用回滚：回滚到上一镜像 tag，并保留已执行 migration 记录；数据库变更只允许向后兼容，破坏性变更必须先完成数据迁移。
- 验收：容器健康、`/health` 200、R-16 API 契约测试通过、密钥扫描无 `.env`/私钥进入构建上下文，且 R-15 评测报告区分实测结果和历史基线。

## 已验证和边界

本仓库已存在非 root Dockerfile、PostgreSQL/Redis healthcheck、`.dockerignore` 对 `.env` 的排除，以及 CI 的测试、干净安装和 Ruff 三类检查。R-17 本轮静态检查通过；未在本机执行生产镜像构建、真实 Secret 管理、备份恢复演练或 Kubernetes/云平台部署验收，这些属于部署环境验证项。
