-- ============================================================
-- 财务数据表结构 (EPro v2)
-- 设计日期: 2026-09-01
-- 数据源: 麦蕊 API 基础证书可用
-- ============================================================

-- 1. stock_basic 扩展（财务快照，每次财报更新覆盖）
-- MySQL 5.7 不支持 IF NOT EXISTS，需要预先检查字段是否存在
-- 这里直接尝试添加，失败忽略（已存在则跳过）
ALTER TABLE stock_basic ADD COLUMN roe_ttm DECIMAL(8,2)     COMMENT 'ROE TTM (%)';
ALTER TABLE stock_basic ADD COLUMN gross_margin DECIMAL(8,2) COMMENT '毛利率 (%)';
ALTER TABLE stock_basic ADD COLUMN net_margin DECIMAL(8,2)   COMMENT '净利率 (%)';
ALTER TABLE stock_basic ADD COLUMN debt_ratio DECIMAL(8,2)   COMMENT '资产负债率 (%)';
ALTER TABLE stock_basic ADD COLUMN pe_ttm DECIMAL(10,2)      COMMENT 'PE TTM';
ALTER TABLE stock_basic ADD COLUMN ps DECIMAL(10,2)          COMMENT 'PS';
ALTER TABLE stock_basic ADD COLUMN pcf DECIMAL(10,2)         COMMENT 'PCF';
ALTER TABLE stock_basic ADD COLUMN rev_yoy DECIMAL(8,2)      COMMENT '营收同比 (%)';
ALTER TABLE stock_basic ADD COLUMN profit_yoy DECIMAL(8,2)   COMMENT '净利润同比 (%)';
ALTER TABLE stock_basic ADD COLUMN eps DECIMAL(10,4)         COMMENT '基本每股收益';
ALTER TABLE stock_basic ADD COLUMN bvps DECIMAL(10,4)        COMMENT '每股净资产';
ALTER TABLE stock_basic ADD COLUMN report_period VARCHAR(10) COMMENT '最新财报期 (如 2026Q2)';

-- 2. financial_quarterly 季度财务指标历史
CREATE TABLE IF NOT EXISTS financial_quarterly (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  report_date DATE NOT NULL COMMENT '财报截止日',
  report_period VARCHAR(10)  COMMENT '财报期标签 (如 2026Q2)',
  publish_date DATE          COMMENT '披露日期',

  -- 质量因子
  roe_ttm DECIMAL(8,2)        COMMENT 'ROE TTM (%)',
  roa_ttm DECIMAL(8,2)        COMMENT 'ROA TTM (%)',
  gross_margin DECIMAL(8,2)   COMMENT '毛利率 (%)',
  net_margin DECIMAL(8,2)     COMMENT '净利率 (%)',
  debt_ratio DECIMAL(8,2)     COMMENT '资产负债率 (%)',
  current_ratio DECIMAL(10,2) COMMENT '流动比率',
  asset_turnover DECIMAL(8,2) COMMENT '总资产周转率',

  -- 成长因子
  rev_yoy DECIMAL(8,2)        COMMENT '营收同比 (%)',
  profit_yoy DECIMAL(8,2)     COMMENT '利润同比 (%)',
  eps_yoy DECIMAL(8,2)        COMMENT 'EPS同比 (%)',
  rev_cagr_3y DECIMAL(8,2)    COMMENT '营收3年复合增速',
  profit_cagr_3y DECIMAL(8,2) COMMENT '利润3年复合增速',

  -- 每股
  eps DECIMAL(10,4)           COMMENT '基本每股收益',
  bvps DECIMAL(10,4)          COMMENT '每股净资产',
  cfps DECIMAL(10,4)          COMMENT '每股经营现金流',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, report_date),
  KEY idx_report_period (report_period),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='季度财务指标历史';

