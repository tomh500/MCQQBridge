ALTER TABLE mcqq_daily.daily_waifu_draws
  ADD COLUMN swapped TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN draw_token VARCHAR(64) NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS mcqq_daily.daily_waifu_resets (
  event VARCHAR(256) NOT NULL PRIMARY KEY,
  day DATE NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

GRANT SELECT,INSERT,UPDATE,DELETE ON mcqq_daily.daily_waifu_draws TO 'mcqq_daily'@'127.0.0.1';
GRANT SELECT,INSERT ON mcqq_daily.daily_waifu_resets TO 'mcqq_daily'@'127.0.0.1';
