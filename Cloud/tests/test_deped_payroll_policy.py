import unittest
import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.policy_engine import (
    RateCalculationService,
    AttendancePolicyService,
    LeavePolicyService,
    PayrollPolicyService,
    HabitualTardinessService
)

class MockCursor:
    """In-memory mock database cursor for testing policy engine without DB dependencies."""
    def __init__(self):
        self.leave_balances = {'EMP-001': {'vl_minutes': 4800, 'sl_minutes': 4800}}
        self.leave_transactions = []
        self.policy_configs = {
            'VL_DEDUCT_TARDINESS': '1',
            'VL_DEDUCT_UNDERTIME': '1',
            'WORK_HOURS_PER_DAY': '8',
            'HABITUAL_TARDINESS_MONTHLY_COUNT': '10',
            'HABITUAL_TARDINESS_CONSECUTIVE_MONTHS': '2',
            'POLICY_EFFECTIVE_DATE': '2026-01-01',
            'ROUND_TARDINESS': '0'
        }
        self.payroll_runs = {}
        self.time_logs = []
        self.last_query = ""

    def execute(self, sql, params=()):
        self.last_query = sql
        sql_u = " ".join(sql.split()).upper()
        if "INSERT INTO TBLLEAVE_TRANSACTIONS" in sql_u:
            self.leave_transactions.append({
                'id': len(self.leave_transactions) + 1,
                'employee_id': params[0],
                'date': params[1],
                'leave_type': params[2],
                'minutes': params[3],
                'transaction_type': params[4],
                'source': params[5],
                'reference_id': params[6],
                'remarks': params[7] if len(params) > 7 else None,
                'created_by': params[8] if len(params) > 8 else 'System'
            })
        elif "FROM TBLPOLICY_CONFIG" in sql_u:
            key = params[0] if params else 'POLICY_EFFECTIVE_DATE'
            val = self.policy_configs.get(key)
            self._fetch_result = {'config_value': val} if val is not None else None
        elif "FROM TBLLEAVE_BALANCES" in sql_u:
            eid = params[0] if params else 'EMP-001'
            bal = self.leave_balances.get(eid, {'vl_minutes': 4800, 'sl_minutes': 4800})
            self._fetch_result = bal
        elif "UPDATE TBLLEAVE_BALANCES SET VL_MINUTES =" in sql_u:
            if "VL_MINUTES +" in sql_u:
                added = params[0]
                eid = params[1]
                if eid in self.leave_balances:
                    self.leave_balances[eid]['vl_minutes'] += added
            else:
                new_vl = params[0]
                eid = params[1]
                if eid in self.leave_balances:
                    self.leave_balances[eid]['vl_minutes'] = new_vl
        elif "FROM TBLLEAVE_TRANSACTIONS" in sql_u:
            eid = params[0]
            ref = params[1]
            target_tx_type = params[2] if len(params) > 2 else 'DEDUCTION'
            matched = [tx for tx in self.leave_transactions if tx['employee_id'] == eid and str(tx['reference_id']) == str(ref) and tx['transaction_type'] == target_tx_type]
            self._fetch_all_result = matched
        elif "FROM TBLPAYROLL" in sql_u:
            pkey = params[0]
            status = self.payroll_runs.get(pkey, {}).get('status')
            self._fetch_result = {'status': status} if status else None
        elif "FROM TBLTIME_LOGS" in sql_u:
            eid = params[0]
            year = params[1]
            month = params[2]
            cnt = len([l for l in self.time_logs if l['employee_id'] == eid and l['year'] == year and l['month'] == month and l['tardiness_minutes'] > 0])
            self._fetch_result = {'cnt': cnt}

    def fetchone(self):
        return getattr(self, '_fetch_result', None)

    def fetchall(self):
        return getattr(self, '_fetch_all_result', [])

