-- For MySQL chat history, report delivery state or cache. Memory and command quotas have their own DDL.
CREATE TABLE IF NOT EXISTS mcqq_group_ai_history (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    member_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    message_text MEDIUMTEXT NOT NULL,
    image_path VARCHAR(80) CHARACTER SET ascii,
    display_name VARCHAR(80) NOT NULL,
    created DOUBLE NOT NULL,
    avatar_url TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY mcqq_group_ai_event (event_id),
    KEY mcqq_group_ai_history_group_time (group_id, created, id),
    KEY mcqq_group_ai_history_time (created)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_attachment (
    event_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    data MEDIUMBLOB NOT NULL,
    byte_size INT UNSIGNED NOT NULL,
    created DOUBLE NOT NULL,
    PRIMARY KEY (event_id),
    KEY mcqq_group_ai_attachment_created (created),
    CONSTRAINT mcqq_group_ai_attachment_event FOREIGN KEY (event_id)
      REFERENCES mcqq_group_ai_history (event_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_profile (
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    member_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    name_updated DOUBLE NOT NULL,
    avatar_url TEXT NOT NULL,
    avatar_updated DOUBLE NOT NULL,
    PRIMARY KEY (group_id, member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_daily (
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    day CHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (group_id, day),
    KEY mcqq_group_ai_daily_day (day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_daily_image (
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    day CHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    page SMALLINT UNSIGNED NOT NULL,
    image MEDIUMBLOB NOT NULL,
    PRIMARY KEY (group_id, day, page),
    CONSTRAINT mcqq_group_ai_daily_image_day FOREIGN KEY (group_id, day)
      REFERENCES mcqq_group_ai_daily (group_id, day) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_daily_start (
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    day CHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_ai_cache (
    cache_key BINARY(32) NOT NULL,
    payload MEDIUMBLOB NOT NULL,
    expires DOUBLE NOT NULL,
    PRIMARY KEY (cache_key),
    KEY mcqq_group_ai_cache_expiry (expires)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
