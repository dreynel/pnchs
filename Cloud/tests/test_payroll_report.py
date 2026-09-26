import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user'] = {
                'id': 1,
                'name': 'Principal User',
                'username': 'principal',
                'role': 'Principal'
            }
        yield client


def test_payroll_report_page_render(client):
    res = client.get('/payroll_report')
    assert res.status_code == 200
    assert b'payroll_report.html' in res.data or b'Payroll Report' in res.data


def test_payroll_report_run_mode(client):
    res = client.get('/api/payroll/report?date_mode=run&year=2026&month=3&half=1')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'employees' in data
    assert 'summary' in data
    assert isinstance(data['employees'], list)


def test_payroll_report_data_alias(client):
    res = client.get('/api/payroll/report_data?key=2026-3-1')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'employees' in data


def test_payroll_report_month_mode(client):
    res = client.get('/api/payroll/report?date_mode=month&year=2026&month=3')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'summary' in data


def test_payroll_report_year_mode(client):
    res = client.get('/api/payroll/report?date_mode=year&year=2026')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'summary' in data


def test_payroll_report_range_mode(client):
    res = client.get('/api/payroll/report?date_mode=range&date_from=2026-01-01&date_to=2026-12-31')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'summary' in data


def test_payroll_report_daily_mode(client):
    res = client.get('/api/payroll/report?date_mode=daily&date=2026-03-15')
    assert res.status_code == 200
    data = res.get_json()
    assert 'period' in data
    assert 'summary' in data
