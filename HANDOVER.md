# HANDOVER — 交接给 CodeBuddy 执行

> 生成时间：2026-10-15 15:11 ｜ 前序：Runner Console 项目重构（计划文件 `C:\Users\yawu\.workbuddy\plans\quantum-forging-tesla-XrbvnUrA.md`）
> 背景：重构由 9 个 subagent 完成 T1–T12，但执行期间本机 shell 通道全程断连，**所有代码只做过静态审查，从未运行过**。你（CodeBuddy）有 shell，请按下面顺序执行。

## 一、项目状态一览

### D:\RunnerConsole（新项目，已完成 T1–T12，未 git init）

```
app/
  main.py                  FastAPI 工厂（lifespan: pool → JobManager → recover_orphans → startup retention）
  config.py                tomllib + RC_ 环境变量覆盖，get_settings() 单例
  schemas.py               Pydantic 模型（LoginIn/RunIn/EnvIn/…）
  db/
    pool.py                PyMySQL + DBUtils PooledDB（maxconnections=8，启动 ping，无降级）
    schema.sql             权威 DDL 13 表（MySQL 8 / utf8mb4 / InnoDB）
    migrations/V1__init.sql  版本化初始迁移（与 schema.sql 一致）
    migrate.py             python -m app.db.migrate --config config.toml（幂等）
    dao/                   users.py / loops.py / runs.py / audit.py / settings.py
  auth/                    gitlab.py(PAT) / local.py(PBKDF2) / sessions.py(sha256+HttpOnly Cookie) / perms.py
  core/
    job_manager.py         start/stop/get/console_tail/clear_lock/recover_orphans/build_command
    loop_runner.py         LoopRunner：worktree→env 拷入→Popen→RUN_ID 捕获(60s 兜底扫目录)→ingest 调用点
    env_lock.py            .runner.lock 契约不变（Windows ctypes 判活）
    git_worktree.py        worktree 准备/清理/artifacts junction
    env_files.py           firebox.env 解析/脱敏
    retention.py           先删盘后删库 + FK CASCADE + 孤儿目录兜底
  ingest/run_ingest.py     ingest_run()：summary.json+run_meta.json → runs/cases/case_failures/artifact_files
  api/                     auth/loops/runs/cases/env/uploads/admin/stats/status/files_routes + deps.py
  realtime/                console_tail.py(TailStream+Hub) + sse_routes.py(SSE)
frontend/                  零构建：index.html + css/design-tokens.css + js/(api/store/router/main/mock-data/ui/chart-lite + views/×5)
                           ?mock=1 全 mock 模式（无后端可演示）
tests/                     （空，未建单测）
start_server.bat           venv 创建 + migrate + uvicorn 8765
config.example.toml        配置模板（中文注释）
README.md / DEPLOY.md      项目说明 / 部署步骤
```

### D:\UIAutomation（runner 侧契约改造已完成，**未 commit**）

改动文件（T2，限定 5 个）：
- `runner.py`：`RUN_ID: <id>` stdout 行（flush，Job setup 前输出）+ main() 构造 cli_args 传 run_job + finally 传 exit_code 给 summary
- `framework/common/run_meta.py`：**新增**，写 `artifacts/<run_id>/run_meta.json`，失败仅 warning 不中断
- `framework/common/run_summary.py`：summary.json 增补 `env_name/git_ref/host/exit_code`，旧字段零改动
- `framework/common/artifacts.py`：`prune_artifact_runs` 改 no-op + deprecation warning（清理权移交新项目）
- `framework/common/log_config.py`：仅 docstring 补充（FileHandler 本已有 utf-8）

**未动**：scripts/、library/、framework/firebox/、framework/fccm/、utils/。当前分支 feat/webui-multiuser。

## 二、CodeBuddy 任务清单（按序执行）

### P0 编译验证（最高优先——静态审查零运行，这是最大的风险敞口）

```bash
cd /d/RunnerConsole
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m compileall app        # 必须零错误
.venv/Scripts/python -c "import app.main"     # import 链验证（会因无 config/DB 报配置错，属预期；看是否 NameError/ImportError）
```

