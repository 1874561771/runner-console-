-- =====================================================================
-- RunnerConsole 权威 DDL（MySQL 8）
-- 引擎 InnoDB / 字符集 utf8mb4 / 排序 utf8mb4_0900_ai_ci / 时间 DATETIME(3)
--
-- 本文件与 app/db/migrations/V1__init.sql 内容一致（初始版本）。
-- 后续 schema 变更：新增 migrations/V2__xxx.sql，不要改动本文件已发布部分。
--
-- 相对原 SQLite schema（webui/db.py L73-176）的语义差异：
--   * loops.status：原 running/done/stopped/paused 收敛为 running/done/stopped/failed。
--     paused 特殊语义说明：原代码 jobs.py LoopRunner._cleanup() 中，
--     pause_on_fail 开启且最后一次迭代 fail/setup_fail 时置 paused——此时循环
--     子进程已退出、环境锁已释放，仅是"因失败提前中止"而非可恢复的暂停态。
--     迁移时映射为 failed，完整原因保留在 stop_reason（原文 "pause on fail ..."）。
--   * jobs.status：原 _job_status() 可能产生 incomplete（进程无返回码，如被杀），
--     收敛为 stopped；新增 broken（run 产物/汇总损坏）。
--   * jobs.passed / jobs.total 移至 runs 表（jobs 不再冗余存计数）。
--   * sessions.token 改名 token_hash：只存明文 token 的 sha256 hex，明文不落库。
--   * settings.key 改名 setting_key（key 是 MySQL 保留字）。
--   * loops.id / jobs.loop_id / runs.loop_id 用 VARCHAR(24)：沿用原
--     "YYYYMMDDHHMMSS-hex6"（21 字符）格式，保留时间语义，LoopRunner 生成逻辑不变。
--   * 新增表：env_grants、runs、cases、case_failures、artifact_files。
-- =====================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------
-- 迁移版本记录（migrate.py 维护）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT          NOT NULL,
    applied_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- users：迁移自原表，字段一一对应
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    gitlab_id   BIGINT       NULL,
    username    VARCHAR(64)  NOT NULL,
    name        VARCHAR(128) NULL,
    email       VARCHAR(128) NULL,
    role        ENUM('admin','user') NOT NULL DEFAULT 'user',
    created_at  DATETIME(3)  NOT NULL,
    last_login  DATETIME(3)  NULL,
    token_hash  CHAR(64)     NULL COMMENT '本地登录 PBKDF2 哈希（hex，64 字符）',
    token_salt  CHAR(32)     NULL COMMENT 'PBKDF2 盐（hex，32 字符）',
    auth_source ENUM('gitlab','local') NOT NULL DEFAULT 'local',
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_gitlab_id (gitlab_id),
    UNIQUE KEY uk_users_username (username),
    KEY idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- sessions：token_hash 为主键（明文 token 不落库，存 sha256 hex）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  CHAR(64)     NOT NULL,
    user_id     BIGINT       NOT NULL,
    created_at  DATETIME(3)  NOT NULL,
    expires_at  DATETIME(3)  NOT NULL,
    PRIMARY KEY (token_hash),
    KEY idx_sessions_expires_at (expires_at),
    CONSTRAINT fk_sessions_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- environments：id 沿用原 hex12 约定
