from flask import Blueprint, jsonify, request
from db import db_cursor
from mysql.connector import Error

salary_grade_bp = Blueprint('salary_grade', __name__, url_prefix='/api/salary_grades')

DEFAULT_THIRD_TRANCHE = [
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

@salary_grade_bp.route('', methods=['GET'])
@salary_grade_bp.route('/', methods=['GET'])
def get_all_salary_grades():
    """Retrieve full salary grade schedule (Grades 1-33), auto-seeding if empty."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
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
            """)
            
            cur.execute("SELECT * FROM tblsalary_grades ORDER BY salary_grade ASC")
            records = cur.fetchall()
            
            if not records:
                for row in DEFAULT_THIRD_TRANCHE:
                    cur.execute(
                        "INSERT INTO tblsalary_grades (salary_grade, position_title, step_1, step_2, step_3, step_4, step_5, step_6, step_7, step_8) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE position_title=VALUES(position_title), step_1=VALUES(step_1), step_2=VALUES(step_2), step_3=VALUES(step_3), step_4=VALUES(step_4), step_5=VALUES(step_5), step_6=VALUES(step_6), step_7=VALUES(step_7), step_8=VALUES(step_8)",
                        row
                    )
                conn.commit()
                cur.execute("SELECT * FROM tblsalary_grades ORDER BY salary_grade ASC")
                records = cur.fetchall()

            return jsonify(records)
    except Error as e:
        return jsonify({'error': str(e)}), 500

@salary_grade_bp.route('/<int:sg>', methods=['GET'])
def get_salary_grade(sg):
    """Retrieve single salary grade row details."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM tblsalary_grades WHERE salary_grade = %s", (sg,))
            record = cur.fetchone()
            if not record:
                return jsonify({'error': f'Salary Grade {sg} not found.'}), 404
            return jsonify(record)
    except Error as e:
        return jsonify({'error': str(e)}), 500

@salary_grade_bp.route('/<int:sg>', methods=['PUT'])
def update_salary_grade(sg):
    """Update step values and position title for a specific salary grade."""
    data = request.json or {}
    position_title = data.get('position_title')
    steps = [data.get(f'step_{i}') for i in range(1, 9)]

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM tblsalary_grades WHERE salary_grade = %s", (sg,))
            if not cur.fetchone():
                return jsonify({'error': f'Salary Grade {sg} does not exist.'}), 404

            sql = """
                UPDATE tblsalary_grades
                SET position_title = %s,
                    step_1 = %s, step_2 = %s, step_3 = %s, step_4 = %s,
                    step_5 = %s, step_6 = %s, step_7 = %s, step_8 = %s
                WHERE salary_grade = %s
            """
            cur.execute(sql, (position_title, *steps, sg))
            conn.commit()
            return jsonify({'success': True, 'message': f'Salary Grade {sg} successfully updated.'})
    except Error as e:
        return jsonify({'error': str(e)}), 500

@salary_grade_bp.route('/lookup', methods=['GET', 'POST'])
def lookup_rate():
    """Look up computed daily, hourly, and per-minute rates for a given SG and Step."""
    if request.method == 'POST':
        data = request.json or {}
        sg = int(data.get('salary_grade') or 0)
        step = int(data.get('step') or 1)
    else:
        sg = request.args.get('salary_grade', type=int, default=0)
        step = request.args.get('step', type=int, default=1)

    if sg <= 0 or step < 1 or step > 8:
        return jsonify({'error': 'Invalid Salary Grade or Step.'}), 400

    step_col = f'step_{step}'
    try:
        with db_cursor() as (conn, cur):
            cur.execute(f"SELECT salary_grade, position_title, {step_col} AS monthly_basic FROM tblsalary_grades WHERE salary_grade = %s", (sg,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': f'Salary Grade {sg} not found.'}), 404
            
            basic = float(row['monthly_basic'] or 0.0)
            return jsonify({
                'salary_grade': sg,
                'step': step,
                'position_title': row['position_title'],
                'monthly_basic': basic,
                'daily_rate': round(basic / 22.0, 2) if basic else 0.0,
                'hourly_rate': round(basic / (22.0 * 8.0), 2) if basic else 0.0,
                'per_min_rate': round(basic / (22.0 * 8.0 * 60.0), 4) if basic else 0.0
            })
    except Error as e:
        return jsonify({'error': str(e)}), 500

@salary_grade_bp.route('/reseed', methods=['POST'])
def reseed_salary_grades():
    """Reseed/reset all salary grade rates to official Third Tranche defaults."""
    try:
        with db_cursor() as (conn, cur):
            for row in DEFAULT_THIRD_TRANCHE:
                sg = row[0]
                cur.execute("SELECT id FROM tblsalary_grades WHERE salary_grade = %s", (sg,))
                if cur.fetchone():
                    cur.execute(
                        "UPDATE tblsalary_grades SET position_title=%s, step_1=%s, step_2=%s, step_3=%s, step_4=%s, step_5=%s, step_6=%s, step_7=%s, step_8=%s WHERE salary_grade=%s",
                        (row[1], *row[2:], sg)
                    )
                else:
                    cur.execute(
                        "INSERT INTO tblsalary_grades (salary_grade, position_title, step_1, step_2, step_3, step_4, step_5, step_6, step_7, step_8) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        row
                    )
            conn.commit()
            return jsonify({'success': True, 'message': 'Salary grades successfully reseeded to SSL Third Tranche defaults.'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