发现语法/import/签名错误 → 修复（修复原则：以 schema.sql 和 mock-data.js 的契约为准，改动最小化）。
另跑一次全仓检查：`grep -rn "prune_artifact_runs" D:/UIAutomation --include=*.py`（排除 artifacts.py 本体），确认 no-op 不会炸调用方。

> **P0 执行结果（2026-10-15，CodeBuddy 追加）**
>
> - 环境：系统 Python 3.10 不满足 ≥3.11 要求，改用本机 py 启动器默认的 **Python 3.14.7** 建 `.venv`，依赖安装成功（fastapi 0.143.1 / pydantic 2.14.1 / uvicorn 0.54.0 / PyMySQL 1.2.3 / DBUtils 3.2.0）。
> - `compileall app`：**零错误**。
> - `import app.main`：**通过**（无 NameError/ImportError，也未触发配置报错——config 为惰性加载）。
> - 追加验证：实际调用 `create_app()` 构造 FastAPI 实例 + 生成完整 OpenAPI schema：**31 paths / 37 operations 全部可解析**，路由挂载齐全（auth/loops/runs/cases/env/uploads/admin/stats/status/files/SSE/config）。注：fastapi 0.143 的 `include_router` 在 app.routes 里表现为 `_IncludedRouter` 懒加载对象，属新版正常行为。
> - `prune_artifact_runs` 调用方检查：D:/UIAutomation 全仓仅 artifacts.py 本体（定义 + `__all__` 导出）匹配，**无任何调用方**，no-op 退役安全。
> - **修复数：0**。静态审查质量超预期，未暴露任何 import/签名不一致。
> - 改动文件：无（仅新增 `.venv/`，未入 git）。

### P1 MySQL 安装与建库

```sql
CREATE DATABASE runner_console CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'runner'@'localhost' IDENTIFIED BY '<密码>';
GRANT ALL PRIVILEGES ON runner_console.* TO 'runner'@'localhost';
```

```bash
cd /d/RunnerConsole
copy config.example.toml config.toml   # 填 [database]、[paths]（workdir=D:/UIAutomation）、[auth] admins=[yjwu]、[gitlab]
.venv/Scripts/python -m app.db.migrate --config config.toml    # applied V1__init；重跑应 up to date
```

> **P1 执行结果（2026-10-15，CodeBuddy 追加）**
>
> - MySQL80 服务已由用户自建并 RUNNING（8.0.46，3306 监听）；`runner@localhost` 可连，`runner_console` 库已建（utf8mb4）。
> - `config.toml` 已创建（不入 git）：database=runner/password；paths.workdir=D:/UIAutomation、artifacts_root=D:/UIAutomation/artifacts（runner 现有产物根）；**auth_mode="local"**（用户无 GitLab，用 GitHub——gitlab 登录分支不启用，admins=["yjwu"]，首次登录自动注册提权）；server.port=8765。
> - **migrate 首跑暴露 1 个 DDL 错误并已修复**：`artifact_files.uk_artifact_files_run_relpath (run_id, relpath)` 在 utf8mb4 下键长 4192B > 3072B 上限（relpath VARCHAR(1024) 参与索引）。修法：唯一键改前缀 `(run_id, relpath(700))`（2896B，安全线内），**列宽 VARCHAR(1024) 与存储契约不变**，ingest 是先删后插、唯一键仅兜底，前缀唯一对实际路径无影响。已同步修 `schema.sql` 与 `migrations/V1__init.sql` 两处（各 1 行 + 注释）。首跑中途 DDL 隐式提交留下 11 张表无版本记录，靠 CREATE TABLE IF NOT EXISTS 幂等语义补齐，无需人工清理。
> - 复跑 migrate：`applied V1__init` → 重跑 `schema already up to date`，幂等 ✅。终态 14 表（13 业务表 + schema_migrations），settings 种子数据（retain_count=50 / retain_days=30）就位，索引已验证生效。
> - 改动文件：`app/db/schema.sql`、`app/db/migrations/V1__init.sql`（各 1 行索引修复）；新增 `config.toml`。
> - 遗留：P4 建仓目标改为 **GitHub**（用户无 GitLab）：https://github.com/1874561771/runner-console-.git；push 凭据届时单独处理，token 不入库不入档。

