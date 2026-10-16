"""RunnerConsole 执行引擎核心（迁移重构自 UIAutomation/webui）。

模块清单：
* env_lock      —— 每环境 .runner.lock（O_CREAT|O_EXCL + pid 判活）
* git_worktree  —— git worktree 准备/清理/分支列表/overlay 拷贝
* env_files     —— firebox.env 解析 / 脱敏 / 缺键检查
* loop_runner   —— LoopRunner：单环境循环执行器
* job_manager   —— JobManager 单例：loop 注册表、启停、孤儿回收

依赖方向约束：core 只 import app.config / app.db.dao（含 app.db.pool），
绝不 import app.api；dao 层也绝不 import core。
"""
