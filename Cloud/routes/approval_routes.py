from flask import Blueprint, jsonify, request, session
from db import db_cursor
from services.policy_engine import AuditService, LeavePolicyService
from datetime import datetime

approval_bp = Blueprint('approval_bp', __name__)

@approval_bp.route('/api/approvals', methods=['GET'])
def get_approvals():
    user = session.get('user', {})
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    role = user.get('role', '')
    status_filter = request.args.get('status', 'Pending').strip()
    doc_type_filter = request.args.get('doc_type', '').strip()

    try:
        with db_cursor() as (conn, cur):
            query = """
                SELECT a.*, 
                       p.year AS pr_year, p.month AS pr_month, p.half AS pr_half, p.status AS pr_status,
                       l.leave_type AS lv_type, l.leave_date AS lv_date, l.reason AS lv_reason, l.employee_id AS lv_emp_id, l.attachment AS lv_attachment
                FROM tblapprovals a
                LEFT JOIN tblpayroll p ON a.DocType='Payroll' AND a.DocNumber=p.period_key
                LEFT JOIN tblleaves l ON a.DocType='Leave' AND a.DocNumber=CAST(l.id AS CHAR)
                WHERE 1=1
            """
            params = []

            # Role-tailored filtering
            if role in ['Principal']:
                query += " AND a.ApproverRole IN ('Principal', 'Admin') AND a.DocType='Payroll'"
            elif role in ['HR', 'HR Officer']:
                query += " AND a.ApproverRole IN ('HR', 'HR Officer') AND a.DocType='Leave'"
            elif role in ['Finance', 'Finance Officer']:
                query += " AND a.DocType='Payroll'"
            elif role in ['Admin', 'Auditor']:
                pass # Admin and Auditor can see all approvals
            else:
                query += " AND a.ApproverRole = %s"
                params.append(role)

            if status_filter and status_filter.lower() != 'all':
                query += " AND a.ApprovalStatus = %s"
                params.append(status_filter)

            if doc_type_filter and doc_type_filter.lower() != 'all':
                query += " AND a.DocType = %s"
                params.append(doc_type_filter)

            query += " ORDER BY a.CreatedAt DESC, a.ApprovalID DESC"

            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            approvals = []
            for r in rows:
                item = {
                    'ApprovalID': r['ApprovalID'],
                    'DocType': r['DocType'],
                    'DocNumber': r['DocNumber'],
                    'ApprovalStatus': r['ApprovalStatus'],
                    'ApproverRole': r['ApproverRole'],
                    'ApproverID': r['ApproverID'],
                    'RequesterID': r['RequesterID'],
                    'Title': r['Title'],
                    'Remarks': r['Remarks'],
                    'ApprovedAt': r['ApprovedAt'].strftime('%b %d, %Y %I:%M %p') if r['ApprovedAt'] else None,
                    'CreatedAt': r['CreatedAt'].strftime('%b %d, %Y %I:%M %p') if r['CreatedAt'] else None
                }

                # Attach domain payload details for rich rendering
                if r['DocType'] == 'Payroll':
                    cur.execute("""
                        SELECT COUNT(*) as emp_count, SUM(total_gross) as gross_pay, SUM(net_pay) as net_pay
                        FROM tblpayroll_details WHERE period_key=%s
                    """, (r['DocNumber'],))
                    sum_row = cur.fetchone() or {}
                    item['details'] = {
                        'year': r['pr_year'],
                        'month': r['pr_month'],
                        'half': r['pr_half'],
                        'emp_count': sum_row.get('emp_count') or 0,
                        'gross_pay': float(sum_row.get('gross_pay') or 0),
                        'net_pay': float(sum_row.get('net_pay') or 0)
                    }
                elif r['DocType'] == 'Leave':
                    emp_name = r['RequesterID'] or 'Employee'
                    if r['lv_emp_id']:
                        cur.execute("SELECT CONCAT(first_name, ' ', last_name) AS fullname FROM tblemployee WHERE employee_id=%s", (r['lv_emp_id'],))
                        emp_rec = cur.fetchone()
                        if emp_rec and emp_rec['fullname']:
                            emp_name = emp_rec['fullname']

                    import json
                    attachments_list = []
                    raw_att = r['lv_attachment']
                    if raw_att:
                        try:
                            parsed = json.loads(raw_att)
                            if isinstance(parsed, list):
                                attachments_list = parsed
                            elif isinstance(parsed, str):
                                attachments_list = [parsed]
                        except Exception:
                            attachments_list = [raw_att]

                    item['details'] = {
                        'employee_id': r['lv_emp_id'],
                        'employee_name': emp_name,
                        'leave_type': r['lv_type'],
                        'leave_date': str(r['lv_date']) if r['lv_date'] else '',
                        'reason': r['lv_reason'] or r['Remarks'],
                        'attachment': attachments_list[0] if attachments_list else None,
                        'attachments': attachments_list
                    }

                approvals.append(item)

            return jsonify({'success': True, 'approvals': approvals})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@approval_bp.route('/api/approvals/<int:approval_id>/action', methods=['POST'])
