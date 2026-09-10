from flask import Blueprint, jsonify, request, session
from db import db_cursor
from mysql.connector import Error
from services.policy_engine import AuditService

registry_bp = Blueprint('registry', __name__, url_prefix='/api/registry')

@registry_bp.before_request
def check_role_access():
    role = session.get('user', {}).get('role')
    if role in ['Admin', 'HR', 'HR Officer']:
        return jsonify({'error': 'Unauthorized: Access to Statutory Registry is restricted'}), 403

# ── Global Payheads ──────────────────────────────────────────────────────────

@registry_bp.route('/global_payheads', methods=['GET'])
def get_global_payheads():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM tblglobal_payheads ORDER BY type, name")
            records = cur.fetchall()
            return jsonify(records)
    except Error as e:
        return jsonify({'error': str(e)}), 500

@registry_bp.route('/global_payheads', methods=['POST'])
def add_global_payhead():
    data = request.json
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    amount = data.get('amount', 0)
    p_type = data.get('type') # 'Earning' or 'Deduction'
    mode   = data.get('mode', 'Amount')
    pct    = data.get('percentage_value', 0)

    if not name or amount is None or not p_type:
        return jsonify({'error': 'Missing parameters'}), 400
    
    try:
        with db_cursor() as (conn, cur):
            # Duplicate check
            cur.execute("SELECT id FROM tblglobal_payheads WHERE name = %s", (name,))
            if cur.fetchone():
                return jsonify({'error': f'Payhead with name "{name}" already exists.'}), 400

            cur.execute(
                "INSERT INTO tblglobal_payheads (name, description, amount, type, mode, percentage_value) VALUES (%s, %s, %s, %s, %s, %s)",
                (name, description, float(amount), p_type, mode, float(pct))
            )
            conn.commit()
            return jsonify({'success': True, 'id': cur.lastrowid})
    except Error as e:
        return jsonify({'error': str(e)}), 500

@registry_bp.route('/global_payheads/<int:id>', methods=['DELETE'])
def delete_global_payhead(id):
    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM tblglobal_payheads WHERE id = %s", (id,))
            conn.commit()
            return jsonify({'success': True})
    except Error as e:
        return jsonify({'error': str(e)}), 500


# ── Statutory Registry ────────────────────────────────────────────────────────

@registry_bp.route('/statutory', methods=['GET'])
def get_statutory_config():
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM tblstatutory_registry ORDER BY config_key")
            records = cur.fetchall()
            return jsonify(records)
    except Error as e:
        return jsonify({'error': str(e)}), 500

@registry_bp.route('/statutory', methods=['PUT'])
def update_statutory_config():
    data = request.json # Expecting list of {key, value, mode}
    if not isinstance(data, list):
        return jsonify({'error': 'Data must be a list of config items'}), 400
    
    try:
        with db_cursor() as (conn, cur):
            for item in data:
                key = item.get('config_key')
                val = item.get('config_value')
                mode = item.get('config_mode', 'Percentage')
                if key and val is not None:
                    cur.execute(
                        "UPDATE tblstatutory_registry SET config_value = %s, config_mode = %s WHERE config_key = %s",
                        (str(val), mode, key)
                    )
            AuditService.log_action(cur, 'STATUTORY_UPDATED', user_name=session.get('user', {}).get('name', 'Unknown'), target_table='tblstatutory_registry')
            conn.commit()
            return jsonify({'success': True})
    except Error as e:
        return jsonify({'error': str(e)}), 500

@registry_bp.route('/statutory', methods=['POST'])
def add_statutory_rule():
    data = request.json
    key   = data.get('config_key', '').strip().upper()
    val   = data.get('config_value', '')
    mode  = data.get('config_mode', 'Percentage')
    desc  = data.get('description', '')

    if not key or val is None:
        return jsonify({'error': 'Key and Value are required'}), 400
    
    try:
        with db_cursor() as (conn, cur):
            # Duplicate check
            cur.execute("SELECT config_key FROM tblstatutory_registry WHERE config_key = %s", (key,))
            if cur.fetchone():
                return jsonify({'error': f'Statutory rule "{key}" already exists.'}), 400

            cur.execute(
                "INSERT INTO tblstatutory_registry (config_key, config_value, config_mode, description) VALUES (%s, %s, %s, %s)",
                (key, str(val), mode, desc)
            )
            conn.commit()
            return jsonify({'success': True})
    except Error as e:
        return jsonify({'error': str(e)}), 500

@registry_bp.route('/statutory/<string:key>', methods=['DELETE'])
def delete_statutory_rule(key):
    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM tblstatutory_registry WHERE config_key = %s", (key,))
            conn.commit()
            return jsonify({'success': True})
    except Error as e:
        return jsonify({'error': str(e)}), 500
