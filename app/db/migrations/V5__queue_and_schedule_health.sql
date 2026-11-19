CREATE TABLE IF NOT EXISTS run_queue (
    id          CHAR(12)     NOT NULL,
    owner_id    BIGINT       NOT NULL,
    env_id      VARCHAR(64)  NOT NULL,
    params      TEXT         NOT NULL,
    status      ENUM('queued','starting','started','cancelled','failed') NOT NULL,
    loop_id     VARCHAR(24)  NULL,
    note        VARCHAR(512) NULL,
    created_at  DATETIME(3)  NOT NULL,
    started_at  DATETIME(3)  NULL,
    PRIMARY KEY (id),
    KEY idx_run_queue_pending (status, created_at),
    KEY idx_run_queue_owner (owner_id),
    CONSTRAINT fk_run_queue_owner FOREIGN KEY (owner_id) REFERENCES users (id),
    CONSTRAINT fk_run_queue_env FOREIGN KEY (env_id) REFERENCES environments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE schedules
    ADD COLUMN failure_streak INT NOT NULL DEFAULT 0 AFTER last_note,
    ADD COLUMN last_run_at DATETIME(3) NULL AFTER failure_streak;
