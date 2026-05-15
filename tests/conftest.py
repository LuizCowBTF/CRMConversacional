# tests/conftest.py
import os
import sys
import pytest

# Adicionar o diretório raiz ao path do Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar diretamente do app.py
from app import app as flask_app, db
from app import User, Lead, Message

@pytest.fixture
def app():
    """Fixture para criar uma instância da aplicação para testes"""
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['LOGIN_DISABLED'] = False
    flask_app.config['SERVER_NAME'] = 'localhost'
    
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.drop_all()

@pytest.fixture
def client(app):
    """Fixture para o client de testes"""
    return app.test_client()

@pytest.fixture
def runner(app):
    """Fixture para o runner de comandos CLI"""
    return app.test_cli_runner()

@pytest.fixture
def auth_client(client, app):
    """Fixture para client autenticado"""
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        if not user:
            user = User(
                name='Test User',
                email='test@example.com',
                role='consultor'
            )
            user.set_password('test123')
            db.session.add(user)
            db.session.commit()
    
    client.post('/login', data={
        'email': 'test@example.com',
        'password': 'test123'
    })
    
    return client