-- owner 引用不带 ON DELETE（默认 RESTRICT）：删除用户前须先清理其数据，
-- 防止误删账号连带级联清掉环境与全部运行记录。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS environments (
    id          CHAR(12)     NOT NULL,
    owner_id    BIGINT       NOT NULL,
    name        VARCHAR(128) NOT NULL,
    relpath     VARCHAR(512) NOT NULL,
    created_at  DATETIME(3)  NOT NULL,
    updated_at  DATETIME(3)  NOT NULL,
    disabled    TINYINT(1)   NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_environments_owner_id (owner_id),
    CONSTRAINT fk_environments_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- env_grants（新增）：环境级授权，viewer 只读 / operator 可执行
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS env_grants (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    env_id      CHAR(12)     NOT NULL,
    user_id     BIGINT       NOT NULL,
    level       ENUM('viewer','operator') NOT NULL DEFAULT 'operator',
    granted_by  BIGINT       NULL,
    created_at  DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_env_grants_env_user (env_id, user_id),
    CONSTRAINT fk_env_grants_env
        FOREIGN KEY (env_id) REFERENCES environments (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_env_grants_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- uploads：迁移自原表（kind suite=测试套件包 script=脚本包）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uploads (
    id          CHAR(12)     NOT NULL,
    owner_id    BIGINT       NOT NULL,
    kind        ENUM('suite','script') NOT NULL,
    name        VARCHAR(255) NOT NULL,
    relpath     VARCHAR(512) NOT NULL,
    created_at  DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_uploads_owner_kind (owner_id, kind),
    CONSTRAINT fk_uploads_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- loops：迁移自原表
-- repeat_total：0=无限循环；status 见文件头收敛说明（paused→failed）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loops (
    id              VARCHAR(24)  NOT NULL,
    owner_id        BIGINT       NOT NULL,
    env_id          CHAR(12)     NULL,
    product         VARCHAR(16)  NULL,
    suite           VARCHAR(255) NULL,
    test            VARCHAR(255) NULL,
    git_ref         VARCHAR(128) NULL,
    source          ENUM('repo','upload') NOT NULL DEFAULT 'repo',
    firmware_branch VARCHAR(128) NULL,
    firmware_build  VARCHAR(64)  NULL,
    headless        TINYINT(1)   NOT NULL DEFAULT 0,
    pause_on_fail   TINYINT(1)   NOT NULL DEFAULT 0,
    repeat_total    INT          NOT NULL DEFAULT 1 COMMENT '0=无限',
    status          ENUM('running','done','stopped','failed') NOT NULL DEFAULT 'running',
    created_at      DATETIME(3)  NOT NULL,
    ended_at        DATETIME(3)  NULL,
    stop_reason     VARCHAR(255) NULL,
    command         TEXT         NULL,
    PRIMARY KEY (id),
    KEY idx_loops_status (status),
    KEY idx_loops_owner_id (owner_id),
    CONSTRAINT fk_loops_owner
        FOREIGN KEY (owner_id) REFERENCES users (id),
    CONSTRAINT fk_loops_env
        FOREIGN KEY (env_id) REFERENCES environments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- jobs：迁移自原表；passed/total 移至 runs 表（不在此重复）
-- status 收敛说明见文件头（incomplete→stopped，新增 broken）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id               CHAR(12)     NOT NULL,
    loop_id          VARCHAR(24)  NOT NULL,
    owner_id         BIGINT       NULL,
    env_id           CHAR(12)     NULL,
    run_id           VARCHAR(24)  NULL COMMENT '产物目录 run id，YYYYMMDDHHMMSS[_n]',
    iteration        INT          NULL,
    status           ENUM('running','pass','fail','setup_fail','broken','stopped')
                     NOT NULL DEFAULT 'running',
    exit_code        INT          NULL,
    job_duration_s   DOUBLE       NULL,
    started_at       DATETIME(3)  NOT NULL,
    ended_at         DATETIME(3)  NULL,
    failed_reason    TEXT         NULL,
    git_ref          VARCHAR(128) NULL,
    job_setup_failed TINYINT(1)   NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_jobs_loop_iteration (loop_id, iteration),
    KEY idx_jobs_status_started_at (status, started_at),
    KEY idx_jobs_run_id (run_id),
    CONSTRAINT fk_jobs_loop
        FOREIGN KEY (loop_id) REFERENCES loops (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_jobs_owner
        FOREIGN KEY (owner_id) REFERENCES users (id),
    CONSTRAINT fk_jobs_env
        FOREIGN KEY (env_id) REFERENCES environments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- runs（新增）：一次执行（run_id）的汇总解析结果，由产物 summary.json 摄取
-- outcome=unknown：summary 缺失或不可解析时的兜底
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id            VARCHAR(24)  NOT NULL,
    job_id            CHAR(12)     NULL,
    loop_id           VARCHAR(24)  NULL,
    product           VARCHAR(16)  NULL,
    dut_model         VARCHAR(128) NULL,
    dut_version       VARCHAR(128) NULL,
    outcome           ENUM('pass','fail','broken','setup_fail','unknown') NOT NULL DEFAULT 'unknown',
    passed            INT          NOT NULL DEFAULT 0,
    failed            INT          NOT NULL DEFAULT 0,
    broken            INT          NOT NULL DEFAULT 0,
    total             INT          NOT NULL DEFAULT 0,
    pass_rate         DOUBLE       NOT NULL DEFAULT 0,
    failed_reason     TEXT         NULL,
    job_duration_s    DOUBLE       NULL,
    branch            VARCHAR(128) NULL,
    build             VARCHAR(64)  NULL,
    env_name          VARCHAR(128) NULL,
    git_ref           VARCHAR(128) NULL,
    host              VARCHAR(128) NULL,
    exit_code         INT          NULL,
    artifacts_relpath VARCHAR(512) NOT NULL,
    started_at        DATETIME(3)  NOT NULL,
    ended_at          DATETIME(3)  NULL,
    ingested_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (run_id),
    KEY idx_runs_job_id (job_id),
    KEY idx_runs_outcome_ended_at (outcome, ended_at),
    KEY idx_runs_loop_id (loop_id),
    CONSTRAINT fk_runs_job
        FOREIGN KEY (job_id) REFERENCES jobs (id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- cases（新增）：run 内的用例级结果
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cases (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    run_id        VARCHAR(24)  NOT NULL,
    name          VARCHAR(255) NOT NULL,
    seq           INT          NOT NULL DEFAULT 0 COMMENT '同名用例多次出现的序号',
    status        ENUM('pass','fail','broken','skipped') NOT NULL,
    duration_s    DOUBLE       NULL,
    message       TEXT         NULL,
    case_relpath  VARCHAR(512) NULL COMMENT '用例详情页相对路径',
    PRIMARY KEY (id),
    UNIQUE KEY uk_cases_run_name_seq (run_id, name, seq),
    KEY idx_cases_run_status (run_id, status),
    CONSTRAINT fk_cases_run
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- case_failures（新增）：run 内失败片段（setup/teardown/主流程）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS case_failures (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    run_id       VARCHAR(24)  NOT NULL,
    case_name    VARCHAR(255) NULL,
    kind         ENUM('job_setup','case_setup','main','case_teardown') NOT NULL,
    message      TEXT         NOT NULL,
    log_relpath  VARCHAR(512) NULL COMMENT '失败日志文件相对路径',
    PRIMARY KEY (id),
    KEY idx_case_failures_run_id (run_id),
    CONSTRAINT fk_case_failures_run
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- artifact_files（新增）：run 产物文件清单（删除 run 时同步清理物理文件）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS artifact_files (
    id         BIGINT        NOT NULL AUTO_INCREMENT,
    run_id     VARCHAR(24)   NOT NULL,
    relpath    VARCHAR(1024) NOT NULL,
    kind       ENUM('job_log','summary_html','summary_json','run_meta','case_log',
                    'screenshot','support_tgz','config','other') NOT NULL DEFAULT 'other',
    size_bytes BIGINT        NOT NULL DEFAULT 0,
    case_name  VARCHAR(255)  NULL,
    PRIMARY KEY (id),
    -- relpath 全列索引在 utf8mb4 下超 3072 字节键长上限（4192B），改用 700 字符前缀
    UNIQUE KEY uk_artifact_files_run_relpath (run_id, relpath(700)),
    KEY idx_artifact_files_run_kind (run_id, kind),
    CONSTRAINT fk_artifact_files_run
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- audit：迁移自原表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit (
    id         BIGINT       NOT NULL AUTO_INCREMENT,
    actor_id   BIGINT       NULL,
    action     VARCHAR(64)  NOT NULL,
    detail     TEXT         NULL,
    created_at DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_audit_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------
-- settings：原 key/value 改名（key 是 MySQL 保留字）
-- 预置保留策略默认值；ON DUPLICATE KEY UPDATE 为 no-op——不覆盖已调整过的值
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    setting_key   VARCHAR(64) NOT NULL,
    setting_value TEXT        NOT NULL,
    PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO settings (setting_key, setting_value) VALUES
    ('retain_count', '50'),
    ('retain_days',  '30')
ON DUPLICATE KEY UPDATE setting_key = setting_key;