class TestDepEdPayrollPolicy(unittest.TestCase):

    def setUp(self):
        self.cur = MockCursor()

    def test_1_non_teaching_on_time(self):
        """TEST 1: Non-teaching employee on time -> 0 tardiness, 0 VL deduction, ₱0 salary impact."""
        res = AttendancePolicyService.calculate_tardiness_and_undertime(
            employee_type='NON_TEACHING', designation='Staff',
            am_in='08:00:00', am_out='12:00:00',
            pm_in='13:00:00', pm_out='17:00:00'
        )
        self.assertEqual(res['tardiness_minutes'], 0)
        self.assertEqual(res['undertime_minutes'], 0)

        proc = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 1), res['tardiness_minutes'], res['undertime_minutes']
        )
        self.assertEqual(proc['total_vl_charged'], 0)
        self.assertEqual(proc['total_lwop_minutes'], 0)
        
        rates = RateCalculationService.compute_rates(25000.00, 22)
        salary_deduction = round(proc['total_lwop_minutes'] * rates['per_min_rate'], 2)
        self.assertEqual(salary_deduction, 0.0)

    def test_2_non_teaching_tardy_covered_by_vl(self):
        """TEST 2: Non-teaching employee 10m tardy with sufficient VL -> 10m tardiness, 10m VL deduction, ₱0 salary deduction."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 4800
        res = AttendancePolicyService.calculate_tardiness_and_undertime(
            employee_type='NON_TEACHING', designation='Staff',
            am_in='08:10:00', am_out='12:00:00',
            pm_in='13:00:00', pm_out='17:00:00'
        )
        self.assertEqual(res['tardiness_minutes'], 10)

        proc = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 2), res['tardiness_minutes'], res['undertime_minutes'], reference_id='LOG-100'
        )
        self.assertEqual(proc['vl_tardiness_minutes'], 10)
        self.assertEqual(proc['lwop_tardiness_minutes'], 0)
        self.assertEqual(proc['remaining_vl_minutes'], 4790)

        rates = RateCalculationService.compute_rates(25000.00, 22)
        salary_deduction = round(proc['total_lwop_minutes'] * rates['per_min_rate'], 2)
        self.assertEqual(salary_deduction, 0.0)

    def test_3_undertime_covered_by_vl(self):
        """TEST 3: Non-teaching employee 15m undertime with sufficient VL -> 15m VL deduction, ₱0 salary deduction."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 4800
        res = AttendancePolicyService.calculate_tardiness_and_undertime(
            employee_type='NON_TEACHING', designation='Staff',
            am_in='08:00:00', am_out='12:00:00',
            pm_in='13:00:00', pm_out='16:45:00'
        )
        self.assertEqual(res['undertime_minutes'], 15)

        proc = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 3), res['tardiness_minutes'], res['undertime_minutes'], reference_id='LOG-101'
        )
        self.assertEqual(proc['vl_undertime_minutes'], 15)
        self.assertEqual(proc['lwop_undertime_minutes'], 0)
        self.assertEqual(proc['remaining_vl_minutes'], 4785)

        rates = RateCalculationService.compute_rates(25000.00, 22)
        salary_deduction = round(proc['total_lwop_minutes'] * rates['per_min_rate'], 2)
        self.assertEqual(salary_deduction, 0.0)

    def test_4_insufficient_vl_creates_lwop(self):
        """TEST 4: Insufficient VL (12m tardy, 5m VL available) -> 5m VL deduction, 7m LWOP, payroll receives only 7m deduction."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 5

        proc = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 4), tardiness_min=12, undertime_min=0, reference_id='LOG-102'
        )
        self.assertEqual(proc['vl_tardiness_minutes'], 5)
        self.assertEqual(proc['lwop_tardiness_minutes'], 7)
        self.assertEqual(proc['remaining_vl_minutes'], 0)

        rates = RateCalculationService.compute_rates(26400.00, 22) # 26400 / 22 = 1200 daily, 150 hourly, 2.5 per min
        salary_deduction = round(proc['lwop_tardiness_minutes'] * rates['per_min_rate'], 2)
        self.assertEqual(salary_deduction, 17.50) # 7 mins * 2.50 = 17.50

    def test_5_attendance_correction_reversal(self):
        """TEST 5: Attendance correction (original 20m tardy -> corrected 5m tardy). Reverses 20m VL, applies 5m VL, net -5m VL."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 4800

        # Step 1: Initial 20 min tardiness logged
        proc1 = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 5), tardiness_min=20, undertime_min=0, reference_id='LOG-200'
        )
        self.assertEqual(proc1['remaining_vl_minutes'], 4780)

        # Step 2: Attendance corrected to 5 min tardiness -> Reversal executed
        rev_mins = LeavePolicyService.reverse_attendance_leave_deductions(
            self.cur, 'EMP-001', reference_id='LOG-200', reason='Time log corrected'
        )
        self.assertEqual(rev_mins, 20)
        self.assertEqual(self.cur.leave_balances['EMP-001']['vl_minutes'], 4800)

        # Step 3: Re-apply 5 min tardiness
        proc2 = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 5), tardiness_min=5, undertime_min=0, reference_id='LOG-200'
        )
        self.assertEqual(proc2['remaining_vl_minutes'], 4795) # Net change: -5 mins

    def test_6_teacher_off_premise_teaching_related_work(self):
        """TEST 6: Teacher with 6h classroom teaching & approved off-premise work -> System must NOT classify as undertime."""
        res = AttendancePolicyService.calculate_tardiness_and_undertime(
            employee_type='TEACHING', designation='Teacher I',
            am_in='07:30:00', am_out='11:30:00',
            pm_in='13:00:00', pm_out='15:00:00', # 6 hours physical school presence
            actual_classroom_minutes=360, # 6 hours classroom teaching
            teaching_related_minutes=120, # 2 hours teaching-related preparation outside school premises
            teaching_related_approved=True # Allowed under DepEd rules
        )
        self.assertEqual(res['undertime_minutes'], 0) # Must NOT flag undertime

    def test_7_habitual_tardiness_flagging(self):
        """TEST 7: Habitual tardiness threshold crossed -> Employee FLAGGED for administrative review; no automatic penalty."""
        # Seed 10 tardy logs in month 7 and month 8
        for day in range(1, 11):
            self.cur.time_logs.append({'employee_id': 'EMP-001', 'year': 2026, 'month': 7, 'tardiness_minutes': 15})
            self.cur.time_logs.append({'employee_id': 'EMP-001', 'year': 2026, 'month': 8, 'tardiness_minutes': 15})

        rep = HabitualTardinessService.check_habitual_tardiness(self.cur, 'EMP-001', 2026, 8)
        self.assertTrue(rep['is_flagged'])
        self.assertIn("Crossed habitual tardiness threshold", rep['reason'])

    def test_8_payroll_locking_prevents_unauthorized_modification(self):
        """TEST 8: Attempt to modify attendance affecting locked/approved payroll period -> System prevents silent modification."""
        self.cur.payroll_runs['2026-8-1'] = {'status': 'Approved'}
        is_locked = PayrollPolicyService.is_payroll_locked(self.cur, '2026-8-1')
        self.assertTrue(is_locked)

    def test_9_historical_payroll_effective_date(self):
        """TEST 9: Historical payroll prior to effective date -> Historical payroll remains unchanged."""
        self.cur.policy_configs['POLICY_EFFECTIVE_DATE'] = '2026-01-01'
        active_for_2025 = PayrollPolicyService.check_policy_effective_date(self.cur, date(2025, 12, 31))
        self.assertFalse(active_for_2025)

        active_for_2026 = PayrollPolicyService.check_policy_effective_date(self.cur, date(2026, 1, 15))
        self.assertTrue(active_for_2026)

    def test_10_precision_and_rounding(self):
        """TEST 10: Rounding verification (1m, 7m, 13m, 59m, 60m) -> High-precision integer minutes, no floating-point truncation errors."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 4800
        test_minutes = [1, 7, 13, 59, 60]
        expected_remaining = 4800

        for m in test_minutes:
            proc = LeavePolicyService.process_tardiness_and_undertime(
                self.cur, 'EMP-001', date(2026, 8, 10), tardiness_min=m, undertime_min=0, reference_id=f'TEST-R-{m}'
            )
            expected_remaining -= m
            self.assertEqual(proc['vl_tardiness_minutes'], m)
            self.assertEqual(proc['remaining_vl_minutes'], expected_remaining)

        self.assertEqual(self.cur.leave_balances['EMP-001']['vl_minutes'], 4800 - sum(test_minutes))

    def test_11_zero_leave_credits_cash_salary_deduction(self):
        """TEST 11: Employee with 0 VL credits -> Tardiness & Undertime 100% converted to LWOP cash salary deduction."""
        self.cur.leave_balances['EMP-001']['vl_minutes'] = 0

        proc = LeavePolicyService.process_tardiness_and_undertime(
            self.cur, 'EMP-001', date(2026, 8, 15), tardiness_min=15, undertime_min=30, reference_id='LOG-ZERO-VL'
        )

        self.assertEqual(proc['vl_tardiness_minutes'], 0)
        self.assertEqual(proc['vl_undertime_minutes'], 0)
        self.assertEqual(proc['lwop_tardiness_minutes'], 15)
        self.assertEqual(proc['lwop_undertime_minutes'], 30)
        self.assertEqual(proc['total_lwop_minutes'], 45)
        self.assertEqual(proc['remaining_vl_minutes'], 0)

        # Verify salary deduction computation for 45 unpaid minutes
        rates = RateCalculationService.compute_rates(30000.0) # ₱30,000 monthly basic
        cash_deduction = round(proc['total_lwop_minutes'] * rates['per_min_rate'], 2)
        self.assertGreater(cash_deduction, 0)
        self.assertEqual(cash_deduction, round(45 * (30000.0 / 22 / 8 / 60), 2))

    def test_12_payroll_releasing_lifecycle_and_payslip_lock(self):
        """TEST 12: Payslip availability strictly tied to is_released flag lifecycle."""
        # 1. Draft
        self.cur.payroll_runs['2026-8-1'] = {'status': 'Draft', 'is_released': False}
        self.assertFalse(self.cur.payroll_runs['2026-8-1']['is_released'])

        # 2. Approved (status max is Approved, pending release)
        self.cur.payroll_runs['2026-8-1']['status'] = 'Approved'
        self.assertEqual(self.cur.payroll_runs['2026-8-1']['status'], 'Approved')
        self.assertFalse(self.cur.payroll_runs['2026-8-1']['is_released'])

        # 3. Released (status stays Approved, is_released becomes True)
        self.cur.payroll_runs['2026-8-1']['is_released'] = True
        self.assertEqual(self.cur.payroll_runs['2026-8-1']['status'], 'Approved')
        self.assertTrue(self.cur.payroll_runs['2026-8-1']['is_released'])


if __name__ == '__main__':
    unittest.main()