### P2 后端冒烟（M3）

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8765
```

- 启动日志顺序：`db pool ready` → `job manager ready` → `startup retention done`（近似文案，看 main.py lifespan）
- `curl http://127.0.0.1:8765/api/me` → 401
- 登录 → 建环境 → POST /api/run（repeat=2, headless=true）→ /api/loops 出现 → iteration 结束后 /api/runs 有数据、runs/cases/artifact_files 表有行
- `curl -N -b cookie "http://127.0.0.1:8765/api/loops/<loop_id>/console"` → snapshot → append* → end
- 杀进程重启 → 原 running loop 被 recover_orphans 置 stopped + audit 有 `loop.recovered`
- 冒烟细节脚本：T7 报告里的 curl 清单（登录/401/envs/uploads/force-release/admin 全套）

**联调期已知风险点**（多 agent 并行开发，重点盯）：
1. dao 函数签名与 routes 调用不一致（T7 是对着各 dao 的"报告签名"写的，个别地方可能漂移——报 KeyError/TypeError 就是对齐问题）
2. loop 关联 jobs JOIN runs 的 SQL（T7 自写口径 `_RUNS`，与 schema ENUM 严格核对）
3. frontend/js/main.js 被 T7 改过 1 行（login 响应兼容），不影响 mock

> **P2 执行结果（2026-10-15，CodeBuddy 追加）**
>
> ### ⚠️ 事故报告：worktree 清理穿透 junction，误删 D:/UIAutomation/artifacts 旧产物
>
> - **现象**：首次冒烟 run 后，`D:/UIAutomation/artifacts/` 被清空（含 2026-09-28 的至少 5 个旧 run 目录，`ls | head -5` 时所见为 20260928140647/1048/1420/44720/5154，实际数量以用户记忆为准）。直接删除，无回收站，本地无备份则不可恢复。
> - **根因**（受控实验复现证实）：`git_worktree.remove_worktree` 先跑 `git worktree remove --force`，而 worktree 内的 `artifacts` 是指向 `config.paths.artifacts_root` 的 **junction**（`link_artifacts` 创建）。**git 的递归删除会穿透 junction 清空目标目录**；Python 3.12+ 的 `shutil.rmtree` 有 junction 防护但 git 没有。
> - **连带影响**：`_one_iteration` 中 remove_worktree 在 ingest 之前执行（loop_runner.py:346 vs :354），首轮 run 的 summary.json 被误删 → runs 行记 `summary.json missing`。
> - **修复**（git_worktree.py）：remove_worktree 在调 git 前先检测并摘除 `artifacts` junction/symlink（新增 `_is_junction` + `_unlink_link`）。受控回归实验：修复前目标被清空、修复后目标完好 ✅。
> - **教训**：Windows 上凡 git 操作范围（add/remove/clean）内有指向共享目录的 junction 都有此风险；后续任何在 worktree 内建链接的代码都要保证"先摘链接，再交 git"。
>
> ### 冒烟验收（修复后第二轮 + 崩溃恢复）
>
> - lifespan 顺序 ✅：`db pool ready` → `job manager ready` → `startup retention done`。注：原代码在 `uvicorn app.main:app` 方式下 `runnerconsole` logger 无 handler，INFO 全部丢弃——已在 main.py 模块级补 `logging.basicConfig`（1 处）。
> - `/api/me` 未登录 → 401 `{detail, error}` ✅
> - **登录链路（本轮新改的管理员建号制）**：yjwu（admins 名单）首登自举 admin ✅；未知用户 → 401「账号不存在，请联系管理员创建」✅；`POST /api/admin/users` 建号（自动生成口令一次性返回）✅；新用户登录 ✅；非 admin 访问 admin 接口 → 403 ✅
> - 建环境 → `POST /api/run`（smoke.txt, repeat=1, headless）→ loop done，RUN_ID 行捕获成功（契约优先路径，未走兜底）✅
> - ingest 全链路 ✅：runs（含 summary 新契约字段 env_name/git_ref）+ cases + case_failures + artifact_files（4 文件，artifacts_by_kind 聚合正确）；产物正确落在 artifacts_root 且 worktree 清理后仍在
> - run_meta.json 缺失 = 预期（worktree 从 HEAD 检出，runner 契约改动未提交；M2 设备回归后 commit 才生效）
> - SSE `/api/loops/<id>/console` ✅：snapshot{offset,text} 事件格式正确
> - 崩溃恢复 ✅：无限循环运行中 kill 进程 → 重启 → `orphan loop ... recovered: no live lock holder, set to stopped` + audit `loop.recovered` ✅
> - 本轮改动文件：`app/core/git_worktree.py`（junction 修复）、`app/main.py`（logging）；另含用户要求的登录建号制改动（见下方独立小节）。
> - 剩余：P3 前端走查、上传/force-release/admin settings 等次要接口未逐一 curl（前端走查会覆盖）。

