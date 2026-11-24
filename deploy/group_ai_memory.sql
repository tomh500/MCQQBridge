CREATE TABLE IF NOT EXISTS mcqq_group_ai_memory (
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    member_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    digest BINARY(32) NOT NULL,
    summary TEXT NOT NULL,
    embedding JSON NOT NULL,
    created DOUBLE NOT NULL,
    PRIMARY KEY (group_id, member_id, digest),
    KEY mcqq_group_ai_memory_created (group_id, created)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
