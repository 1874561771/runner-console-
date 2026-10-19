-- ---------------------------------------------------------------------
-- V2：定时任务（schedules）+ 保存的套件（saved_suites）
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS schedules (
    id           CHAR(12)     NOT NULL,
    owner_id     BIGINT       NOT NULL,
    name         VARCHAR(128) NOT NULL,
    env_id       VARCHAR(64)  NOT NULL,
    params       TEXT         NOT NULL,              -- RunIn 快照（JSON：env/product/git_ref/cases/suite/repeat/...）
    rule_type    ENUM('daily','once') NOT NULL,
    rule_time    VARCHAR(5)   NOT NULL DEFAULT '',   -- daily 用 'HH:MM'（本机时间）
    run_at       DATETIME(3)  NULL,                  -- once 用
    enabled      TINYINT(1)   NOT NULL DEFAULT 1,
    next_run_at  DATETIME(3)  NULL,
    last_loop_id VARCHAR(64)  NULL,
    last_status  VARCHAR(16)  NULL,                  -- ok | fail | start_error | missed
    last_note    VARCHAR(512) NULL,
    created_at   DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_schedules_due (enabled, next_run_at),
    KEY idx_schedules_owner (owner_id),
    CONSTRAINT fk_schedules_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS saved_suites (
    id         CHAR(12)     NOT NULL,
    owner_id   BIGINT       NOT NULL,
    name       VARCHAR(128) NOT NULL,
    product    VARCHAR(32)  NOT NULL DEFAULT 'firebox',
    cases      TEXT         NOT NULL,               -- case 脚本路径集合（JSON 数组）
    created_at DATETIME(3)  NOT NULL,
    updated_at DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_saved_suites_owner (owner_id),
    CONSTRAINT fk_saved_suites_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
