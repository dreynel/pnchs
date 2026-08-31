"""
Run this once to create the database tables:
    python init_db.py
"""
from db import get_connection
from mysql.connector import Error

DDL_USERS = """
CREATE TABLE IF NOT EXISTS tblusers (
    id            INT          NOT NULL AUTO_INCREMENT,
    username      VARCHAR(100) NOT NULL UNIQUE,
    password      VARCHAR(255) NOT NULL,
    name          VARCHAR(150) NOT NULL,
    role          VARCHAR(50)  NOT NULL,
    employee_id   VARCHAR(20)  NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_PAYROLL = """
CREATE TABLE IF NOT EXISTS tblpayroll (
    id            INT          NOT NULL AUTO_INCREMENT,
    period_key    VARCHAR(20)  NOT NULL UNIQUE,
    year          INT          NOT NULL,
    month         INT          NOT NULL,
    half          INT          NOT NULL,
    status        VARCHAR(30)  NOT NULL DEFAULT 'Draft',
    remarks       TEXT         NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_PAYROLL_DETAILS = """
CREATE TABLE IF NOT EXISTS tblpayroll_details (
    id            INT          NOT NULL AUTO_INCREMENT,
    period_key    VARCHAR(20)  NOT NULL,
    employee_id   VARCHAR(20)  NOT NULL,
    basic_salary  DECIMAL(10,2) DEFAULT 0,
    half_basic    DECIMAL(10,2) DEFAULT 0,
    other_earnings DECIMAL(10,2) DEFAULT 0,
    other_deductions DECIMAL(10,2) DEFAULT 0,
    daily_rate    DECIMAL(10,2) DEFAULT 0,
    absent_days   INT          DEFAULT 0,
    absent_deduction DECIMAL(10,2) DEFAULT 0,
    late_minutes  INT          DEFAULT 0,
    tardiness_deduction DECIMAL(10,2) DEFAULT 0,
    undertime_minutes INT          DEFAULT 0,
    undertime_deduction DECIMAL(10,2) DEFAULT 0,
    holiday_pay   DECIMAL(10,2) DEFAULT 0,
    leave_deduction DECIMAL(10,2) DEFAULT 0,
    total_gross   DECIMAL(10,2) DEFAULT 0,
    total_deduct  DECIMAL(10,2) DEFAULT 0,
    net_pay       DECIMAL(10,2) DEFAULT 0,
    is_negative   TINYINT(1)   DEFAULT 0,
    dtr_filed     TINYINT(1)   DEFAULT 0,
    payheads_json JSON         NULL,
    statutory_json JSON        NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_pd_payroll FOREIGN KEY (period_key) REFERENCES tblpayroll(period_key) ON DELETE CASCADE,
    CONSTRAINT fk_pd_emp FOREIGN KEY (employee_id) REFERENCES tblemployee(employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL = """
CREATE TABLE IF NOT EXISTS tblemployee (
    id            INT          NOT NULL AUTO_INCREMENT,
    employee_id   VARCHAR(20)  NOT NULL UNIQUE,
    first_name    VARCHAR(80)  NOT NULL,
    last_name     VARCHAR(80)  NOT NULL,
    designation   VARCHAR(120) NOT NULL,
    birthday      DATE         NULL,
    email         VARCHAR(150) NOT NULL,
    contact       VARCHAR(30)  NOT NULL,
    address       TEXT         NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                               ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_FINGERPRINTS = """
CREATE TABLE IF NOT EXISTS fingerprints (
    id                   INT          NOT NULL AUTO_INCREMENT,
    employee_id          VARCHAR(20)  NULL,
    user_name            VARCHAR(150) NOT NULL,
    fingerprint_template TEXT         NOT NULL,
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_fingerprint_employee
        FOREIGN KEY (employee_id)
        REFERENCES tblemployee (employee_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL2 = """
CREATE TABLE IF NOT EXISTS tblpayhead (
    id            INT            NOT NULL AUTO_INCREMENT,
    employee_id   VARCHAR(20)    NOT NULL,
    pay_head      VARCHAR(120)   NOT NULL,
    description   TEXT,
    amount        DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    category      ENUM('Earning', 'Deduction') DEFAULT 'Earning',
    mode          ENUM('Amount', 'Percentage') DEFAULT 'Amount',
    percentage_value DECIMAL(10, 2) DEFAULT 0.00,
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_payhead_employee
        FOREIGN KEY (employee_id)
        REFERENCES tblemployee (employee_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_BIO = """
CREATE TABLE IF NOT EXISTS tblbiometric_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id VARCHAR(20) NOT NULL,
    log_type VARCHAR(20) NOT NULL,
    log_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bio_emp FOREIGN KEY (employee_id) REFERENCES tblemployee(employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_HOLIDAYS = """
CREATE TABLE IF NOT EXISTS tblholidays (
    id INT AUTO_INCREMENT PRIMARY KEY,
    holiday_date DATE NOT NULL,
    holiday_name VARCHAR(150) NOT NULL,
    holiday_type VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_LEAVES = """
CREATE TABLE IF NOT EXISTS tblleaves (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id VARCHAR(20) NOT NULL,
    leave_date DATE NOT NULL,
    leave_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'Pending',
    reason TEXT NULL,
    reviewed_by VARCHAR(100) NULL,
    reviewed_at DATETIME NULL,
    filed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_leave_emp FOREIGN KEY (employee_id) REFERENCES tblemployee(employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_GLOBAL_PAYHEADS = """
CREATE TABLE IF NOT EXISTS tblglobal_payheads (
    id            INT            NOT NULL AUTO_INCREMENT,
    name          VARCHAR(120)   NOT NULL,
    description   TEXT,
    amount        DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    type          VARCHAR(20)    NOT NULL, -- 'Earning' or 'Deduction'
    mode          ENUM('Amount', 'Percentage') DEFAULT 'Amount',
    percentage_value DECIMAL(10, 2) DEFAULT 0.00,
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_STATUTORY_REGISTRY = """
CREATE TABLE IF NOT EXISTS tblstatutory_registry (
    id            INT            NOT NULL AUTO_INCREMENT,
    config_key    VARCHAR(100)   NOT NULL UNIQUE,
    config_value  VARCHAR(255)   NOT NULL,
    config_mode   ENUM('Amount', 'Percentage') DEFAULT 'Percentage',
    description   TEXT           NULL,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_ENROLLMENT_TASKS = """
CREATE TABLE IF NOT EXISTS tblenrollment_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id VARCHAR(20) NOT NULL,
    finger_index INT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_enroll_task_emp FOREIGN KEY (employee_id) REFERENCES tblemployee(employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_TIME_LOGS = """
CREATE TABLE IF NOT EXISTS tbltime_logs (
    log_id      INT          NOT NULL AUTO_INCREMENT,
    employee_id VARCHAR(20)  NOT NULL,
    work_date   DATE         NOT NULL,
    am_time_in  TIME         NULL,
    am_time_out TIME         NULL,
    pm_time_in  TIME         NULL,
    pm_time_out TIME         NULL,
    PRIMARY KEY (log_id),
    UNIQUE KEY idx_emp_date (employee_id, work_date),
    CONSTRAINT fk_timelog_emp FOREIGN KEY (employee_id) REFERENCES tblemployee(employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_LEAVE_BALANCES = """
CREATE TABLE IF NOT EXISTS tblleave_balances (
    id            INT          NOT NULL AUTO_INCREMENT,
    employee_id   VARCHAR(20)  NOT NULL UNIQUE,
    vl_minutes    INT          NOT NULL DEFAULT 4800,
    sl_minutes    INT          NOT NULL DEFAULT 4800,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_leave_bal_emp FOREIGN KEY (employee_id) REFERENCES tblemployee (employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_LEAVE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS tblleave_transactions (
    id               INT          NOT NULL AUTO_INCREMENT,
    employee_id      VARCHAR(20)  NOT NULL,
    date             DATE         NOT NULL,
    leave_type       VARCHAR(20)  NOT NULL DEFAULT 'VL',
    minutes          INT          NOT NULL,
    transaction_type VARCHAR(20)  NOT NULL,
    source           VARCHAR(30)  NOT NULL,
    reference_id     VARCHAR(100) NULL,
    remarks          TEXT         NULL,
    created_by       VARCHAR(100) NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_leave_tx_emp FOREIGN KEY (employee_id) REFERENCES tblemployee (employee_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_POLICY_CONFIG = """
CREATE TABLE IF NOT EXISTS tblpolicy_config (
    id           INT          NOT NULL AUTO_INCREMENT,
    config_key   VARCHAR(100) NOT NULL UNIQUE,
    config_value VARCHAR(255) NOT NULL,
    description  TEXT         NULL,
    updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_AUDIT_LOGS = """
CREATE TABLE IF NOT EXISTS tblaudit_logs (
    id           INT          NOT NULL AUTO_INCREMENT,
    employee_id  VARCHAR(20)  NULL,
    user_name    VARCHAR(100) NULL,
    action       VARCHAR(50)  NOT NULL,
    target_table VARCHAR(50)  NULL,
    target_id    VARCHAR(100) NULL,
    old_value    TEXT         NULL,
    new_value    TEXT         NULL,
    reason       TEXT         NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_SALARY_GRADES = """
CREATE TABLE IF NOT EXISTS tblsalary_grades (
    id            INT            NOT NULL AUTO_INCREMENT,
    salary_grade  INT            NOT NULL UNIQUE,
    position_title VARCHAR(120)  NULL,
    step_1        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_2        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_3        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_4        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_5        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_6        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_7        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    step_8        DECIMAL(12,2)  NOT NULL DEFAULT 0.00,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _add_column_if_missing(cur, table, column, alter_sql):
    """Add a column only if it doesn't already exist (compatible with all MySQL versions)."""
    cur.execute(
        "SELECT COUNT(*) as cnt FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, column)
    )
    row = cur.fetchone()
    cnt = row['cnt'] if isinstance(row, dict) else row[0]
    if cnt == 0:
        cur.execute(alter_sql)


def init():
    try:
        conn = get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(DDL)
        cur.execute(DDL2)
        cur.execute(DDL_FINGERPRINTS)
        cur.execute(DDL_BIO)
        cur.execute(DDL_USERS)
        cur.execute(DDL_PAYROLL)
        cur.execute(DDL_PAYROLL_DETAILS)
        cur.execute(DDL_HOLIDAYS)
        cur.execute(DDL_LEAVES)
        cur.execute(DDL_GLOBAL_PAYHEADS)
        cur.execute(DDL_STATUTORY_REGISTRY)
        cur.execute(DDL_ENROLLMENT_TASKS)
        cur.execute(DDL_TIME_LOGS)
        cur.execute(DDL_LEAVE_BALANCES)
        cur.execute(DDL_LEAVE_TRANSACTIONS)
        cur.execute(DDL_POLICY_CONFIG)
        cur.execute(DDL_AUDIT_LOGS)
        cur.execute(DDL_SALARY_GRADES)

        # ── Safe column migrations (works on all MySQL versions) ───────────────
        migrations = [
            ('tblemployee',        'employee_type',   "ALTER TABLE tblemployee ADD COLUMN employee_type VARCHAR(50) DEFAULT 'NON_TEACHING' AFTER designation"),
            ('tblemployee',        'salary_grade',    "ALTER TABLE tblemployee ADD COLUMN salary_grade INT NULL AFTER employee_type"),
            ('tblemployee',        'step',            "ALTER TABLE tblemployee ADD COLUMN step INT DEFAULT 1 AFTER salary_grade"),
            ('tblenrollment_tasks', 'step',           "ALTER TABLE tblenrollment_tasks ADD COLUMN step INT DEFAULT 1 AFTER status"),
            ('tblenrollment_tasks', 'message',        "ALTER TABLE tblenrollment_tasks ADD COLUMN message VARCHAR(255) NULL AFTER step"),
            ('tblenrollment_tasks', 'error_message',  "ALTER TABLE tblenrollment_tasks ADD COLUMN error_message VARCHAR(255) NULL AFTER message"),
            ('tblpayroll',         'approved_by',     'ALTER TABLE tblpayroll ADD COLUMN approved_by VARCHAR(150) NULL AFTER remarks'),

            ('tblpayroll',         'approved_by',     'ALTER TABLE tblpayroll ADD COLUMN approved_by VARCHAR(150) NULL AFTER remarks'),
            ('tblpayroll',         'approved_at',     'ALTER TABLE tblpayroll ADD COLUMN approved_at DATETIME NULL AFTER approved_by'),
            ('tblpayroll_details', 'holiday_pay',     'ALTER TABLE tblpayroll_details ADD COLUMN holiday_pay DECIMAL(10,2) DEFAULT 0 AFTER other_earnings'),
            ('tblpayroll_details', 'undertime_minutes', 'ALTER TABLE tblpayroll_details ADD COLUMN undertime_minutes INT DEFAULT 0 AFTER tardiness_deduction'),
            ('tblpayroll_details', 'undertime_deduction', 'ALTER TABLE tblpayroll_details ADD COLUMN undertime_deduction DECIMAL(10,2) DEFAULT 0 AFTER undertime_minutes'),
            ('tblpayroll_details', 'sss_ee',          'ALTER TABLE tblpayroll_details ADD COLUMN sss_ee DECIMAL(10,2) DEFAULT 0 AFTER undertime_deduction'),
            ('tblpayroll_details', 'philhealth_ee',   'ALTER TABLE tblpayroll_details ADD COLUMN philhealth_ee DECIMAL(10,2) DEFAULT 0 AFTER sss_ee'),
            ('tblpayroll_details', 'pagibig_ee',      'ALTER TABLE tblpayroll_details ADD COLUMN pagibig_ee DECIMAL(10,2) DEFAULT 0 AFTER philhealth_ee'),
            ('tblpayroll_details', 'withholding_tax', 'ALTER TABLE tblpayroll_details ADD COLUMN withholding_tax DECIMAL(10,2) DEFAULT 0 AFTER pagibig_ee'),
            ('tblpayroll_details', 'is_negative',     'ALTER TABLE tblpayroll_details ADD COLUMN is_negative TINYINT(1) DEFAULT 0 AFTER net_pay'),
            ('tblpayroll_details', 'payheads_json',   'ALTER TABLE tblpayroll_details ADD COLUMN payheads_json JSON NULL AFTER dtr_filed'),
            ('tblpayroll_details', 'statutory_json',  'ALTER TABLE tblpayroll_details ADD COLUMN statutory_json JSON NULL AFTER payheads_json'),
            ('tblpayroll_details', 'vl_tardiness_minutes', 'ALTER TABLE tblpayroll_details ADD COLUMN vl_tardiness_minutes INT DEFAULT 0 AFTER undertime_minutes'),
            ('tblpayroll_details', 'vl_undertime_minutes', 'ALTER TABLE tblpayroll_details ADD COLUMN vl_undertime_minutes INT DEFAULT 0 AFTER vl_tardiness_minutes'),
            ('tblpayroll_details', 'lwop_tardiness_minutes', 'ALTER TABLE tblpayroll_details ADD COLUMN lwop_tardiness_minutes INT DEFAULT 0 AFTER vl_undertime_minutes'),
            ('tblpayroll_details', 'lwop_undertime_minutes', 'ALTER TABLE tblpayroll_details ADD COLUMN lwop_undertime_minutes INT DEFAULT 0 AFTER lwop_tardiness_minutes'),
            ('tblpayhead',         'mode',            "ALTER TABLE tblpayhead ADD COLUMN mode ENUM('Amount', 'Percentage') DEFAULT 'Amount' AFTER amount"),
            ('tblpayhead',         'percentage_value', "ALTER TABLE tblpayhead ADD COLUMN percentage_value DECIMAL(10, 2) DEFAULT 0.00 AFTER mode"),
            ('tblpayhead',         'description',      "ALTER TABLE tblpayhead ADD COLUMN description TEXT AFTER pay_head"),
            ('tblglobal_payheads', 'mode',            "ALTER TABLE tblglobal_payheads ADD COLUMN mode ENUM('Amount', 'Percentage') DEFAULT 'Amount' AFTER amount"),
            ('tblglobal_payheads', 'percentage_value', "ALTER TABLE tblglobal_payheads ADD COLUMN percentage_value DECIMAL(10, 2) DEFAULT 0.00 AFTER mode"),
            ('tblglobal_payheads', 'description',      "ALTER TABLE tblglobal_payheads ADD COLUMN description TEXT AFTER name"),
            ('tblstatutory_registry', 'config_mode',  "ALTER TABLE tblstatutory_registry ADD COLUMN config_mode ENUM('Amount', 'Percentage') DEFAULT 'Percentage' AFTER config_value"),
            ('tbltime_logs',       'actual_classroom_teaching_minutes', 'ALTER TABLE tbltime_logs ADD COLUMN actual_classroom_teaching_minutes INT DEFAULT 0 AFTER pm_time_out'),
            ('tbltime_logs',       'teaching_related_minutes', 'ALTER TABLE tbltime_logs ADD COLUMN teaching_related_minutes INT DEFAULT 0 AFTER actual_classroom_teaching_minutes'),
            ('tbltime_logs',       'teaching_related_approved', 'ALTER TABLE tbltime_logs ADD COLUMN teaching_related_approved TINYINT(1) DEFAULT 1 AFTER teaching_related_minutes'),
            ('tbltime_logs',       'tardiness_minutes', 'ALTER TABLE tbltime_logs ADD COLUMN tardiness_minutes INT DEFAULT 0 AFTER teaching_related_approved'),
            ('tbltime_logs',       'undertime_minutes', 'ALTER TABLE tbltime_logs ADD COLUMN undertime_minutes INT DEFAULT 0 AFTER tardiness_minutes'),
            ('tbltime_logs',       'vl_minutes_charged', 'ALTER TABLE tbltime_logs ADD COLUMN vl_minutes_charged INT DEFAULT 0 AFTER undertime_minutes'),
            ('tbltime_logs',       'unpaid_minutes',   'ALTER TABLE tbltime_logs ADD COLUMN unpaid_minutes INT DEFAULT 0 AFTER vl_minutes_charged'),
            ('tbltime_logs',       'remarks',          'ALTER TABLE tbltime_logs ADD COLUMN remarks TEXT NULL AFTER unpaid_minutes'),
            ('tblleaves',          'reason',           'ALTER TABLE tblleaves ADD COLUMN reason TEXT NULL AFTER status'),
            ('tblleaves',          'reviewed_by',      'ALTER TABLE tblleaves ADD COLUMN reviewed_by VARCHAR(100) NULL AFTER reason'),
            ('tblleaves',          'reviewed_at',      'ALTER TABLE tblleaves ADD COLUMN reviewed_at DATETIME NULL AFTER reviewed_by'),
            ('tblleaves',          'filed_at',         'ALTER TABLE tblleaves ADD COLUMN filed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER reviewed_at'),
        ]
        for table, col, sql in migrations:
            _add_column_if_missing(cur, table, col, sql)

        # Ensure finger_index exists on fingerprints
        _add_column_if_missing(cur, 'fingerprints', 'finger_index', "ALTER TABLE fingerprints ADD COLUMN finger_index INT DEFAULT 1")
        
        # Try adding unique constraint for (employee_id, finger_index) if not exist
        try:
            cur.execute("ALTER TABLE fingerprints ADD UNIQUE KEY idx_emp_finger (employee_id, finger_index)")
        except Exception:
            pass # Probably already exists
        
        # Seed users
        users = [
            ('admin', 'admin123', 'John Lenard Bocal', 'Admin', 'EMP-001'),
            ('hr', 'hr1234', 'John Lenard Bocal (HR)', 'HR', 'EMP-001'),
            ('finance', 'finance123', 'John Lenard Bocal (Finance)', 'Finance', 'EMP-001'),
            ('john.lenard@school.edu.ph', 'user123', 'John Lenard Bocal', 'Employee', 'EMP-001')
        ]
        for u in users:
            cur.execute("SELECT id FROM tblusers WHERE username=%s", (u[0],))
            if not cur.fetchone():
                cur.execute("INSERT INTO tblusers (username, password, name, role, employee_id) VALUES (%s, %s, %s, %s, %s)", u)

        # Seed 2026 PH Holidays
        holidays = [
            ('2026-01-01', 'New Year\'s Day', 'Regular'),
            ('2026-02-25', 'EDSA People Power Revolution', 'Special'),
            ('2026-04-02', 'Maundy Thursday', 'Regular'),
            ('2026-04-03', 'Good Friday', 'Regular'),
            ('2026-04-09', 'Araw ng Kagitingan', 'Regular'),
            ('2026-05-01', 'Labor Day', 'Regular'),
            ('2026-06-12', 'Independence Day', 'Regular'),
            ('2026-08-21', 'Ninoy Aquino Day', 'Special'),
            ('2026-08-31', 'National Heroes Day', 'Regular'),
            ('2026-11-01', 'All Saints\' Day', 'Special'),
            ('2026-11-30', 'Bonifacio Day', 'Regular'),
            ('2026-12-25', 'Christmas Day', 'Regular'),
            ('2026-12-30', 'Rizal Day', 'Regular')
        ]
        for h in holidays:
            cur.execute("SELECT id FROM tblholidays WHERE holiday_date=%s", (h[0],))
            if not cur.fetchone():
                cur.execute("INSERT INTO tblholidays (holiday_date, holiday_name, holiday_type) VALUES (%s, %s, %s)", h)

        # Seed Statutory Config (Official Philippine Government DepEd Rules)
        stat_configs = [
            ('GSIS_EE_RATE', '0.09', 'Percentage', 'GSIS employee share rate (9% of basic salary)'),
            ('PHILHEALTH_EE_RATE', '0.025', 'Percentage', 'PhilHealth employee share rate (2.5% of basic salary)'),
            ('PAGIBIG_EE_AMOUNT', '200.00', 'Amount', 'Pag-IBIG employee monthly fixed contribution (₱200 cap)'),
            ('BIR_ENABLED', '1', 'Amount', 'Enable BIR Withholding Tax (1=Yes, 0=No)')
        ]
        for k, v, m, d in stat_configs:
            cur.execute("SELECT id FROM tblstatutory_registry WHERE config_key=%s", (k,))
            if not cur.fetchone():
                cur.execute("INSERT INTO tblstatutory_registry (config_key, config_value, config_mode, description) VALUES (%s, %s, %s, %s)", (k, v, m, d))
            else:
                cur.execute("UPDATE tblstatutory_registry SET config_value=%s, config_mode=%s, description=%s WHERE config_key=%s", (v, m, d, k))

        # Seed Policy Configs for DepEd Rules
        policy_configs = [
            ('VL_DEDUCT_TARDINESS', '1', 'Treat tardiness as VL credit deduction first (1=Yes, 0=No)'),
            ('VL_DEDUCT_UNDERTIME', '1', 'Treat undertime as VL credit deduction first (1=Yes, 0=No)'),
            ('WORK_HOURS_PER_DAY', '8', 'Standard work hours per day'),
            ('HABITUAL_TARDINESS_MONTHLY_COUNT', '10', 'Number of tardy occurrences per month for habitual threshold'),
            ('HABITUAL_TARDINESS_CONSECUTIVE_MONTHS', '2', 'Number of consecutive months for habitual threshold'),
            ('POLICY_EFFECTIVE_DATE', '2026-01-01', 'Effective date for DepEd attendance policy'),
            ('ROUND_TARDINESS', '0', 'Whether to round tardiness/undertime minutes (0=No rounding)')
        ]
        for k, v, d in policy_configs:
            cur.execute("SELECT id FROM tblpolicy_config WHERE config_key=%s", (k,))
            if not cur.fetchone():
                cur.execute("INSERT INTO tblpolicy_config (config_key, config_value, description) VALUES (%s, %s, %s)", (k, v, d))

        # Seed leave balances for existing employees if missing
        cur.execute("SELECT employee_id FROM tblemployee")
        emps = cur.fetchall()
        for emp in emps:
            eid = emp['employee_id']
            cur.execute("SELECT id FROM tblleave_balances WHERE employee_id=%s", (eid,))
            if not cur.fetchone():
                cur.execute("INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes) VALUES (%s, 4800, 4800)", (eid,))

        # Seed Salary Grades (Official Government SSL Third Tranche)
        salary_grade_matrix = [
            (1, None, 14634, 14730, 14849, 14968, 15089, 15211, 15333, 15456),
            (2, None, 15522, 15636, 15752, 15869, 15986, 16103, 16223, 16342),
            (3, None, 16486, 16610, 16732, 16856, 16982, 17106, 17234, 17360),
            (4, None, 17506, 17636, 17767, 17898, 18031, 18163, 18298, 18433),
            (5, None, 18581, 18720, 18858, 18998, 19137, 19280, 19423, 19565),
            (6, None, 19716, 19862, 20009, 20158, 20307, 20456, 20609, 20761),
            (7, None, 20914, 21069, 21224, 21382, 21539, 21699, 21859, 22022),
            (8, None, 22423, 22627, 22832, 23038, 23246, 23456, 23668, 23883),
            (9, None, 24329, 24523, 24720, 24917, 25117, 25318, 25521, 25725),
            (10, None, 26917, 27131, 27347, 27565, 27786, 28007, 28230, 28456),
            (11, 'Teacher I', 31705, 31820, 32109, 32401, 32697, 32998, 33302, 33611),
            (12, 'Teacher II', 33947, 34069, 34357, 34648, 34943, 35242, 35544, 35850),
            (13, 'Teacher III', 36125, 36283, 36599, 36919, 37244, 37572, 37904, 38241),
            (14, 'Teacher IV', 38764, 39141, 39523, 39910, 40300, 40696, 41097, 41503),
            (15, 'Teacher V', 42178, 42594, 43015, 43442, 43874, 44310, 44753, 45202),
            (16, 'Teacher VI', 45694, 46152, 46615, 47084, 47559, 48040, 48528, 49020),
            (17, 'Teacher VII', 49562, 50066, 50576, 51092, 51614, 52144, 52678, 53221),
            (18, 'Master Teacher I', 53818, 54371, 54933, 55499, 56075, 56657, 57246, 57842),
            (19, 'Master Teacher II / Principal I', 59153, 59966, 60793, 61632, 62486, 63353, 64236, 65132),
            (20, 'Master Teacher III / Principal II', 66052, 66970, 67904, 68853, 69818, 70772, 71727, 72671),
            (21, 'Master Teacher IV / Principal III', 73303, 74337, 75388, 76456, 77542, 78645, 79692, 80831),
            (22, 'Principal IV', 81796, 82963, 84151, 85356, 86582, 87746, 89011, 90295),
            (23, None, 91306, 92622, 93962, 95330, 96823, 98341, 99883, 101318),
            (24, None, 102603, 104209, 105841, 107500, 109185, 110898, 112533, 114301),
            (25, None, 116643, 118469, 120326, 122212, 124131, 126079, 128061, 130073),
            (26, None, 131807, 133870, 135968, 138100, 140268, 142469, 144707, 146983),
            (27, None, 148940, 151273, 153644, 155906, 158353, 160235, 162752, 165310),
            (28, None, 167129, 169752, 172418, 174797, 177545, 180339, 182660, 185537),
            (29, None, 187531, 190482, 193480, 196528, 199624, 202005, 205191, 208430),
            (30, None, 210718, 214038, 217207, 220425, 223691, 227224, 230595, 234240),
            (31, None, 300961, 306691, 312532, 318182, 323938, 329989, 336092, 342310),
            (32, None, 356237, 363257, 370418, 377359, 384805, 392400, 400150, 408055),
            (33, None, 449157, 462329, 0, 0, 0, 0, 0, 0)
        ]
        for sg in salary_grade_matrix:
            cur.execute("SELECT id FROM tblsalary_grades WHERE salary_grade=%s", (sg[0],))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO tblsalary_grades (salary_grade, position_title, step_1, step_2, step_3, step_4, step_5, step_6, step_7, step_8) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    sg
                )

        conn.commit()
        cur.close()
        conn.close()
        print("[OK] Tables created/migrated: tblemployee, tblpayhead, fingerprints, tblusers, tblpayroll, tblpayroll_details, tblholidays, tblleaves, tblleave_balances, tblleave_transactions, tblpolicy_config, tblaudit_logs, tblsalary_grades")

    except Error as e:
        print(f"[ERROR] Database error: {e}")

if __name__ == '__main__':
    init()