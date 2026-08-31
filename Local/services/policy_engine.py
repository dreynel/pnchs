"""
Policy Engine for DepEd Attendance, Tardiness, Undertime, Leave Credits, and LWOP Rules.
"""
from datetime import datetime, date
import math

class RateCalculationService:
    @staticmethod
    def compute_rates(basic_salary, month_working_days=22, hours_per_day=8):
        """
        Centralized payroll rate computation service.
        Does not hard-code assumptions if month_working_days is provided dynamically.
        """
        if not basic_salary or month_working_days <= 0:
            return {'daily_rate': 0.0, 'hourly_rate': 0.0, 'per_min_rate': 0.0}
        
        daily_rate = float(basic_salary) / float(month_working_days)
        hourly_rate = daily_rate / float(hours_per_day)
        per_min_rate = hourly_rate / 60.0
        return {
            'daily_rate': round(daily_rate, 4),
            'hourly_rate': round(hourly_rate, 4),
            'per_min_rate': round(per_min_rate, 6)
        }

class AttendancePolicyService:
    @staticmethod
    def get_schedule(employee_type, designation=''):
        """
        Returns schedule times in minutes-since-midnight and required daily hours.
        Supports TEACHING and NON_TEACHING classifications.
        """
        emp_type = (employee_type or '').upper()
        desig = (designation or '').lower()

        if emp_type == 'TEACHING' or 'faculty' in desig or 'teacher' in desig:
            return {
                'type': 'TEACHING',
                'am_start': 7 * 60 + 30,  # 07:30 (450)
                'am_end':   11 * 60 + 30, # 11:30 (690)
                'pm_start': 13 * 60,       # 13:00 (780)
                'pm_end':   17 * 60,       # 17:00 (1020)
                'required_work_minutes': 480, # 8 hours total required workday
                'required_classroom_minutes': 360, # 6 hours classroom teaching
                'label': 'Teaching Schedule (7:30-11:30 / 13:00-17:00)'
            }
        else: # NON_TEACHING
            return {
                'type': 'NON_TEACHING',
                'am_start': 8 * 60,        # 08:00 (480)
                'am_end':   12 * 60,       # 12:00 (720)
                'pm_start': 13 * 60,       # 13:00 (780)
                'pm_end':   17 * 60,       # 17:00 (1020)
                'required_work_minutes': 480, # 8 hours
                'required_classroom_minutes': 0,
                'label': 'Non-Teaching Schedule (8:00-12:00 / 13:00-17:00)'
            }

    @staticmethod
    def td_to_minutes(td):
        if td is None:
            return None
        if isinstance(td, (int, float)):
            return int(td)
        if hasattr(td, 'total_seconds'):
            return int(td.total_seconds()) // 60
        if isinstance(td, str):
            parts = td.split(':')
            if len(parts) >= 2:
                return int(parts[0]) * 60 + int(parts[1])
        return None

    @classmethod
    def calculate_tardiness_and_undertime(cls, employee_type, designation, am_in, am_out, pm_in, pm_out,
                                          actual_classroom_minutes=0, teaching_related_minutes=0,
                                          teaching_related_approved=True):
        """
        Calculates tardiness and undertime in exact minutes.
        For TEACHING personnel: Does NOT flag undertime simply because non-classroom teaching-related work
        was performed outside school premises when allowed under applicable DepEd rules.
        """
        sch = cls.get_schedule(employee_type, designation)
        
        am_in_m  = cls.td_to_minutes(am_in)
        am_out_m = cls.td_to_minutes(am_out)
        pm_in_m  = cls.td_to_minutes(pm_in)
        pm_out_m = cls.td_to_minutes(pm_out)

        late_min = 0
        undertime_min = 0

        # Tardiness calculation: physical arrival after start of session
        if am_in_m is not None and am_in_m > sch['am_start']:
            late_min += (am_in_m - sch['am_start'])
        if pm_in_m is not None and pm_in_m > sch['pm_start']:
            late_min += (pm_in_m - sch['pm_start'])

        emp_type_clean = sch['type']

        if emp_type_clean == 'TEACHING':
            # Calculate physical classroom/school rendered time
            rendered_school = 0
            if am_in_m is not None and am_out_m is not None:
                rendered_school += max(0, am_out_m - max(am_in_m, sch['am_start']))
            elif am_in_m is not None:
                rendered_school += max(0, sch['am_end'] - max(am_in_m, sch['am_start']))

            if pm_in_m is not None and pm_out_m is not None:
                rendered_school += max(0, pm_out_m - max(pm_in_m, sch['pm_start']))
            elif pm_in_m is not None:
                rendered_school += max(0, sch['pm_end'] - max(pm_in_m, sch['pm_start']))

            effective_classroom = max(rendered_school, actual_classroom_minutes)

            # If teaching-related work outside premises is allowed/approved:
            if teaching_related_approved:
                # Add off-premise teaching-related work (up to fulfilling required workday)
                total_fulfilled = effective_classroom + max(teaching_related_minutes, sch['required_work_minutes'] - sch['required_classroom_minutes'])
            else:
                total_fulfilled = effective_classroom + teaching_related_minutes

            if total_fulfilled < sch['required_work_minutes']:
                undertime_min = sch['required_work_minutes'] - total_fulfilled
            else:
                undertime_min = 0
        else:
            # NON_TEACHING
            if am_out_m is not None and am_out_m < sch['am_end']:
                undertime_min += (sch['am_end'] - am_out_m)
            if pm_out_m is not None and pm_out_m < sch['pm_end']:
                undertime_min += (sch['pm_end'] - pm_out_m)

        return {
            'tardiness_minutes': int(late_min),
            'undertime_minutes': int(undertime_min)
        }