def approval_action(approval_id):
    user = session.get('user', {})
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    role = user.get('role', '')
    user_name = user.get('name', 'Approver')
    data = request.json or {}
    action = data.get('action') # 'Approved' or 'Rejected'
    remarks = data.get('remarks', '').strip()

    if action not in ['Approved', 'Rejected']:
        return jsonify({'error': 'Action must be Approved or Rejected'}), 400

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM tblapprovals WHERE ApprovalID=%s", (approval_id,))
            approval = cur.fetchone()
            if not approval:
                return jsonify({'error': 'Approval item not found'}), 404

            doc_type = approval['DocType']
            doc_number = approval['DocNumber']

            # Update tblapprovals record
            cur.execute("""
                UPDATE tblapprovals
                SET ApprovalStatus=%s, ApproverID=%s, Remarks=%s, ApprovedAt=NOW()
                WHERE ApprovalID=%s
            """, (action, user_name, remarks, approval_id))

            # Domain specific execution
            if doc_type == 'Payroll':
                cur.execute(
                    "UPDATE tblpayroll SET status=%s, remarks=%s, approved_by=%s, approved_at=NOW() WHERE period_key=%s",
                    (action, remarks, user_name, doc_number)
                )
                audit_tag = 'PAYROLL_APPROVED' if action == 'Approved' else 'PAYROLL_REJECTED'
                AuditService.log_action(cur, audit_tag, user_name=user_name, target_table='tblpayroll', new_value=doc_number)

            elif doc_type == 'Leave':
                leave_id = int(doc_number)
                cur.execute("SELECT * FROM tblleaves WHERE id=%s", (leave_id,))
                leave = cur.fetchone()
                if leave:
                    old_status = leave['status']
                    emp_id = leave['employee_id']
                    leave_date_str = str(leave['leave_date'])
                    leave_type = leave['leave_type']

                    cur.execute("""
                        UPDATE tblleaves 
                        SET status=%s, reviewed_by=%s, reviewed_at=NOW(), reason=COALESCE(NULLIF(%s, ''), reason)
                        WHERE id=%s
                    """, (action, user_name, remarks, leave_id))

                    if action == 'Approved' and old_status != 'Approved':
                        bal = LeavePolicyService.get_balance(cur, emp_id)
                        target_key = 'vl_minutes' if leave_type == 'VL' else 'sl_minutes'
                        curr_mins = bal.get(target_key, 0)
                        new_mins = max(0, curr_mins - 480)

                        cur.execute(f"UPDATE tblleave_balances SET {target_key}=%s WHERE employee_id=%s", (new_mins, emp_id))
                        cur.execute("""
                            INSERT INTO tblleave_transactions
                            (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                            VALUES (%s, %s, %s, 480, 'DEDUCTION', 'LEAVE_APPLICATION', %s, %s, %s)
                        """, (emp_id, leave_date_str, leave_type, f"LEAVE-{leave_id}", f"Approved {leave_type} leave on {leave_date_str}", user_name))

                        AuditService.log_action(
                            cur, action='LEAVE_APPROVED', employee_id=emp_id, user_name=user_name,
                            target_table='tblleaves', target_id=str(leave_id),
                            old_value=f"Status: {old_status}", new_value=f"Status: Approved (-480m {leave_type})",
                            reason=remarks or leave.get('reason') or 'Leave Approved'
                        )
                    elif old_status == 'Approved' and action == 'Rejected':
                        bal = LeavePolicyService.get_balance(cur, emp_id)
                        target_key = 'vl_minutes' if leave_type == 'VL' else 'sl_minutes'
                        curr_mins = bal.get(target_key, 0)
                        new_mins = curr_mins + 480

                        cur.execute(f"UPDATE tblleave_balances SET {target_key}=%s WHERE employee_id=%s", (new_mins, emp_id))
                        cur.execute("""
                            INSERT INTO tblleave_transactions
                            (employee_id, date, leave_type, minutes, transaction_type, source, reference_id, remarks, created_by)
                            VALUES (%s, %s, %s, 480, 'ACCRUAL', 'LEAVE_REVERSAL', %s, %s, %s)
                        """, (emp_id, leave_date_str, leave_type, f"REV-LEAVE-{leave_id}", f"Refunded rejected {leave_type} leave on {leave_date_str}", user_name))

                        AuditService.log_action(
                            cur, action='LEAVE_REJECTED', employee_id=emp_id, user_name=user_name,
                            target_table='tblleaves', target_id=str(leave_id),
                            old_value="Status: Approved", new_value="Status: Rejected (+480m refunded)",
                            reason=remarks or 'Leave Rejected'
                        )

            conn.commit()
            return jsonify({'success': True, 'message': f'Document {doc_number} successfully {action.lower()}.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
