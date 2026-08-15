CREATE TABLE IF NOT EXISTS stock_basic (
  dm VARCHAR(10) PRIMARY KEY COMMENT '纯数字代码',
  mc VARCHAR(50) COMMENT '名称',
  jys VARCHAR(5) COMMENT '交易所 SZ/SH/BJ',
  ltsz DECIMAL(20,2) COMMENT '流通市值',
  zsz DECIMAL(20,2) COMMENT '总市值',
  pe DECIMAL(10,2) COMMENT '市盈率',
  pb DECIMAL(10,2) COMMENT '市净率',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS daily_kline (
  dm VARCHAR(10) NOT NULL COMMENT '纯数字代码',
  t DATE NOT NULL COMMENT '交易日',
  o DECIMAL(10,2), h DECIMAL(10,2), l DECIMAL(10,2), c DECIMAL(10,2),
  v BIGINT COMMENT '成交量(手)',
  a DECIMAL(20,2) COMMENT '成交额(元)',
  pc DECIMAL(10,2) COMMENT '昨收',
  ma5 DECIMAL(10,2), ma10 DECIMAL(10,2), ma20 DECIMAL(10,2), ma60 DECIMAL(10,2),
  PRIMARY KEY (dm, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS strategy_signal (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  strategy VARCHAR(10) NOT NULL COMMENT 'A/B/C',
  score DECIMAL(10,2),
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  detail TEXT COMMENT 'JSON 信号详情',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_dm_t (dm, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS backtest_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  strategy VARCHAR(10) NOT NULL,
  start_date DATE,
  end_date DATE,
  hold_days INT,
  sample_count INT,
  win_count INT,
  win_rate DECIMAL(5,2),
  avg_return DECIMAL(10,2),
  avg_loss DECIMAL(10,2),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommend_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  t DATE NOT NULL COMMENT '推荐日期',
  dm VARCHAR(10) NOT NULL,
  strategy VARCHAR(10) COMMENT '命中策略',
  score DECIMAL(10,2) COMMENT '综合评分',
  reason TEXT COMMENT '推荐理由',
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  position_pct DECIMAL(5,2) COMMENT '建议仓位',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_t (t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS track_watch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  track_date DATE NOT NULL COMMENT '跟踪日期',
  status VARCHAR(20) DEFAULT '观察中' COMMENT '观察中/达标/不达标',
  entry_price DECIMAL(10,2) COMMENT '建议买入价',
  stop_loss DECIMAL(10,2) COMMENT '止损价',
  current_price DECIMAL(10,2) COMMENT '最新价',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_date (track_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS factor_flag (
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  factor VARCHAR(30) NOT NULL COMMENT '指标名',
  flag TINYINT NOT NULL DEFAULT 0 COMMENT '0/1',
  PRIMARY KEY (dm, t, factor),
  KEY idx_t_factor (t, factor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS combo_rank (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '指标组合，如 macd_golden+gap_up',
  period VARCHAR(10) COMMENT '周期标签 超短/短/中短/中',
  hold_days INT,
  train_win_rate DECIMAL(5,2),
  test_win_rate DECIMAL(5,2),
  train_sample INT,
  test_sample INT,
  train_avg_win DECIMAL(10,2),
  train_avg_loss DECIMAL(10,2),
  test_avg_win DECIMAL(10,2),
  test_avg_loss DECIMAL(10,2),
  train_ratio DECIMAL(10,2),
  test_ratio DECIMAL(10,2),
  train_expectation DECIMAL(10,4),
  test_expectation DECIMAL(10,4),
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS index_kline (
  code VARCHAR(20) NOT NULL COMMENT '指数代码，如000001.SH',
  t DATE NOT NULL,
  o DECIMAL(10,2), h DECIMAL(10,2), l DECIMAL(10,2), c DECIMAL(10,2),
  v BIGINT, a DECIMAL(20,2), pc DECIMAL(10,2),
  ma20 DECIMAL(10,2),
  PRIMARY KEY (code, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS history_replay (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '组合名',
  period VARCHAR(10) COMMENT '周期标签',
  dm VARCHAR(10) COMMENT '股票代码',
  mc VARCHAR(50) COMMENT '股票名称',
  buy_date DATE COMMENT '买入日',
  entry DECIMAL(10,2) COMMENT '买入价',
  stop DECIMAL(10,2) COMMENT '止损价',
  exit_price DECIMAL(10,2) COMMENT '出场价',
  ret DECIMAL(10,2) COMMENT '收益率%',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_combo (combo, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
