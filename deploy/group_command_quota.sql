CREATE TABLE IF NOT EXISTS mcqq_group_command_quota_lock (
    command_name VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (command_name, group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mcqq_group_command_quota (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    command_name VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
    group_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    member_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created DOUBLE NOT NULL,
    PRIMARY KEY (id),
    KEY mcqq_group_command_member (command_name, group_id, member_id, created),
    KEY mcqq_group_command_expiry (command_name, group_id, created)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