### P3 前端走查（M4）

浏览器 `http://127.0.0.1:8765/`（真实后端）+ `python -m http.server 8080` 开 `frontend/?mock=1`（对照用）。
对照 Ardot 三屏（文件 736602918319197）：运行台渐进披露表单 → 发起任务 → 任务中心行点击 Inspector → 控制台 SSE 滚动 → 看板统计。1366/1920 两档宽度。

> **材料区改造（2026-10-16，用户反馈，CodeBuddy 追加）**
>
> 1. job/case log 不再跳转：点击条目在运行台内嵌展开深色终端风格查看器（同时只展开一个，再点收起/点另一条切换），懒加载 /runs/<run_id>/<relpath>，超 5000 行截断提示下载原文件。
> 2. **step 高亮**（按 runner 侧 ui_automation.step 日志格式）：`START` 行橙底左条、`PASS` 绿、`FAIL`/`[ERROR]`/Traceback 红（异常块红背景）、`Saved screenshot` 蓝色、`=== StepN ===`（Job setup）与 CASE/RESULT/duration 结构行灰色加粗。
> 3. 配置/支持包/汇总 JSON/运行元数据 → 直接下载；summary.html → 新窗口渲染。
> 4. 截图：缩略图网格（128×80 裁切），点击弹层放大（深色遮罩 + 原图），**点遮罩空白处关闭**（点图片本身不关）。
> - 验证数据：手工构造符合 runner 契约的演示 run（20261016123000，含 2 step pass / 1 fail / 2 截图）走 ingest 真实入库，端到端全部通过。

> **运行台交互重构（2026-10-16，用户实测 6 项反馈，CodeBuddy 追加）**
>
> | # | 反馈 | 处理 |
> |---|---|---|
> | 1 | RUN 按钮在右上角，不顺手 | 移到左侧配置卡底部整行（命令预览下方） |
> | 2 | 切页签后 console 断流 | 根因：render 每次重置 `state.tab="overview"` 且只绑定 running loop。改为模块级 state 保留 loop 绑定与页签；切回自动重开 SSE（快照续传后继续追加）。端到端实测：切走 2133 字符 → 切回 6703 → 3s 后 7062（流恢复）✅ |
> | 3 | 任务中心「在运行台打开」看不到详情/材料 | 根因：tasks.js 早已跳 `#/console?loop=<id>` 但 console.js 从未解析该参数。已解析并绑定指定 loop；右栏新增「工件」页签（Job 日志/Case 日志/截图/汇总页分组，带大小与下载链接，走 /api/runs/<id>/artifacts + /runs/<id>/<relpath>） |
> | 4 | 点「最近一次运行」跳任务中心不合理 | 空态按钮删除；运行台默认绑定最近一条任务直接显示详情（优先 running），不再跳走 |
> | 5 | 运行台加载慢 | /api/config 的分支缓存 60s 过期后首访同步 fetch 要 1.8-2s。改 stale-while-revalidate：过期先返回旧数据、后台线程刷新（旧数据最长兜底 10 分钟）。实测稳定 10ms（仅服务冷启动首跑 1.9s） |
> | 6 | 「配置下方最近 job 列表 + 点击右侧看详情」设计丢失 | 已恢复：配置卡下方新增「最近任务」卡（最近 8 条，徽标/环境/目标/owner，当前绑定项高亮），点击即 showLoop(id) 右侧刷新；发起运行/URL 进入也走同一入口 |
>
> - 顺带修复：`prepare_worktree` 原来每轮 iteration 都 `git fetch`（timeout 90s）——HEAD 场景（默认）已跳过，指定远端分支才 fetch 且降为 30s。此前无限循环轮间隙会被 fetch 卡住、STOP 响应延迟几十秒，实测已消除。
> - 右栏详情区加 `position: sticky`（滚动左列时右侧详情保持可见）。
> - 改动文件：`frontend/js/views/console.js`（主要）、`frontend/css/console.css`、`app/core/git_worktree.py`。

