# 部署切换清单（T13 收尾）

> 代码与文件已就绪。以下步骤需要 shell 通道与你的凭证，按顺序执行。

## 0. 一键部署（推荐，新机器 / 实验室部署用）

前提：目标机器已装 **Python 3.11+** 和 **MySQL 8**（Server 本体脚本不代装，
未装时向导会给出指引；`winget install Oracle.MySQL` 或官网 MSI 均可）。

双击项目根目录的 **`install.bat`**，它会自动完成：

1. 建 `.venv` 虚拟环境并安装依赖（首次约 1-2 分钟）
2. 首次运行弹出交互向导 `setup_wizard.py`：
   - 输入 MySQL root 密码 → 自动建库 `runner_console`（utf8mb4）、
     建用户 `runner`（密码可自动生成）、授权
   - 交互确认 runner 仓库路径与管理员用户名 → 生成 `config.toml`
   - 自动执行 schema 迁移（幂等，重跑无害）
3. 启动服务 `0.0.0.0:8765`（局域网内办公室电脑直接访问 `http://<实验室机IP>:8765/`）

日常运行再次双击 `install.bat` 即可（配置已存在则直接迁移 + 启动）。
注意：本脚本窗口开着服务才在跑；要注册为 Windows 后台服务/开机自启，
用 Task Scheduler 配一个开机运行 `install.bat`（最小化）的任务即可。

### 配置文件在哪、有什么

| 文件 | 作用 | 是否入库 |
|---|---|---|
| `config.example.toml` | 配置模板（含每个字段的中文注释） | 入库 |
| `config.toml` | **本机实际配置**：数据库地址/账号密码、runner 仓库路径、产物路径、管理员名单、服务监听地址端口 | **不入库**（含密码，已在 .gitignore） |

数据库连接信息就在 `config.toml` 的 `[database]` 段（host/port/user/password/database）；
数据库本身只建一次（向导或手动 SQL），换机器部署 = 新机器上重跑 `install.bat`。

### 打包成 exe（可选，尚未实施）

可行且影响小（PyInstaller，onedir 形态，需适配 frontend/migrations 资源路径
与 PROJECT_ROOT，约 10 行代码 + 一份 spec）。代价：打包后改前端需重新打包。
建议源码 + install.bat 的方式部署，exe 方式待定后再做。

## 1. 安装 MySQL 8（Windows 本机，手动方式）

1. MySQL 8 Community（zip 版或 MSI 均可），root 密码自定。
2. 建库：
   ```sql
   CREATE DATABASE runner_console CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   CREATE USER 'runner'@'localhost' IDENTIFIED BY '<密码>';
   GRANT ALL PRIVILEGES ON runner_console.* TO 'runner'@'localhost';
   ```
3. 复制 `config.example.toml` → `config.toml`，填 [database] 四项 + [paths]（workdir=D:/UIAutomation、artifacts_root/consoles/uploads/worktrees 路径）+ [auth]（admins=[你的 GitLab 用户名]）+ [gitlab]。

## 2. 编译级验证（shell 恢复后，代码层尚未跑过 py_compile）

```bash
cd /d/RunnerConsole
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m compileall app      # 零语法错误
.venv/Scripts/python -m app.db.migrate --config config.toml   # applied V1__init；重跑应 up to date
```

## 3. M2 设备回归（runner 契约改造的硬门槛，你手动跑）

```bash
cd /d/UIAutomation
.venv/Scripts/python -m runner --product firebox --test scripts/firebox/smoke/firebox_smoke_login.py --headless true
```

观察点：
- stdout 首行 `RUN_ID: 20261015xxxxxx`（Job setup 失败场景也出现）
- `artifacts/<run_id>/run_meta.json` 存在
- `summary.json` 新增 env_name/git_ref/host/exit_code，旧字段不变
- `python -m runner` 旧 CLI 用法完全不变；旧 webui 仍能驱动新 runner（兜底兼容）

## 4. 后端冒烟（M3）

```bash
cd /d/RunnerConsole
.venv/Scripts/python -m uvicorn app.main:app --port 8765
# 登录 → 建环境 → 发 loop(repeat=2) → /api/runs 有数据 →
# curl -N /api/loops/<loop_id>/console 看到 snapshot+append+end →
# 杀进程重启：孤儿 loop 被置 stopped
```

## 5. 前端走查（M4）

浏览器开 `http://127.0.0.1:8765/`，对照 Ardot 三屏（文件 736602918319197）：
- 运行台：渐进披露表单发起一轮任务
- 任务中心：行点击 Inspector → 控制台页签 SSE 实时滚动
- 数据看板：KPI/趋势/失败 Top 与 SQL 直查一致
- 1366 与 1920 宽度无布局破损

## 6. GitLab 建仓 + 推送（需要你的 PAT）

```bash
cd /d/RunnerConsole
git init && git add -A && git commit -m "feat: Runner Console v1 (independent project, MySQL, SSE console)"
# 在 http://gitlab.wgti.net 新建项目 runner-console（仅 HTTP），然后：
git remote add origin http://gitlab.wgti.net/<你的组>/runner-console.git
git push -u origin master
# 建议保护 master，后续改动走 MR
```

## 7. 原仓库处置（切换完成、新服务稳定运行一周后）

```bash
cd /d/UIAutomation
git checkout feat/webui-multiuser   # 或你指定的分支
# runner 侧契约改动（T2）单独提交：
git add runner.py framework/common/run_meta.py framework/common/run_summary.py framework/common/artifacts.py framework/common/log_config.py
git commit -m "feat: runner contract for Runner Console (RUN_ID line, run_meta.json, summary ext fields)"
# webui 空壳化：
rm -rf webui/*.py webui/index.html webui/favicon.svg webui/start_server.bat
# 写 webui/README.md：一行说明「已迁移至 RunnerConsole（gitlab.wgti.net/<组>/runner-console）」
git tag webui-archive && git push origin webui-archive
```

注意：切换期间旧 `webui/server.py` 不再启动（8765 让给新服务）；原仓提交前确认 runner 侧改动不含 webui/ 内容（分支纪律）。
