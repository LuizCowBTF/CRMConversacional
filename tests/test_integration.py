# tests/test_integration.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import db, User, Lead

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200

def test_admin_login(client):
    response = client.post('/login', data={
        'email': 'admin@crm.com',
        'password': 'admin'
    }, follow_redirects=True)
    assert response.status_code == 200

def test_dashboard_redirects_if_not_logged_in(client):
    response = client.get('/dashboard')
    assert response.status_code == 302

def test_conversas_accessible_after_login(client):
    # Primeiro faz login
    login_response = client.post('/login', data={
        'email': 'admin@crm.com',
        'password': 'admin'
    }, follow_redirects=True)
    
    # Agora acessa conversas com a sessão autenticada
    response = client.get('/conversas', follow_redirects=True)
    assert response.status_code == 200