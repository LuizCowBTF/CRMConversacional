# tests/test_basic.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import db
from app import User, Lead, Message

def test_index_redirects_to_login(client):
    response = client.get('/')
    assert response.status_code == 302
    assert '/login' in response.location

def test_login_page_renders(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b'CRM' in response.data or b'Conversacional' in response.data

def test_user_creation():
    # Usando weekly_quota (campo correto)
    user = User(
        name='Usuario Teste Unidade',
        email='teste_unidade@crm.com',
        role='consultor',
        weekly_quota=50
    )
    user.set_password('123456')

    assert user.name == 'Usuario Teste Unidade'
    assert user.email == 'teste_unidade@crm.com'
    assert user.role == 'consultor'
    assert user.weekly_quota == 50
    assert user.check_password('123456') == True

def test_lead_creation():
    lead = Lead(
        name='Lead Teste Unidade',
        phone='11999999999',
        email='lead_unidade@teste.com',
        stage='em_conversacao',
        budget=5000
    )

    assert lead.name == 'Lead Teste Unidade'
    assert lead.phone == '11999999999'
    assert lead.stage == 'em_conversacao'

def test_message_creation():
    # Usando body (campo correto)
    message = Message(
        body='Mensagem de teste unitario',
        direction='out',
        kind='text'
    )

    assert message.body == 'Mensagem de teste unitario'
    assert message.direction == 'out'