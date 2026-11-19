CREATE TABLE IF NOT EXISTS run_templates (
    id         CHAR(12)     NOT NULL,
    owner_id   BIGINT       NOT NULL,
    name       VARCHAR(128) NOT NULL,
    params     TEXT         NOT NULL,
    created_at DATETIME(3)  NOT NULL,
    updated_at DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_run_templates_owner (owner_id),
    CONSTRAINT fk_run_templates_owner
        FOREIGN KEY (owner_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