-- 3. financial_income 利润表
CREATE TABLE IF NOT EXISTS financial_income (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  report_date DATE NOT NULL COMMENT '财报截止日',
  publish_date DATE          COMMENT '披露日期',

  -- 收入与成本
  revenue DECIMAL(20,2)       COMMENT '营业收入',
  total_revenue DECIMAL(20,2) COMMENT '营业总收入',
  total_cost DECIMAL(20,2)    COMMENT '营业总成本',
  op_cost DECIMAL(20,2)       COMMENT '营业成本',

  -- 利润
  op_profit DECIMAL(20,2)     COMMENT '营业利润',
  total_profit DECIMAL(20,2)  COMMENT '利润总额',
  net_profit DECIMAL(20,2)    COMMENT '净利润',
  parent_net_profit DECIMAL(20,2) COMMENT '归母净利润',
  deduct_net_profit DECIMAL(20,2) COMMENT '扣非净利润',

  -- 费用
  sell_expense DECIMAL(20,2)  COMMENT '销售费用',
  mgr_expense DECIMAL(20,2)   COMMENT '管理费用',
  rd_expense DECIMAL(20,2)    COMMENT '研发费用',
  fin_expense DECIMAL(20,2)   COMMENT '财务费用',
  tax_expense DECIMAL(20,2)   COMMENT '所得税费用',

  -- 每股
  eps DECIMAL(10,4)           COMMENT '基本每股收益',
  diluted_eps DECIMAL(10,4)   COMMENT '稀释每股收益',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, report_date),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='利润表';

-- 4. financial_balance 资产负债表
CREATE TABLE IF NOT EXISTS financial_balance (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  report_date DATE NOT NULL COMMENT '财报截止日',
  publish_date DATE          COMMENT '披露日期',

  -- 总览
  total_asset DECIMAL(20,2)   COMMENT '资产总计',
  total_liab DECIMAL(20,2)    COMMENT '负债合计',
  equity DECIMAL(20,2)        COMMENT '所有者权益',
  parent_equity DECIMAL(20,2) COMMENT '归母所有者权益',

  -- 流动资产
  cash DECIMAL(20,2)          COMMENT '货币资金',
  trade_asset DECIMAL(20,2)   COMMENT '交易性金融资产',
  receivable DECIMAL(20,2)    COMMENT '应收账款',
  inventory DECIMAL(20,2)     COMMENT '存货',
  current_asset DECIMAL(20,2) COMMENT '流动资产合计',

  -- 非流动资产
  fixed_asset DECIMAL(20,2)   COMMENT '固定资产',
  intangible_asset DECIMAL(20,2) COMMENT '无形资产',
  goodwill DECIMAL(20,2)      COMMENT '商誉',
  noncurrent_asset DECIMAL(20,2) COMMENT '非流动资产合计',

  -- 负债
  short_debt DECIMAL(20,2)    COMMENT '短期借款',
  payable DECIMAL(20,2)       COMMENT '应付账款',
  advance_receipt DECIMAL(20,2) COMMENT '预收账款',
  long_debt DECIMAL(20,2)     COMMENT '长期借款',
  bond_payable DECIMAL(20,2)  COMMENT '应付债券',
  current_liab DECIMAL(20,2)  COMMENT '流动负债合计',
  noncurrent_liab DECIMAL(20,2) COMMENT '非流动负债合计',

  -- 资本
  share_capital DECIMAL(20,2) COMMENT '实收资本',
  capital_reserve DECIMAL(20,2) COMMENT '资本公积',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, report_date),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='资产负债表';

