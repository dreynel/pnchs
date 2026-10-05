import json
from datetime import datetime
from services.policy_engine import AuditService

class NotificationService:
    @classmethod
    def is_permitted_notification(cls, title, category, target_role, target_employee_id=None):
        """
        Enforces strict compliance with notification policy:
        1. Accounting : Payroll status approval
        2. HR : Leave management status approval
        3. to all : leave application approval status
        4. to all : Payroll Run done
        5. to all : payslip can be viewed + DTR
        """
        title_norm = (title or '').strip().lower()
        cat_norm = (category or '').strip().lower()
        role_norm = (target_role or '').strip().lower()

        # 1. Accounting: Payroll status approval
        if role_norm in ['accounting', 'finance', 'finance officer'] and cat_norm == 'payroll':
            if any(k in title_norm for k in ['payroll status approval', 'payroll approved', 'payroll rejected', 'payroll run approved', 'payroll run rejected']):
                return True

        # 2. HR: Leave management status approval
        if role_norm in ['hr', 'hr officer'] and cat_norm == 'leave':
            if any(k in title_norm for k in ['leave management status approval', 'leave application', 'leave request', 'new leave application']):
                return True

        # 3. to all: leave application approval status
        if cat_norm == 'leave' and (role_norm == 'all' or target_employee_id is not None):
            if any(k in title_norm for k in ['leave application approval status', 'leave application approved', 'leave application rejected', 'leave approved', 'leave rejected', 'leave status']):
                return True

        # 4. to all: Payroll Run done
        if cat_norm == 'payroll' and role_norm == 'all':
            if any(k in title_norm for k in ['payroll run done', 'payroll run completed']):
                return True

        # 5. to all: payslip can be viewed + DTR
        if cat_norm == 'payroll' and role_norm == 'all':
            if any(k in title_norm for k in ['payslip can be viewed + dtr', 'payslip released', 'payslip & dtr', 'payslips released']):
                return True

        return False

    @classmethod
    def create_notification(cls, cur, title, message, category='System', target_role=None,
                            target_user_id=None, target_employee_id=None, link_url=None,
                            link_label=None, icon='🔔', priority='Normal', sender_name='System'):
        """
        Creates a new notification strictly validated against the whitelisted event matrix:
        - Accounting : Payroll status approval
        - HR : Leave management status approval
        - to all : leave application approval status
        - to all : Payroll Run done
        - to all : payslip can be viewed + DTR
        """
        roles = target_role if isinstance(target_role, (list, tuple)) else [target_role]
        created_ids = []

        for role in roles:
            if not cls.is_permitted_notification(title, category, role, target_employee_id):
                print(f"[POLICY] Notification rejected: Title='{title}', Category='{category}', Role='{role}' outside strict whitelist.")
                continue

            # Normalize role label
            normalized_role = role
            if role in ['Accounting', 'Finance', 'Finance Officer']:
                normalized_role = 'Accounting'
            elif role in ['HR', 'HR Officer']:
                normalized_role = 'HR'

            cur.execute("""
                INSERT INTO tblnotifications 
                (sender_name, target_role, target_user_id, target_employee_id, category, title, message, link_url, link_label, icon, priority)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (sender_name, normalized_role, target_user_id, target_employee_id, category, title, message, link_url, link_label, icon, priority))
            
            notif_id = cur.lastrowid
            created_ids.append(notif_id)

            # Audit log the dispatch
            audit_payload = {
                'notification_id': notif_id,
                'title': title,
                'target_role': normalized_role,
                'target_user_id': target_user_id,
                'target_employee_id': target_employee_id,
                'category': category,
                'sender': sender_name
            }
            try:
                AuditService.log_action(
                    cur, 
                    action='NOTIFICATION_DISPATCHED', 
                    user_name=sender_name, 
                    target_table='tblnotifications', 
                    target_id=notif_id,
                    new_value=json.dumps(audit_payload)
                )
            except Exception as e:
                print(f"[AUDIT] Audit log error on notification dispatch: {e}")

        return created_ids

    @staticmethod
    def get_user_notifications(cur, user_id, role, employee_id=None, limit=30):
        """
        Fetches notifications strictly adhering to recipient scoping:
        - Accounting users: Accounting (Payroll status approval) + ALL
        - HR users: HR (Leave management status approval) + ALL
        - Everyone: ALL (leave application approval status, Payroll Run done, payslip can be viewed + DTR)
                    + direct target_employee_id notifications
        """
        query = """
            SELECT n.id, n.sender_name, n.target_role, n.target_user_id, n.target_employee_id,
                   n.category, n.title, n.message, n.link_url, n.link_label, n.icon, n.priority,
                   n.created_at,
                   CASE WHEN nr.id IS NOT NULL THEN 1 ELSE 0 END AS is_read,
                   nr.read_at
            FROM tblnotifications n
            LEFT JOIN tblnotification_reads nr ON n.id = nr.notification_id AND nr.user_id = %s
            WHERE (
                (n.target_role = 'ALL')
                OR (%s IS NOT NULL AND n.target_employee_id = %s)
                OR (n.target_role = 'Accounting' AND %s IN ('Accounting', 'Finance', 'Finance Officer'))
                OR (n.target_role = 'HR' AND %s IN ('HR', 'HR Officer'))
            )
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT %s
        """
        cur.execute(query, (
            user_id, employee_id, employee_id, role, role, limit
        ))
        rows = cur.fetchall()

        notifications = []
        unread_count = 0
        now = datetime.now()

        for r in rows:
            is_r = bool(r['is_read'])
            if not is_r:
                unread_count += 1
            
            created_dt = r['created_at']
            time_ago = ''
            if created_dt:
                diff = now - created_dt
                if diff.days > 0:
                    time_ago = f"{diff.days}d ago"
                elif diff.seconds >= 3600:
                    time_ago = f"{diff.seconds // 3600}h ago"
                elif diff.seconds >= 60:
                    time_ago = f"{diff.seconds // 60}m ago"
                else:
                    time_ago = "Just now"

            notifications.append({
                'id': r['id'],
                'sender_name': r['sender_name'],
                'target_role': r['target_role'],
                'category': r['category'],
                'title': r['title'],
                'message': r['message'],
                'link_url': r['link_url'],
                'link_label': r['link_label'],
                'icon': r['icon'],
                'priority': r['priority'],
                'is_read': is_r,
                'created_at': created_dt.strftime('%b %d, %Y %I:%M %p') if created_dt else '',
                'time_ago': time_ago
            })

        return {
            'unread_count': unread_count,
            'notifications': notifications
        }

    @staticmethod
    def mark_as_read(cur, notification_id, user_id, user_name='User'):
        """Marks a notification as read specifically for this user account."""
        cur.execute("""
            INSERT INTO tblnotification_reads (notification_id, user_id, read_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (notification_id, user_id) DO NOTHING
        """, (notification_id, user_id))

        try:
            AuditService.log_action(
                cur,
                action='NOTIFICATION_READ',
                user_name=user_name,
                target_table='tblnotification_reads',
                target_id=notification_id
            )
        except Exception:
            pass
        return True

    @staticmethod
    def mark_all_read(cur, user_id, role, employee_id=None, user_name='User'):
        """Marks all eligible notifications for this user as read."""
        cur.execute("""
            INSERT INTO tblnotification_reads (notification_id, user_id, read_at)
            SELECT n.id, %s, NOW()
            FROM tblnotifications n
            WHERE (
                (n.target_role = 'ALL')
                OR (%s IS NOT NULL AND n.target_employee_id = %s)
                OR (n.target_role = 'Accounting' AND %s IN ('Accounting', 'Finance', 'Finance Officer'))
                OR (n.target_role = 'HR' AND %s IN ('HR', 'HR Officer'))
            )
            ON CONFLICT (notification_id, user_id) DO NOTHING
        """, (user_id, employee_id, employee_id, role, role))

        try:
            AuditService.log_action(
                cur,
                action='NOTIFICATIONS_CLEARED',
                user_name=user_name,
                target_table='tblnotification_reads'
            )
        except Exception:
            pass
        return True

    @staticmethod
    def get_audit_trail(cur, limit=100, role_filter=None):
        """
        Administrative audit view of all dispatched notifications, target roles/accounts,
        and read receipt metrics.
        """
        query = """
            SELECT n.id, n.sender_name, n.target_role, n.target_user_id, n.target_employee_id,
                   n.category, n.title, n.message, n.priority, n.created_at,
                   COUNT(nr.id) AS read_count
            FROM tblnotifications n
            LEFT JOIN tblnotification_reads nr ON n.id = nr.notification_id
            WHERE 1=1
        """
        params = []
        if role_filter and role_filter != 'ALL':
            query += " AND n.target_role = %s"
            params.append(role_filter)

        query += " GROUP BY n.id ORDER BY n.created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        trail = []
        for r in rows:
            trail.append({
                'id': r['id'],
                'sender': r['sender_name'],
                'target_role': r['target_role'] or 'Direct Account',
                'target_user_id': r['target_user_id'],
                'target_employee_id': r['target_employee_id'],
                'category': r['category'],
                'title': r['title'],
                'message': r['message'],
                'priority': r['priority'],
                'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M:%S') if r['created_at'] else '',
                'read_count': int(r['read_count'] or 0)
            })
        return trail