class LeavePolicyService:
    @staticmethod
    def get_policy_config(cur, key, default_val):
        cur.execute("SELECT config_value FROM tblpolicy_config WHERE config_key = %s", (key,))
        row = cur.fetchone()
        if row and row.get('config_value') is not None:
            return row['config_value']
        return default_val

    @classmethod
    def get_balance(cls, cur, employee_id):
        cur.execute("SELECT vl_minutes, sl_minutes FROM tblleave_balances WHERE employee_id = %s", (employee_id,))
        row = cur.fetchone()
        if not row:
            # Default seed 4800 mins (10 days)
            cur.execute("INSERT INTO tblleave_balances (employee_id, vl_minutes, sl_minutes) VALUES (%s, 4800, 4800)", (employee_id,))
            return {'vl_minutes': 4800, 'sl_minutes': 4800}
        return {'vl_minutes': int(row['vl_minutes']), 'sl_minutes': int(row['sl_minutes'])}

    @classmethod
    def format_minutes_to_dhm(cls, total_minutes, hours_per_day=8):
        """Format integer minutes into Days, Hours, Minutes display string."""
        mins_per_day = hours_per_day * 60
        days = total_minutes // mins_per_day
        rem_mins = total_minutes % mins_per_day
        hours = rem_mins // 60
        mins = rem_mins % 60
        return f"{days}d {hours}h {mins}m"

    @classmethod
    def process_tardiness_and_undertime(cls, cur, employee_id, date_val, tardiness_min, undertime_min,
                                        reference_id=None, user_name='System'):
        """
        Charges tardiness and undertime to VL credits first.
        Returns breakdown of VL-covered vs LWOP (unpaid) minutes.
        Creates transaction records in tblleave_transactions for auditability.
        """
        deduct_tardiness = cls.get_policy_config(cur, 'VL_DEDUCT_TARDINESS', '1') == '1'
        deduct_undertime = cls.get_policy_config(cur, 'VL_DEDUCT_UNDERTIME', '1') == '1'

        bal = cls.get_balance(cur, employee_id)
        current_vl = bal['vl_minutes']

        vl_tardiness = 0
        lwop_tardiness = 0
        if deduct_tardiness and tardiness_min > 0:
            vl_tardiness = min(tardiness_min, current_vl)
            lwop_tardiness = tardiness_min - vl_tardiness
            current_vl -= vl_tardiness
        else:
            lwop_tardiness = tardiness_min

        vl_undertime = 0
        lwop_undertime = 0
        if deduct_undertime and undertime_min > 0:
            vl_undertime = min(undertime_min, current_vl)
            lwop_undertime = undertime_min - vl_undertime
            current_vl -= vl_undertime
        else:
            lwop_undertime = undertime_min

        # Update DB balance
        cur.execute("UPDATE tblleave_balances SET vl_minutes = %s WHERE employee_id = %s", (current_vl, employee_id))

        ref_str = str(reference_id) if reference_id else 'DTR'

        # Log VL transactions
        if vl_tardiness > 0:
            cur.execute("""
                INSERT INTO tblleave_transactions
                (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, date_val, 'VL', vl_tardiness, 'DEDUCTION', 'TARDINESS', ref_str, f"Tardiness of {tardiness_min} mins charged to VL", user_name))

        if vl_undertime > 0:
            cur.execute("""
                INSERT INTO tblleave_transactions
                (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, date_val, 'VL', vl_undertime, 'DEDUCTION', 'UNDERTIME', ref_str, f"Undertime of {undertime_min} mins charged to VL", user_name))

        return {
            'vl_tardiness_minutes': vl_tardiness,
            'vl_undertime_minutes': vl_undertime,
            'lwop_tardiness_minutes': lwop_tardiness,
            'lwop_undertime_minutes': lwop_undertime,
            'total_vl_charged': vl_tardiness + vl_undertime,
            'total_lwop_minutes': lwop_tardiness + lwop_undertime,
            'remaining_vl_minutes': current_vl
        }

    @classmethod
    def reverse_attendance_leave_deductions(cls, cur, employee_id, reference_id, user_name='System', reason='Attendance Correction'):
        """
        Reverses any previous VL deductions associated with reference_id.
        Restores VL balance and logs a REVERSAL transaction.
        """
        cur.execute("""
            SELECT id, leave_type, minutes, source, date
            FROM tblleave_transactions
            WHERE employee_id = %s AND reference_id = %s AND transaction_type = %s
        """, (employee_id, str(reference_id), 'DEDUCTION'))
        txs = cur.fetchall()

        if not txs:
            return 0

        total_reversed = 0
        for tx in txs:
            mins = tx['minutes']
            total_reversed += mins

            # Log reversal
            cur.execute("""
                INSERT INTO tblleave_transactions
                (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, tx['date'], tx['leave_type'], mins, 'REVERSAL', tx['source'], str(reference_id),
                  f"Reversal of {mins} mins due to {reason}", user_name))

        # Restore balance
        cur.execute("UPDATE tblleave_balances SET vl_minutes = vl_minutes + %s WHERE employee_id = %s", (total_reversed, employee_id))
        return total_reversed

class PayrollPolicyService:
    @staticmethod
    def is_payroll_locked(cur, period_key):
        cur.execute("SELECT status FROM tblpayroll WHERE period_key = %s", (period_key,))
        row = cur.fetchone()
        if row and row.get('status') in ['Approved', 'Posted']:
            return True
        return False

    @staticmethod
    def check_policy_effective_date(cur, check_date):
        cur.execute("SELECT config_value FROM tblpolicy_config WHERE config_key = %s", ('POLICY_EFFECTIVE_DATE',))
        row = cur.fetchone()
        if not row or not row.get('config_value'):
            return True # Active by default
        try:
            eff_date = datetime.strptime(row['config_value'], '%Y-%m-%d').date()
            if isinstance(check_date, str):
                check_date = datetime.strptime(check_date, '%Y-%m-%d').date()
            return check_date >= eff_date
        except Exception:
            return True

class HabitualTardinessService:
    @staticmethod
    def check_habitual_tardiness(cur, employee_id, target_year, target_month):
        """
        Checks if an employee crosses the administrative habitual tardiness threshold.
        Threshold: e.g. >=10 occurrences per month for >=2 consecutive months in a semester.
        Does NOT impose automatic disciplinary or payroll penalties; flags for HR review.
        """
        cur.execute("SELECT config_value FROM tblpolicy_config WHERE config_key = %s", ('HABITUAL_TARDINESS_MONTHLY_COUNT',))
        row1 = cur.fetchone()
        monthly_limit = int(row1['config_value']) if row1 and row1.get('config_value') else 10

        cur.execute("SELECT config_value FROM tblpolicy_config WHERE config_key = %s", ('HABITUAL_TARDINESS_CONSECUTIVE_MONTHS',))
        row2 = cur.fetchone()
        consec_limit = int(row2['config_value']) if row2 and row2.get('config_value') else 2

        # Evaluate last 6 months up to target_month
        monthly_tardy_counts = {}
        curr_m = target_month
        curr_y = target_year
        months_to_check = []
        for _ in range(6):
            months_to_check.append((curr_y, curr_m))
            curr_m -= 1
            if curr_m < 1:
                curr_m = 12
                curr_y -= 1
        months_to_check.reverse()

        qualifying_months = []
        for y, m in months_to_check:
            cur.execute("""
                SELECT COUNT(*) as cnt
                FROM tbltime_logs
                WHERE employee_id = %s
                  AND YEAR(work_date) = %s
                  AND MONTH(work_date) = %s
                  AND tardiness_minutes > 0
            """, (employee_id, y, m))
            cnt = cur.fetchone()['cnt']
            label = f"{y}-{m:02d}"
            monthly_tardy_counts[label] = cnt
            if cnt >= monthly_limit:
                qualifying_months.append(label)

        # Check for consecutive months
        is_flagged = False
        consec_streak = 0
        max_streak = 0
        for y, m in months_to_check:
            label = f"{y}-{m:02d}"
            if label in qualifying_months:
                consec_streak += 1
                if consec_streak > max_streak:
                    max_streak = consec_streak
            else:
                consec_streak = 0

        if max_streak >= consec_limit:
            is_flagged = True

        return {
            'employee_id': employee_id,
            'is_flagged': is_flagged,
            'threshold_monthly_count': monthly_limit,
            'threshold_consecutive_months': consec_limit,
            'qualifying_months': qualifying_months,
            'monthly_counts': monthly_tardy_counts,
            'reason': f"Crossed habitual tardiness threshold ({max_streak} consecutive months with >={monthly_limit} tardy occurrences)" if is_flagged else "Normal attendance pattern"
        }

class AuditService:
    @staticmethod
    def log_action(cur, action, employee_id=None, user_name='System', target_table=None, target_id=None,
                   old_value=None, new_value=None, reason=None):
        cur.execute("""
            INSERT INTO tblaudit_logs
            (employee_id, user_name, action, target_table, target_id, old_value, new_value, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (employee_id, user_name, action, target_table, str(target_id) if target_id else None,
              str(old_value) if old_value else None, str(new_value) if new_value else None, reason))