> **P3 执行结果（2026-10-15，CodeBuddy 追加）**
>
> - 走查方式：Python playwright（headless Chromium）登录真实后端逐屏截图（1366 宽）：登录页 / 运行台 / 高级展开态 / Pause on fail 选中态 / 任务中心 / 数据看板，全部渲染正常。
> - **运行台执行区按 Ardot 设计稿重做**（用户反馈实际 UI 与设计稿不符）：
>   - 重复次数改为 `× 3` 前缀窄框，与"无限循环"开关同行右对齐（原为 label+宽输入框左对齐）；
>   - Pause on fail 勾选后整行浅红高亮 + 文字强调（CSS `:has(:checked)`）；
>   - "高级"改为整行折叠条「高级 · 固件 Branch / Build ›」，箭头旋转动效；
>   - 命令预览增加「命令预览」小标签。
>   - 改动：`frontend/js/views/console.js`（标记 + 折叠逻辑）、`frontend/css/console.css`（样式重写执行区）。
> - **登录页默认页签改本地账号**（用户无法登录的根因：默认 GitLab PAT 页签而部署是 local 模式，且 /api/config 需登录后才能拿 auth_mode，前端无法自动感知）：`main.js` loginMode 默认 "local"、index.html 默认激活本地页签 + 用户名/密码框默认可见。
> - **修复 /api/config 慢（2-3s → 30ms）**：根因是 list_branches 每次渲染都 `git fetch --prune origin`（内网 GitLab 数秒）。`git_worktree.py` 加 60s TTL 缓存 + fetch 超时 60s→8s；代价是切分支后分支列表最多延迟 60s。
> - 其余屏（任务中心 Inspector 列表、看板统计卡/趋势/失败 TOP/iteration 列表）用真实冒烟数据验证通过；mock 模式（?mock=1）未再单独走查（此前 T12 已验）。
> - 改动文件：`frontend/js/views/console.js`、`frontend/css/console.css`、`frontend/js/main.js`、`frontend/index.html`、`app/core/git_worktree.py`（缓存）。
> - 遗留：1920 宽度未截图（布局为响应式 grid，风险低）；管理员创建用户等 admin UI 走查通过（P2 冒烟 + 用户实测）。
> - **修正（用户反馈）**：固件 branch 下拉错用了 runner 仓库 git 分支列表（console.js:597 复用 state.config.branches）。语义澄清：该 branch 是 firebox 固件 build 的分支，Job setup 按它下载 build 供 firebox 升降级（runner --branch），形如 utm-2026_2，runner 侧无候选列表接口。已改为自由文本输入（placeholder「如 utm-2026_2（留空不指定）」），build 输入框保持「填了 branch 才解禁」联动；命令预览拼接验证正确（--branch utm-2026_2 --build 733385）。

### P4 GitLab 建仓

