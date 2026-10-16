-- V1__init.sql — RunnerConsole 初始 schema（MySQL 8）
-- 内容与 app/db/schema.sql（权威 DDL）保持一致。
-- 迁移历史与 SQLite 版（webui/db.py）的字段对应关系、status 收敛说明
-- 见 schema.sql 文件头注释，此处不再重复。
-- 后续变更请新增 V2__xxx.sql 等版本文件，由 app/db/migrate.py 逐版本执行。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT          NOT NULL,
    applied_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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

CREATE TABLE IF NOT EXISTS audit (
    id         BIGINT       NOT NULL AUTO_INCREMENT,
    actor_id   BIGINT       NULL,
    action     VARCHAR(64)  NOT NULL,
    detail     TEXT         NULL,
    created_at DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_audit_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS settings (
    setting_key   VARCHAR(64) NOT NULL,
    setting_value TEXT        NOT NULL,
    PRIMARY KEY (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO settings (setting_key, setting_value) VALUES
    ('retain_count', '50'),
    ('retain_days',  '30')
ON DUPLICATE KEY UPDATE setting_key = setting_key;
