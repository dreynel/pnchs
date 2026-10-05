from flask import Blueprint, jsonify, request, session
from db import db_cursor
from services.notification_service import NotificationService

notification_bp = Blueprint('notification', __name__, url_prefix='/api/notifications')

@notification_bp.route('', methods=['GET'])
def get_notifications():
    """Fetch notifications validated and filtered for the current logged-in user role or account."""
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized: Please log in'}), 401

    user_id = user.get('id')
    role = user.get('role', '')
    employee_id = user.get('employee_id')

    try:
        with db_cursor() as (conn, cur):
            data = NotificationService.get_user_notifications(
                cur, user_id=user_id, role=role, employee_id=employee_id
            )
            return jsonify({
                'success': True,
                'role': role,
                'user_id': user_id,
                'unread_count': data['unread_count'],
                'notifications': data['notifications']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notification_bp.route('/<int:notif_id>/read', methods=['POST'])
def mark_read(notif_id):
    """Mark a single notification as read for the current user."""
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = user.get('id')
    user_name = user.get('name') or user.get('username') or 'User'

    try:
        with db_cursor(commit=True) as (conn, cur):
            NotificationService.mark_as_read(cur, notif_id, user_id=user_id, user_name=user_name)
            return jsonify({'success': True, 'message': 'Notification marked as read.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notification_bp.route('/read-all', methods=['POST'])
def mark_all_read():
    """Mark all notifications matching user role or account as read."""
    user = session.get('user')
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = user.get('id')
    role = user.get('role', '')
    employee_id = user.get('employee_id')
    user_name = user.get('name') or user.get('username') or 'User'

    try:
        with db_cursor(commit=True) as (conn, cur):
            NotificationService.mark_all_read(
                cur, user_id=user_id, role=role, employee_id=employee_id, user_name=user_name
            )
            return jsonify({'success': True, 'message': 'All notifications marked as read.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notification_bp.route('/audit', methods=['GET'])
def get_audit():
    """Administrative endpoint to audit notification dispatch and delivery history."""
    user = session.get('user')
    if not user or user.get('role') not in ['Admin', 'Administrator', 'Principal', 'HR', 'HR Officer']:
        return jsonify({'error': 'Unauthorized: Admin or Principal access required.'}), 403

    role_filter = request.args.get('role')
    limit = int(request.args.get('limit', 100))

    try:
        with db_cursor() as (conn, cur):
            trail = NotificationService.get_audit_trail(cur, limit=limit, role_filter=role_filter)
            return jsonify({'success': True, 'audit_trail': trail})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@notification_bp.route('/dispatch', methods=['POST'])
def dispatch_announcement():
    """Allows Admin, Principal, or HR to broadcast an institutional notification."""
    user = session.get('user')
    if not user or user.get('role') not in ['Admin', 'Administrator', 'Principal', 'HR', 'HR Officer']:
        return jsonify({'error': 'Unauthorized to dispatch notifications.'}), 403

    data = request.json or {}
    title = (data.get('title') or '').strip()
    message = (data.get('message') or '').strip()
    target_role = data.get('target_role') or 'ALL'
    target_emp = data.get('target_employee_id')
    category = data.get('category') or 'System'
    icon = data.get('icon') or '📢'
    link_url = data.get('link_url')
    link_label = data.get('link_label')

    if not title or not message:
        return jsonify({'error': 'Title and message are required.'}), 400

    sender = user.get('name') or user.get('username') or 'Administrator'

    try:
        with db_cursor(commit=True) as (conn, cur):
            notif_ids = NotificationService.create_notification(
                cur,
                title=title,
                message=message,
                category=category,
                target_role=target_role if not target_emp else None,
                target_employee_id=target_emp,
                link_url=link_url,
                link_label=link_label,
                icon=icon,
                sender_name=sender
            )
            if not notif_ids:
                return jsonify({
                    'error': 'Notification rejected: Does not match strictly permitted notification whitelist (Accounting: Payroll status approval, HR: Leave management status approval, or to all: leave application approval status, Payroll Run done, payslip can be viewed + DTR).'
                }), 400
            return jsonify({'success': True, 'notification_ids': notif_ids, 'message': 'Notification dispatched.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