```bash
cd /d/RunnerConsole
git init && git add -A && git commit -m "feat: Runner Console v1 (independent project, MySQL, SSE console)"
git remote add origin http://gitlab.wgti.net/<组>/runner-console.git   # 先在 GitLab 网页建项目
git push -u origin master    # 仅 HTTP 可用，HTTPS 会超时
```

> **P4 执行结果（2026-10-15，CodeBuddy 追加）**
>
> - 建仓目标改为 **GitHub**（用户无 GitLab）：https://github.com/1874561771/runner-console-.git
> - `.gitignore` 新建：`.venv/`、`config.toml`（含 DB 密码）、`data/`、`data_*.log`、`__pycache__/`、IDE 杂物。提交前敏感文件检查通过。
> - `git init -b main` → commit `3ae8b22`（69 文件）→ push 成功（`main -> main`）。fine-grained PAT 仅用于 push 命令本身，未写入 remote URL / 任何文件；**已提醒用户 push 完成后 revoke 该 token**。
> - 备注：前两次 push 403/404 是 token 的 Repository access 未包含该仓库 + Contents 只读，用户在 GitHub 上补权限后成功。
> - 后续正常使用 `git push origin main` 即可（remote 存的是干净 URL，无凭据；下次 push 时 git 会提示输入凭据或由 Windows 凭据管理器接管）。

### P5 原仓处置（等新服务稳定一周后再做，勿提前）

```bash
cd /d/UIAutomation
# 1. runner 契约改动单独提交（不含任何 webui/ 内容——分支纪律）
git add runner.py framework/common/run_meta.py framework/common/run_summary.py framework/common/artifacts.py framework/common/log_config.py
git commit -m "feat: runner contract for Runner Console (RUN_ID line, run_meta.json, summary ext fields)"
# 2. webui 空壳化 + 归档 tag
rm webui/*.py webui/index.html webui/favicon.svg webui/start_server.bat
echo "Migrated to Runner Console: gitlab.wgti.net/<组>/runner-console" > webui/README.md
git add -A && git commit -m "chore: archive webui (moved to RunnerConsole)"
git tag webui-archive && git push origin webui-archive
```

### 需要用户参与的节点

- **M2 设备回归（P0/P1 之后随时可做）**：真机跑 smoke，验证 RUN_ID 行/run_meta.json/summary 新字段/旧 CLI 不变/旧 webui 兼容。命令与观察点见 `DEPLOY.md` §3。此步是"runner 契约改动提交"的门槛——**P5 第 1 步 commit 前必须完成**。

## 三、关键契约速查

| 契约 | 值 |
|---|---|
| run_id 格式 | `YYYYMMDDHHMMSS[_N]`（VARCHAR(24)） |
| loop_id 格式 | `YYYYMMDDHHMMSS-hex6` 21 字符（VARCHAR(24)） |
| exit code | 0 全 pass / 1 有 case fail / 2 仅 Job setup 失败 / 3 case setup 或 teardown broken；"没起来"= Popen 异常或无 RUN_ID 行 |
| loops.status | running/done/stopped/failed（原 paused→failed，原因在 stop_reason） |
| jobs.status | running/pass/fail/setup_fail/broken/stopped（原 incomplete→broken） |
| runs.outcome | pass/fail/broken/setup_fail/unknown |
| SSE 事件 | snapshot{offset,text} → append(文本块，id=byte offset) → reset → end{status}；Last-Event-ID 续传 |
| audit actions | loop.start/loop.stop/loop.recovered/env.lock.force-release/env.grant(.revoke)/retention.run/settings.update/user.role/user.reset/register/login/logout/upload.create |
| API 错误体 | {detail, error}（前端读 data.error） |

## 四、禁止事项

1. runner 侧改动只许改 runner.py + framework/common/，scripts/library/framework/firebox 一行不动。
2. 原仓 runner 契约 commit 严禁混入 webui/ 文件（用户分支纪律）。
3. 不建 locks 数据库表——.runner.lock 文件契约是刻意的（CLI 直跑 runner 也依赖）。
4. DB 不可用时服务启动即退出，不要加降级模式。
5. artifacts 清理只认 core/retention.py，runner 侧 prune 已退役，别往回加。
