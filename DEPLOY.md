# 部署切换清单（T13 收尾）

> 代码与文件已就绪。以下步骤需要 shell 通道与你的凭证，按顺序执行。

## 1. 安装 MySQL 8（Windows 本机）

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
