CREATE TABLE IF NOT EXISTS scan_realtime (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    dm VARCHAR(10) NOT NULL,
    mc VARCHAR(50),
    scan_time DATETIME NOT NULL COMMENT '扫描时间',
    current_price DECIMAL(10,2) COMMENT '当前价',
    prev_close DECIMAL(10,2) COMMENT '昨收',
    pct_change DECIMAL(8,2) COMMENT '涨跌幅%',
    prev_breakout_date DATE COMMENT '前次突破日',
    prev_breakout_close DECIMAL(10,2) COMMENT '前次突破日收盘',
    prev_breakout_high DECIMAL(10,2) COMMENT '前次突破日最高',
    prev_high_4d DECIMAL(10,2) COMMENT '过去4天最高',
    stop_loss DECIMAL(10,2) COMMENT '建议止损价',
    detail TEXT COMMENT 'JSON 明细',
    UNIQUE KEY uq_dm_scan (dm, scan_time),
    KEY idx_scan_time (scan_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='14:30 实时扫描结果';