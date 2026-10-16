# Runner Console

UI Automation runner 的独立控制台（原 `D:/UIAutomation/webui` 重构而来）。

- **后端**：FastAPI + uvicorn ｜ MySQL 8（PyMySQL + DBUtils 连接池）
- **前端**：零构建 vanilla JS（ES Modules），`python -m http.server` 即可预览，`?mock=1` 全 mock 模式
- **部署**：同一台 Windows，端口 8765；通过 config 指向 runner 仓库（默认 `D:/UIAutomation`）与其 `artifacts/`

## 快速开始

```bat
:: 1. 前置：本机 MySQL 8 已安装，建库：
::    CREATE DATABASE runner_console CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
:: 2. 配置
copy config.example.toml config.toml
::    编辑 config.toml：[database] 连接信息、[paths] workdir/artifacts_root、[auth]/[gitlab]
:: 3. 启动（自动建 venv、跑迁移、起服务）
start_server.bat
:: 4. 打开 http://127.0.0.1:8765/（GitLab PAT 或本地账号登录）
```

前端单独预览（无需后端）：`python -m http.server 8080` → `http://localhost:8080/frontend/?mock=1`

## 与 runner 的契约（`D:/UIAutomation` 侧已同步改造）

| 契约 | 说明 |
|---|---|
| `RUN_ID: <id>` stdout 行 | runner 启动即输出（flush），LoopRunner 解析替代扫目录 |
| `artifacts/<run_id>/run_meta.json` | run_id/product/started_at/cli_args/host |
| `summary.json` 增补字段 | env_name/git_ref/host/exit_code（旧字段不变） |
| `python -m runner` CLI | 不变 |
| `.runner.lock` | 位置/格式不变，仍在 env 目录 |

exit code 语义：0 全 pass / 1 有 case fail / 2 仅 Job setup 失败 / 3 case setup 或 teardown broken；"runner 未起来"由「Popen 异常或无 RUN_ID 行」判定。

## 目录

```
app/          FastAPI 后端（api/ 路由、core/ 执行引擎、db/ schema+DAO、ingest/ 产物入库、realtime/ SSE、auth/）
frontend/     零构建前端（views: console 运行台 / tasks 任务中心 / dashboard 看板 / resources 资源 / admin 管理）
app/db/schema.sql        MySQL 权威 DDL（13 表）
app/db/migrations/       版本化迁移
config.example.toml      配置模板（含中文注释）
start_server.bat         一键启动（venv + migrate + uvicorn 8765）
```

## 数据模型要点

- 结构化结果全部入 MySQL：`runs / cases / case_failures / artifact_files`（ingest 在每轮 iteration 结束后进程内同步执行）
- 大文件（截图 PNG / support tgz / 日志）留磁盘，DB 只存 `artifact_files` 路径索引
- 环境锁维持 `.runner.lock` 文件契约（跨进程正确载体），DB 侧 environments + env_grants 表管理环境与分级授权（viewer/operator）
- session 只存 sha256（HttpOnly Cookie），GitLab PAT 不落盘
- 保留策略（retain_count/retain_days）是 artifacts 清理唯一持有方：先删盘后删库，FK 级联

## API

启动后访问 `/docs`（FastAPI 自动 OpenAPI）。核心端点：

| 域 | 端点 |
|---|---|
| 认证 | POST /api/login · /api/logout · GET /api/me |
| 运行 | POST /api/run · GET /api/loops[/{id}[/status]] · POST /api/loops/{id}/stop |
| 结果 | GET /api/runs[/{id}] · /api/runs/{id}/cases · /api/runs/{id}/joblog · /api/runs/{id}/summary.html |
| 实时 | GET /api/loops/{id}/console（SSE：snapshot → append* → end，Last-Event-ID 续传） |
| 资源 | /api/envs CRUD · /api/envs/{id}/grants · /api/lock/force-release · /api/uploads |
| 管理 | /api/admin/users · /api/admin/audit · /api/admin/settings |
| 产物 | GET /runs/{run_id}/{relpath}（带鉴权文件流，防路径穿越） |

## 审计 action 枚举

`loop.start` / `loop.stop` / `loop.recovered` / `env.lock.force-release` / `env.grant` / `env.grant.revoke` / `retention.run` / `settings.update` / `user.role` / `user.reset` / `register` / `login` / `logout` / `upload.create`