-- 5. financial_cashflow 现金流量表
CREATE TABLE IF NOT EXISTS financial_cashflow (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  report_date DATE NOT NULL COMMENT '财报截止日',
  publish_date DATE          COMMENT '披露日期',

  -- 三大现金流
  op_cashflow_net DECIMAL(20,2) COMMENT '经营活动现金流量净额',
  inv_cashflow_net DECIMAL(20,2) COMMENT '投资活动现金流量净额',
  fin_cashflow_net DECIMAL(20,2) COMMENT '筹资活动现金流量净额',

  -- 经营现金流
  sale_cash DECIMAL(20,2)     COMMENT '销售商品提供劳务收到的现金',
  op_inflow DECIMAL(20,2)     COMMENT '经营活动现金流入小计',
  op_outflow DECIMAL(20,2)    COMMENT '经营活动现金流出小计',

  -- 投资现金流
  inv_inflow DECIMAL(20,2)    COMMENT '投资活动现金流入小计',
  inv_outflow DECIMAL(20,2)   COMMENT '投资活动现金流出小计',

  -- 筹资现金流
  fin_inflow DECIMAL(20,2)    COMMENT '筹资活动现金流入小计',
  fin_outflow DECIMAL(20,2)   COMMENT '筹资活动现金流出小计',

  -- 期末现金
  end_cash DECIMAL(20,2)      COMMENT '期末现金及现金等价物余额',
  net_increase DECIMAL(20,2)  COMMENT '现金及现金等价物净增加额',

  -- 关键净利润
  net_profit DECIMAL(20,2)    COMMENT '净利润',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, report_date),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='现金流量表';

-- 6. financial_hm 股东户数
CREATE TABLE IF NOT EXISTS financial_hm (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  cutoff_date DATE NOT NULL COMMENT '截止日期',
  publish_date DATE         COMMENT '公告日期',

  total_holders BIGINT       COMMENT '股东总数',
  a_holders BIGINT           COMMENT 'A股东户数',
  float_holders BIGINT       COMMENT '已流通股股东户数',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, cutoff_date),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股东户数变化';

-- 7. financial_dividend 分红
CREATE TABLE IF NOT EXISTS financial_dividend (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  declare_date DATE NOT NULL COMMENT '公告日期',
  ex_date DATE                COMMENT '除权除息日',
  record_date DATE            COMMENT '股权登记日',

  per_10_share DECIMAL(10,2)  COMMENT '每10股派息(税前 元)',
  per_10_send DECIMAL(10,2)   COMMENT '每10股送股',
  per_10_transfer DECIMAL(10,2) COMMENT '每10股转增',

  progress VARCHAR(50)        COMMENT '进度描述',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, declare_date),
  KEY idx_ex_date (ex_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分红记录';

-- 8. financial_unlock 解禁
CREATE TABLE IF NOT EXISTS financial_unlock (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  unlock_date DATE NOT NULL COMMENT '解禁日期',
  publish_date DATE         COMMENT '公告日期',

  unlock_shares BIGINT       COMMENT '解禁数量(万股)',
  unlock_value DECIMAL(20,2) COMMENT '解禁市值(亿元)',
  batch_no INT               COMMENT '上市批次',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_date (dm, unlock_date),
  KEY idx_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='解禁限售';

-- 9. financial_top10_holder 十大股东
CREATE TABLE IF NOT EXISTS financial_top10_holder (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  cutoff_date DATE NOT NULL COMMENT '截止日期',
  rank_no INT NOT NULL       COMMENT '排名 (1-10)',

  holder_name VARCHAR(200)   COMMENT '股东名称',
  holder_type VARCHAR(50)    COMMENT '股东类型',
  shares BIGINT              COMMENT '持股数量',
  pct DECIMAL(8,4)           COMMENT '持股比例 (%)',

  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dm_rank (dm, cutoff_date, rank_no),
  KEY idx_holder_name (holder_name(50))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='十大股东';

-- 10. 同步状态表（监控拉取进度）
CREATE TABLE IF NOT EXISTS sync_status (
  data_type VARCHAR(50) PRIMARY KEY COMMENT '数据类型',
  last_sync_date DATE         COMMENT '最后同步日期',
  last_run_at DATETIME        COMMENT '最后运行时间',
  records_synced INT          COMMENT '本次同步条数',
  total_records BIGINT        COMMENT '累计条数',
  status VARCHAR(20)          COMMENT 'success/failed/running',
  error_msg TEXT               COMMENT '错误信息'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据同步状态';