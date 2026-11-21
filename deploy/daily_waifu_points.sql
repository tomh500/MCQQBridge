-- Select your database before running, then grant these tables to your own bot account.
CREATE TABLE IF NOT EXISTS waifu_accounts (
  subject VARCHAR(260) NOT NULL PRIMARY KEY,
  points INT UNSIGNED NOT NULL DEFAULT 0,
  preference JSON NOT NULL,
  CHECK (points <= 2147483647)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS waifu_rewards (
  subject VARCHAR(260) NOT NULL, day DATE NOT NULL,
  PRIMARY KEY (subject, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS waifu_wishes (
  subject VARCHAR(260) NOT NULL, source_url VARCHAR(256) NOT NULL,
  failures INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (subject, source_url)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS waifu_operations (
  event_id VARCHAR(256) NOT NULL PRIMARY KEY,
  subject VARCHAR(260) NOT NULL, kind VARCHAR(32) NOT NULL,
  result JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
-- Grant SELECT, INSERT, UPDATE on accounts and wishes, and SELECT, INSERT on
-- rewards and operations, to the bot account configured by your deployment.
