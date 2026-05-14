"""
CRM Conversacional - Sistema completo
Stack: Flask + SQLAlchemy + SQLite + Bootstrap 5
Foco: Velocidade, simplicidade, distribuição inteligente, pipeline conversacional
"""

import os
import re
import uuid
import mimetypes
from datetime import datetime, timedelta, date
from functools import wraps
from collections import defaultdict

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, jsonify, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func, desc

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'crm-conversacional-secret-key-change-in-prod'
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_INSTANCE_DIR = os.path.join(_BASE_DIR, 'instance')
_UPLOAD_DIR = os.path.join(_BASE_DIR, 'static', 'uploads')
os.makedirs(_INSTANCE_DIR, exist_ok=True)
os.makedirs(_UPLOAD_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(_INSTANCE_DIR, 'crm.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = _UPLOAD_DIR
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB
db = SQLAlchemy(app)

# Estágios do pipeline (conforme spec)
PIPELINE_STAGES = [
    ('mensagem_enviada', 'Mensagem Enviada'),
    ('em_conversacao', 'Em Conversação'),
    ('cotacao_enviada', 'Cotação Enviada'),
    ('proposta_digitada', 'Proposta Digitada'),
    ('em_analise', 'Em Análise'),
    ('aguardando_pagamento', 'Aguardando Pagamento'),
    ('plano_fechado', 'Plano Fechado'),
    ('lead_frio', 'Lead Frio'),
]
STAGE_LABELS = dict(PIPELINE_STAGES)
STAGE_SHORT = {
    'mensagem_enviada': 'Msg.E',
    'em_conversacao':   'Em.Cv',
    'cotacao_enviada':  'Ct.E',
    'proposta_digitada':'Pp.D',
    'em_analise':       'Em.A',
    'aguardando_pagamento': 'Ag.P',
    'plano_fechado':    'Pl.F',
    'lead_frio':        'L.Fr',
}

# Etapas que disparam formulário obrigatório
STAGE_FORMS = {
    'cotacao_enviada':      ['operadora', 'subproduto', 'valor', 'vidas', 'bairro'],
    'proposta_digitada':    ['confirm_quotation'],
    'em_analise':           ['confirm_quotation'],
    'aguardando_pagamento': ['data_boleto', 'data_vigencia'],
    'plano_fechado':        [],
}

# Roles disponíveis no sistema
ROLES = ['master', 'admin', 'coordenador', 'lider', 'consultor']
ROLE_LABEL = {
    'master': 'Master',
    'admin': 'Administrador',
    'coordenador': 'Coordenador',
    'lider': 'Líder de Equipe',
    'consultor': 'Consultor',
}

# Lista oficial de planos/operadoras
PLANOS_OFICIAIS = [
    # ADESÃO
    ('ADESÃO', 'Amil'), ('ADESÃO', 'Ampla'), ('ADESÃO', 'Assim'), ('ADESÃO', 'Cemeru'),
    ('ADESÃO', 'Hapvida GNDI'), ('ADESÃO', 'Klini'), ('ADESÃO', 'Plamer'), ('ADESÃO', 'Samoc'),
    ('ADESÃO', 'SulAmérica'), ('ADESÃO', 'Unimed'), ('ADESÃO', 'Ommed'),
    # PF
    ('PF', 'Assim'), ('PF', 'Gndi'), ('PF', 'Leve'), ('PF', 'MedSênior'),
    ('PF', 'PreventSênior'), ('PF', 'Odonto Amil'), ('PF', 'Odonto SulAmerica'),
    ('PF', 'Samoc'),
    # PME
    ('PME', 'Amil'), ('PME', 'Amil 30-99'), ('PME', 'Assim'), ('PME', 'Assim 30-99'),
    ('PME', 'Bradesco'), ('PME', 'Gndi'), ('PME', 'Klini'), ('PME', 'Leve'),
    ('PME', 'MedSênior'), ('PME', 'Porto Seguro'), ('PME', 'SulAmerica'),
    ('PME', 'Unimed Ferj'), ('PME', 'Odonto Amil'), ('PME', 'Odonto Assim'),
    ('PME', 'Odonto Bradesco'), ('PME', 'Odonto SulAmerica'), ('PME', 'Cemeru'),
    ('PME', 'NotreDame'), ('PME', 'Alice'),
]

# ----------------------------------------------------------------------------
# MODELS
# ----------------------------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='consultor')  # master | admin | coordenador | lider | consultor
    weekly_quota = db.Column(db.Integer, default=20)
    is_online = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    is_blocked = db.Column(db.Boolean, default=False)  # bloqueado por master/coordenador (não recebe lead, não envia msg)
    blocked_reason = db.Column(db.String(255), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Hierarquia: cada usuário aponta para seu superior direto
    # consultor → líder; líder → coordenador; coordenador → master; etc.
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    manager = db.relationship('User', remote_side=[id], backref='subordinados')

    favorite_templates = db.Column(db.String(255), default='')  # ids separados por vírgula (max 3)
    favorite_followups = db.Column(db.String(255), default='')  # ids separados por vírgula (max 5)

    # Cadência pessoal de follow-up (preferências do corretor)
    cadence_per_day = db.Column(db.Integer, default=2)        # quantos FUPs por dia (1-4)
    cadence_days = db.Column(db.Integer, default=3)           # quantos dias mantém cadência (1-3)
    cadence_interval_hours = db.Column(db.Integer, default=3) # intervalo mínimo entre FUPs no mesmo dia

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def fav_template_ids(self):
        return [int(x) for x in self.favorite_templates.split(',') if x.strip().isdigit()]

    @property
    def fav_followup_ids(self):
        return [int(x) for x in self.favorite_followups.split(',') if x.strip().isdigit()]


class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    company = db.Column(db.String(120))
    source = db.Column(db.String(60), default='manual')  # origem (OCULTA para consultor se não foi ele que cadastrou)
    source_visible_to_consultor = db.Column(db.Boolean, default=False)  # true só se consultor criou
    stage = db.Column(db.String(40), default='mensagem_enviada')
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    tags = db.Column(db.String(255), default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime)
    last_inbound_at = db.Column(db.DateTime)
    last_outbound_at = db.Column(db.DateTime)
    sent_without_response = db.Column(db.Integer, default=0)

    # Qualificação inicial (vem do form/API)
    tem_cnpj = db.Column(db.Boolean)  # True = PME, False = PF
    categoria = db.Column(db.String(20))  # PF | PME | ADESAO (derivado de tem_cnpj quando aplicável)
    vidas = db.Column(db.Integer)  # quantas vidas (pode vir nulo da origem)
    preferencia_contato = db.Column(db.String(20), default='whatsapp')  # whatsapp | email | telefone

    # Negócio
    budget = db.Column(db.Float, default=0.0)
    moved_to_remarketing_at = db.Column(db.DateTime)
    fups_sent_today = db.Column(db.Integer, default=0)
    fups_last_date = db.Column(db.Date)

    # Quando entrou na etapa atual (resgatado pelo dashboard)
    stage_entered_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', backref='leads')

    @property
    def stage_label(self):
        return STAGE_LABELS.get(self.stage, self.stage)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    @property
    def initial(self):
        return (self.name or 'L')[0].upper()

    @property
    def sla_minutes(self):
        """tempo desde a última mensagem inbound não respondida"""
        if not self.last_inbound_at:
            return None
        if self.last_outbound_at and self.last_outbound_at > self.last_inbound_at:
            return None
        delta = datetime.utcnow() - self.last_inbound_at
        return int(delta.total_seconds() // 60)


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # null = inbound do lead
    direction = db.Column(db.String(10))  # 'in' (do lead) | 'out' (do consultor)
    body = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(20), default='text')  # text | template | followup | snippet | note
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship('Lead', backref=db.backref('messages', order_by='Message.created_at'))
    user = db.relationship('User')


class Template(db.Model):
    __tablename__ = 'templates'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), default='geral')
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)


class FollowUp(db.Model):
    __tablename__ = 'followups'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    days_after = db.Column(db.Integer, default=1)  # disparo automático após X dias sem resposta
    sequence = db.Column(db.Integer, default=1)  # FUP 1, 2, 3...
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)


class Snippet(db.Model):
    __tablename__ = 'snippets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    shortcut = db.Column(db.String(30), nullable=False)  # ex: /oi
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='snippets')


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'))
    action = db.Column(db.String(60), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')
    lead = db.relationship('Lead')


class DistributionRule(db.Model):
    """Marca configuração geral da distribuição"""
    __tablename__ = 'distribution_rules'
    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(30), default='round_robin_proporcional')
    redistribute_offline = db.Column(db.Boolean, default=True)
    cold_after_days = db.Column(db.Integer, default=3)


class Task(db.Model):
    """Tarefa agendada pelo corretor (lembrete/ligação/follow-up manual)"""
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'))  # opcional
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    kind = db.Column(db.String(30), default='lembrete')  # lembrete | ligacao | followup_manual | reuniao
    scheduled_at = db.Column(db.DateTime, nullable=False)
    done = db.Column(db.Boolean, default=False)
    done_at = db.Column(db.DateTime)
    triggered = db.Column(db.Boolean, default=False)  # se já mostrou popup
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='tasks')
    lead = db.relationship('Lead')


class Attachment(db.Model):
    """Anexo de mensagem (imagem, pdf, áudio, qualquer arquivo)"""
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer, default=0)
    kind = db.Column(db.String(20), default='file')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('Message', backref='attachments')


class Operadora(db.Model):
    """Operadora/plano oficial — admin gerencia."""
    __tablename__ = 'operadoras'
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(20), nullable=False)  # ADESÃO | PF | PME
    nome = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    @property
    def full_label(self):
        return f'{self.categoria} - {self.nome}'


class Quotation(db.Model):
    """Cotação enviada para um lead (preenchida ao mover para 'cotacao_enviada')."""
    __tablename__ = 'quotations'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    operadora_id = db.Column(db.Integer, db.ForeignKey('operadoras.id'))
    subproduto = db.Column(db.String(120), nullable=False)
    valor = db.Column(db.Float, nullable=False, default=0.0)
    vidas = db.Column(db.Integer, nullable=False, default=1)
    bairro = db.Column(db.String(120), nullable=False)
    # Fase de pagamento (preenchido ao avançar para 'aguardando_pagamento')
    data_boleto = db.Column(db.Date)
    data_vigencia = db.Column(db.Date)
    confirmed_at_proposta = db.Column(db.DateTime)
    confirmed_at_analise = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship('Lead', backref=db.backref('quotation', uselist=False))
    operadora = db.relationship('Operadora')


class LeadStageHistory(db.Model):
    """Registra cada mudança de etapa do lead — base para dashboard por período."""
    __tablename__ = 'lead_stage_history'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # quem fez a mudança
    from_stage = db.Column(db.String(40))
    to_stage = db.Column(db.String(40), nullable=False)
    entered_at = db.Column(db.DateTime, default=datetime.utcnow)

    lead = db.relationship('Lead', backref=db.backref('stage_history', order_by='LeadStageHistory.entered_at'))
    user = db.relationship('User')


# Token simples para a API de inbound (em produção: trocar por OAuth/JWT por origem)
INBOUND_API_TOKEN = os.environ.get('CRM_INBOUND_TOKEN', 'demo-token-troque-em-prod')


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------

def log(action, detail='', lead_id=None, user_id=None):
    """Registra auditoria"""
    entry = AuditLog(
        action=action,
        detail=detail,
        lead_id=lead_id,
        user_id=user_id or session.get('user_id')
    )
    db.session.add(entry)


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrap


def role_required(*allowed_roles):
    """Decorador para restringir rotas a determinados papéis."""
    def deco(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            u = current_user()
            if not u or u.role not in allowed_roles:
                flash(f'Apenas {", ".join(allowed_roles)} podem acessar essa página.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrap
    return deco


# Mantém compat com decorador antigo
admin_required = role_required('admin', 'master')


# ============================================================================
# HIERARQUIA & PERMISSÕES — núcleo do sistema
# ============================================================================
def descendants_of(user):
    """Retorna recursivamente todos os usuários abaixo do `user` na hierarquia."""
    seen = set()
    stack = [user.id]
    while stack:
        current_id = stack.pop()
        children = User.query.filter_by(manager_id=current_id).all()
        for c in children:
            if c.id not in seen:
                seen.add(c.id)
                stack.append(c.id)
    return User.query.filter(User.id.in_(seen)).all() if seen else []


def visible_user_ids(user):
    """IDs dos usuários cujos leads esse user pode ENXERGAR (conversas).

    - master: todos
    - coordenador: subordinados (todos níveis abaixo) + ele mesmo
    - lider: NÃO vê conversas (só métricas agregadas) — set vazio
    - admin: NÃO vê conversas (é operacional) — set vazio
    - consultor: só ele mesmo
    """
    if not user:
        return set()
    if user.role == 'master':
        return {u.id for u in User.query.all()}
    if user.role == 'coordenador':
        ids = {u.id for u in descendants_of(user)}
        ids.add(user.id)
        return ids
    if user.role in ('lider', 'admin'):
        return set()  # não acessam conversas
    return {user.id}  # consultor


def can_see_lead(user, lead):
    if not user or not lead:
        return False
    if user.role == 'master':
        return True
    if user.role in ('lider', 'admin'):
        return False
    return lead.owner_id in visible_user_ids(user)


def can_act_on_lead(user, lead):
    """Pode enviar msg, mudar stage, redistribuir, bloquear corretor.

    - master: pode tudo, em qualquer lead
    - coordenador: pode tudo em leads de seus subordinados
    - consultor (owner): pode tudo no próprio lead se não estiver bloqueado
    - admin / lider: não atuam em conversa
    """
    if not user or not lead:
        return False
    if user.role == 'master':
        return True
    if user.role == 'coordenador':
        return lead.owner_id in visible_user_ids(user)
    if user.role == 'consultor':
        return lead.owner_id == user.id and not user.is_blocked
    return False


def filter_leads_by_visibility(query, user):
    """Aplica filtro de visibilidade ao query de Leads."""
    if user.role == 'master':
        return query
    if user.role == 'coordenador':
        return query.filter(Lead.owner_id.in_(visible_user_ids(user)))
    if user.role in ('lider', 'admin'):
        return query.filter(db.false())
    return query.filter(Lead.owner_id == user.id)


def can_manage_users(user):
    """Cadastrar/editar consultores, definir distribuição, gerenciar templates.
    - master: sim (visão total)
    - admin: sim (papel operacional)
    """
    return user and user.role in ('master', 'admin')


def can_view_audit(user):
    """Sistema de auditoria continua existindo, acessível só ao master."""
    return user and user.role == 'master'


def can_block_consultor(user, target):
    """Quem pode bloquear o consultor `target`?"""
    if not user or not target or target.role != 'consultor':
        return False
    if user.role == 'master':
        return True
    if user.role == 'coordenador':
        return target.id in visible_user_ids(user)
    return False



@app.context_processor
def inject_globals():
    u = current_user()
    unread_count = 0
    pending_tasks = 0
    if u:
        base_q = filter_leads_by_visibility(Lead.query, u)
        unread_count = base_q.filter(
            Lead.last_inbound_at.isnot(None),
            db.or_(Lead.last_outbound_at.is_(None),
                   Lead.last_outbound_at < Lead.last_inbound_at)
        ).count()
        pending_tasks = Task.query.filter_by(user_id=u.id, done=False).count()

    NAV_MAP = {
        'conversas': 'conversas', 'pipeline': 'pipeline', 'dashboard': 'dashboard',
        'tarefas': 'tarefas', 'remarketing': 'remarketing', 'preferencias': 'preferencias',
        'usuarios': 'usuarios', 'distribuicao': 'distribuicao',
        'distribuicao_simular': 'distribuicao',
        'templates_list': 'templates', 'templates_favorite': 'templates',
        'followups_list': 'followups', 'followups_favorite': 'followups',
        'snippets': 'preferencias', 'relatorios': 'relatorios',
        'auditoria': 'auditoria', 'configuracoes': 'config',
        'perfil': 'perfil', 'notificacoes': 'notif', 'lead_detail': 'conversas',
        'operadoras_list': 'operadoras',
    }
    active_nav = NAV_MAP.get(request.endpoint, '')

    return dict(
        current_user=u,
        PIPELINE_STAGES=PIPELINE_STAGES,
        STAGE_LABELS=STAGE_LABELS,
        STAGE_SHORT=STAGE_SHORT,
        STAGE_FORMS=STAGE_FORMS,
        ROLE_LABEL=ROLE_LABEL,
        unread_count=unread_count,
        pending_tasks=pending_tasks,
        active_nav=active_nav,
        can_manage_users=can_manage_users,
        can_view_audit=can_view_audit,
        can_act_on_lead=can_act_on_lead,
    )


def render_variables(text, lead, user):
    """Substitui {{nome}}, {{empresa}}, {{consultor}} etc."""
    if not text:
        return text
    mapping = {
        'nome': lead.name or '',
        'empresa': lead.company or '',
        'consultor': user.name if user else '',
        'email': lead.email or '',
        'telefone': lead.phone or '',
    }
    def repl(m):
        key = m.group(1).strip().lower()
        return mapping.get(key, m.group(0))
    return re.sub(r'\{\{\s*([a-zA-Z_]+)\s*\}\}', repl, text)


# ----------------------------------------------------------------------------
# DISTRIBUIÇÃO INTELIGENTE
# ----------------------------------------------------------------------------

def pick_next_owner():
    """
    Algoritmo de distribuição inteligente:
    - Round-robin proporcional baseado em meta semanal
    - Considera leads já recebidos na semana
    - Pula usuários offline (fallback)
    - Calcula 'pressure' = recebidos / meta. Menor pressure = próximo da fila.
    - Desempate: menos recebidos hoje.
    """
    users = User.query.filter_by(role='consultor', is_active=True).all()
    if not users:
        return None

    rule = DistributionRule.query.first()
    if rule and rule.redistribute_offline:
        candidates = [u for u in users if u.is_online]
        if not candidates:
            candidates = users  # fallback: ignora online se ninguém estiver
    else:
        candidates = users

    week_start = datetime.utcnow() - timedelta(days=7)
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    best = None
    best_score = None
    for u in candidates:
        week_count = Lead.query.filter(
            Lead.owner_id == u.id,
            Lead.created_at >= week_start
        ).count()
        day_count = Lead.query.filter(
            Lead.owner_id == u.id,
            Lead.created_at >= day_start
        ).count()
        quota = max(u.weekly_quota, 1)
        pressure = week_count / quota
        # score: priorizamos quem tem MENOR pressure, depois menos leads hoje
        score = (pressure, day_count, u.id)
        if best_score is None or score < best_score:
            best_score = score
            best = u
    return best


# ----------------------------------------------------------------------------
# AUTOMAÇÃO: FOLLOW-UPS E LEADS FRIOS
# ----------------------------------------------------------------------------

def run_automations():
    """
    Roda automações sempre que dashboard/conversas/tarefas são acessadas:
    1. Reset diário de fups_sent_today (se o dia mudou)
    2. Move leads com cadência esgotada (3 dias + max/dia FUPs) para REMARKETING
    3. Move leads em mensagem_enviada sem resposta há X dias para lead_frio
    """
    today = date.today()
    rule = DistributionRule.query.first()
    cold_days = rule.cold_after_days if rule else 3
    threshold = datetime.utcnow() - timedelta(days=cold_days)

    # 1) Reset diário do contador fups_sent_today
    leads_to_reset = Lead.query.filter(
        db.or_(Lead.fups_last_date.is_(None), Lead.fups_last_date < today)
    ).all()
    for lead in leads_to_reset:
        lead.fups_sent_today = 0
        lead.fups_last_date = today

    # 2) Move para REMARKETING (cadência esgotada: 3+ FUPs e 3+ dias sem resposta)
    remarketing_targets = Lead.query.filter(
        Lead.moved_to_remarketing_at.is_(None),
        Lead.last_outbound_at.isnot(None),
        Lead.last_outbound_at < threshold,
        Lead.sent_without_response >= 3,
    ).all()
    for lead in remarketing_targets:
        if not lead.last_inbound_at or lead.last_inbound_at < lead.last_outbound_at:
            lead.moved_to_remarketing_at = datetime.utcnow()
            lead.stage = 'lead_frio'
            entry = AuditLog(
                action='auto_remarketing',
                detail=f'Cadência esgotada após {cold_days} dias e {lead.sent_without_response} FUPs · movido para Remarketing',
                lead_id=lead.id,
            )
            db.session.add(entry)
            # Cria tarefa automática de ligação para o owner
            if lead.owner_id:
                task = Task(
                    user_id=lead.owner_id,
                    lead_id=lead.id,
                    title=f'Ligar para {lead.name} (remarketing)',
                    description='Lead esgotou cadência de WhatsApp. Realizar ligação.',
                    kind='ligacao',
                    scheduled_at=datetime.utcnow() + timedelta(hours=2),
                )
                db.session.add(task)

    db.session.commit()


# ----------------------------------------------------------------------------
# ROTAS — AUTH
# ----------------------------------------------------------------------------

@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            session['user_id'] = user.id
            user.is_online = True
            log('login', f'Login efetuado: {user.email}', user_id=user.id)
            db.session.commit()
            return redirect(url_for('dashboard'))
        flash('Credenciais inválidas.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    u = current_user()
    if u:
        u.is_online = False
        log('logout', f'Logout: {u.email}', user_id=u.id)
        db.session.commit()
    session.clear()
    return redirect(url_for('login'))


# ----------------------------------------------------------------------------
# ROTAS — DASHBOARD
# ----------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    run_automations()
    u = current_user()

    # === FILTRO DE PERÍODO ===
    # 'today' | '7d' | '30d' | 'month' | 'custom' (com de=/ate=)
    periodo = request.args.get('periodo', '30d')
    now = datetime.utcnow()
    today_0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == 'today':
        date_from = today_0
        date_to = now
    elif periodo == '7d':
        date_from = now - timedelta(days=7)
        date_to = now
    elif periodo == 'month':
        date_from = today_0.replace(day=1)
        date_to = now
    elif periodo == 'custom':
        try:
            date_from = datetime.strptime(request.args.get('de', ''), '%Y-%m-%d')
            date_to = datetime.strptime(request.args.get('ate', ''), '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            date_from = now - timedelta(days=30)
            date_to = now
    else:  # 30d (padrão)
        date_from = now - timedelta(days=30)
        date_to = now

    # Filtro adicional: consultor específico (master/coordenador pode escolher)
    filter_user_id = request.args.get('consultor', type=int)

    # === BASE QUERY com visibilidade hierárquica ===
    # Admin e Líder: para métricas, podem ver agregado da empresa toda
    # (mas continuam SEM acessar conversas individualmente)
    if u.role in ('admin', 'lider', 'master'):
        base = Lead.query
    elif u.role == 'coordenador':
        base = Lead.query.filter(Lead.owner_id.in_(visible_user_ids(u)))
    else:  # consultor
        base = Lead.query.filter(Lead.owner_id == u.id)

    if filter_user_id and u.role in ('master', 'admin', 'coordenador', 'lider'):
        base = base.filter(Lead.owner_id == filter_user_id)

    # Métricas operacionais (no período)
    leads_periodo = base.filter(Lead.created_at >= date_from, Lead.created_at <= date_to)
    total_periodo = leads_periodo.count()
    leads_today = base.filter(Lead.created_at >= today_0).count()
    total_leads = base.count()

    cold = base.filter(Lead.stage == 'lead_frio').count()
    closed = base.filter(Lead.stage == 'plano_fechado').count()
    active = base.filter(Lead.stage.in_([
        'em_conversacao', 'cotacao_enviada', 'proposta_digitada',
        'em_analise', 'aguardando_pagamento'
    ])).count()

    responded = base.filter(Lead.last_inbound_at.isnot(None)).count()
    response_rate = round((responded / total_leads * 100), 1) if total_leads else 0
    conversion_rate = round((closed / total_leads * 100), 1) if total_leads else 0

    # Contagem e valor por etapa
    stages_count = {}
    stages_value = {}
    for stage_id, _ in PIPELINE_STAGES:
        q = base.filter(Lead.stage == stage_id)
        stages_count[stage_id] = q.count()
        # Soma do orçamento (budget) E do valor da cotação por etapa
        v = db.session.query(func.coalesce(func.sum(Lead.budget), 0.0))\
            .filter(Lead.id.in_(q.with_entities(Lead.id))).scalar() or 0
        # Se houver quotation.valor, prefere
        qv = db.session.query(func.coalesce(func.sum(Quotation.valor), 0.0))\
            .join(Lead, Lead.id == Quotation.lead_id)\
            .filter(Lead.stage == stage_id, Lead.id.in_([l.id for l in base.all()] or [-1])).scalar() or 0
        stages_value[stage_id] = float(qv if qv > 0 else v)

    # Receita potencial / fechada / perdida no PERÍODO
    active_stages = ['mensagem_enviada', 'em_conversacao', 'cotacao_enviada',
                     'proposta_digitada', 'em_analise', 'aguardando_pagamento']
    rev_pot_q = base.filter(Lead.stage.in_(active_stages))
    rev_closed_q = base.filter(Lead.stage == 'plano_fechado',
                               Lead.stage_entered_at >= date_from,
                               Lead.stage_entered_at <= date_to)
    rev_lost_q = base.filter(Lead.stage == 'lead_frio')

    def sum_budget(q):
        s = db.session.query(func.coalesce(func.sum(Lead.budget), 0.0))\
            .filter(Lead.id.in_(q.with_entities(Lead.id))).scalar() or 0
        return float(s)
    revenue_potential = sum_budget(rev_pot_q)
    revenue_closed = sum_budget(rev_closed_q)
    revenue_lost = sum_budget(rev_lost_q)

    # Produtividade da equipe (visível por master/admin/coordenador/lider)
    consultants = []
    if u.role in ('master', 'admin', 'coordenador', 'lider'):
        if u.role == 'coordenador':
            team = [usr for usr in descendants_of(u) if usr.role == 'consultor']
        elif u.role == 'lider':
            team = [usr for usr in descendants_of(u) if usr.role == 'consultor']
        else:
            team = User.query.filter_by(role='consultor', is_active=True).all()
        for c in team:
            c_leads_period = Lead.query.filter(
                Lead.owner_id == c.id,
                Lead.created_at >= date_from, Lead.created_at <= date_to
            ).count()
            c_closed = Lead.query.filter(Lead.owner_id == c.id, Lead.stage == 'plano_fechado').count()
            c_active = Lead.query.filter(
                Lead.owner_id == c.id,
                Lead.stage.in_(active_stages)
            ).count()
            c_sla = db.session.query(func.count(Lead.id)).filter(
                Lead.owner_id == c.id,
                Lead.last_inbound_at.isnot(None),
                db.or_(Lead.last_outbound_at.is_(None),
                       Lead.last_outbound_at < Lead.last_inbound_at)
            ).scalar() or 0
            consultants.append({
                'id': c.id, 'name': c.name,
                'leads_periodo': c_leads_period,
                'closed': c_closed, 'active': c_active,
                'sla_pendentes': c_sla,
                'quota': c.weekly_quota,
                'pressure': round((c_leads_period / max(c.weekly_quota, 1)) * 100, 1),
                'online': c.is_online, 'blocked': c.is_blocked,
            })

    avg_response_time = compute_avg_response_time(u)

    # Origem dos leads (top 5) — apenas para master/admin/coordenador
    sources = []
    if u.role in ('master', 'admin', 'coordenador'):
        sources_q = db.session.query(Lead.source, func.count(Lead.id))
        sources_q = sources_q.filter(Lead.id.in_(base.with_entities(Lead.id)))
        sources = sources_q.group_by(Lead.source).order_by(desc(func.count(Lead.id))).limit(5).all()

    # Para os filtros: lista de consultores visíveis
    visible_consultants = []
    if u.role == 'master' or u.role == 'admin':
        visible_consultants = User.query.filter_by(role='consultor').order_by(User.name).all()
    elif u.role == 'coordenador':
        visible_consultants = User.query.filter(
            User.id.in_(visible_user_ids(u)),
            User.role == 'consultor'
        ).order_by(User.name).all()
    elif u.role == 'lider':
        # Líder filtra pelos consultores diretamente subordinados a ele
        visible_consultants = [usr for usr in descendants_of(u) if usr.role == 'consultor']
        visible_consultants.sort(key=lambda x: x.name)

    return render_template('dashboard.html',
        periodo=periodo, date_from=date_from, date_to=date_to,
        filter_user_id=filter_user_id,
        visible_consultants=visible_consultants,
        leads_today=leads_today, total_periodo=total_periodo, total_leads=total_leads,
        cold=cold, closed=closed, active=active,
        response_rate=response_rate, conversion_rate=conversion_rate,
        stages_count=stages_count, stages_value=stages_value,
        consultants=consultants, avg_response_time=avg_response_time,
        revenue_potential=revenue_potential,
        revenue_closed=revenue_closed,
        revenue_lost=revenue_lost,
        sources=sources,
        # Modo restrito: líder e admin não veem detalhes de leads individuais
        is_aggregated_view=(u.role in ('lider', 'admin')),
    )


def compute_avg_response_time(user):
    """Tempo médio entre msg inbound e próxima outbound (minutos)"""
    base = filter_leads_by_visibility(Lead.query, user)
    leads = base.limit(200).all()
    times = []
    for lead in leads:
        msgs = sorted(lead.messages, key=lambda m: m.created_at)
        last_in = None
        for m in msgs:
            if m.direction == 'in':
                last_in = m.created_at
            elif m.direction == 'out' and last_in:
                delta = (m.created_at - last_in).total_seconds() / 60
                if 0 < delta < 60*24:  # ignora outliers
                    times.append(delta)
                last_in = None
    if not times:
        return None
    return round(sum(times) / len(times), 1)


# ----------------------------------------------------------------------------
# ROTAS — CONVERSAS
# ----------------------------------------------------------------------------

@app.route('/conversas')
@login_required
def conversas():
    run_automations()
    u = current_user()

    # Líder não acessa conversas — só vê métricas
    if u.role == 'lider':
        flash('Líderes não têm acesso ao conteúdo das conversas. Use o Dashboard.', 'info')
        return redirect(url_for('dashboard'))

    filter_stage = request.args.get('stage', '')
    search = request.args.get('q', '').strip()
    # Filtro de consultor (master/admin/coordenador podem escolher)
    filter_user_id = request.args.get('consultor', type=int)

    q = filter_leads_by_visibility(Lead.query, u)
    if filter_user_id and u.role in ('master', 'admin', 'coordenador'):
        q = q.filter(Lead.owner_id == filter_user_id)
    if filter_stage:
        q = q.filter(Lead.stage == filter_stage)
    if search:
        like = f'%{search}%'
        q = q.filter(db.or_(Lead.name.ilike(like), Lead.phone.ilike(like), Lead.company.ilike(like)))

    leads = q.order_by(desc(Lead.last_message_at), desc(Lead.created_at)).all()

    selected_id = request.args.get('lead', type=int) or request.args.get('lead_id', type=int)
    selected = None
    if selected_id:
        selected = Lead.query.get(selected_id)
        if selected and not can_see_lead(u, selected):
            selected = None
    elif leads:
        selected = leads[0]

    templates = Template.query.filter_by(is_active=True).all()
    fav_templates = [t for t in templates if t.id in u.fav_template_ids]
    followups = FollowUp.query.filter_by(is_active=True).all()
    fav_followups = [f for f in followups if f.id in u.fav_followup_ids]
    user_snippets = Snippet.query.filter_by(user_id=u.id).all()

    # Lista de consultores visíveis (para filtro de gestor)
    visible_consultants = []
    if u.role in ('master', 'admin', 'coordenador'):
        visible_consultants = User.query.filter(
            User.id.in_(visible_user_ids(u)),
            User.role == 'consultor'
        ).order_by(User.name).all()

    # Permissão de ação na conversa selecionada
    can_act = can_act_on_lead(u, selected) if selected else False
    # Operadoras (para o modal de cotação)
    operadoras = Operadora.query.filter_by(is_active=True).order_by(Operadora.categoria, Operadora.nome).all()

    return render_template('conversas.html',
        leads=leads, selected=selected,
        templates=templates, fav_templates=fav_templates,
        followups=followups, fav_followups=fav_followups,
        snippets=user_snippets,
        filter_stage=filter_stage, search=search,
        filter_user_id=filter_user_id,
        visible_consultants=visible_consultants,
        can_act=can_act,
        operadoras=operadoras,
        lead_id_for_js=selected.id if selected else '',
    )


@app.route('/conversas/<int:lead_id>/send', methods=['POST'])
@login_required
def send_message(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        abort(403)
    body = request.form.get('body', '').strip()
    kind = request.form.get('kind', 'text')
    if not body:
        flash('Mensagem vazia.', 'warning')
        return redirect(url_for('conversas', lead=lead_id))

    # === REGRA DE CADÊNCIA ===
    # Aplica somente em mensagens kind=followup ou template (não em texto livre conversacional).
    # Texto livre é resposta direta do corretor, não consome cadência.
    is_followup_kind = kind in ('followup', 'template')
    today = date.today()
    if lead.fups_last_date != today:
        lead.fups_sent_today = 0
        lead.fups_last_date = today

    if is_followup_kind:
        max_per_day = u.cadence_per_day or 2
        if lead.fups_sent_today >= max_per_day:
            flash(f'Limite diário de cadência atingido ({max_per_day} FUPs/dia para este lead). Ajuste em Preferências.', 'warning')
            return redirect(url_for('conversas', lead=lead_id))
        # Intervalo mínimo entre FUPs no mesmo dia
        min_interval = timedelta(hours=u.cadence_interval_hours or 3)
        last_fup = Message.query.filter(
            Message.lead_id == lead.id,
            Message.direction == 'out',
            Message.kind.in_(('followup', 'template')),
        ).order_by(desc(Message.created_at)).first()
        if last_fup and (datetime.utcnow() - last_fup.created_at) < min_interval:
            mins_left = int((min_interval - (datetime.utcnow() - last_fup.created_at)).total_seconds() / 60)
            flash(f'Intervalo mínimo de {u.cadence_interval_hours}h entre FUPs. Aguarde ~{mins_left}min.', 'warning')
            return redirect(url_for('conversas', lead=lead_id))

    body = render_variables(body, lead, u)
    msg = Message(lead_id=lead.id, user_id=u.id, direction='out', body=body, kind=kind)
    db.session.add(msg)
    lead.last_message_at = datetime.utcnow()
    lead.last_outbound_at = datetime.utcnow()
    if is_followup_kind:
        lead.sent_without_response = (lead.sent_without_response or 0) + 1
        lead.fups_sent_today = (lead.fups_sent_today or 0) + 1
    log('message_sent', f'Mensagem [{kind}] enviada: {body[:80]}', lead_id=lead.id)
    db.session.commit()
    return redirect(url_for('conversas', lead=lead_id))


@app.route('/conversas/<int:lead_id>/simulate-inbound', methods=['POST'])
@login_required
def simulate_inbound(lead_id):
    """Simula uma resposta do lead (para demo) — em produção viria via webhook do WhatsApp"""
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    body = request.form.get('body', '').strip()
    if not body:
        return redirect(url_for('conversas', lead=lead_id))
    msg = Message(lead_id=lead.id, user_id=None, direction='in', body=body, kind='text')
    db.session.add(msg)
    lead.last_message_at = datetime.utcnow()
    lead.last_inbound_at = datetime.utcnow()
    lead.sent_without_response = 0
    # Regra automática: ao responder, volta para "em_conversacao"
    if lead.stage in ('mensagem_enviada', 'lead_frio'):
        old = lead.stage
        lead.stage = 'em_conversacao'
        log('auto_stage_change', f'Movido de {STAGE_LABELS.get(old)} para Em Conversação (lead respondeu)', lead_id=lead.id)
    db.session.commit()
    return redirect(url_for('conversas', lead=lead_id))


@app.route('/conversas/<int:lead_id>/budget', methods=['POST'])
@login_required
def update_lead_budget(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        abort(403)
    raw = request.form.get('budget', '0').replace('.', '').replace(',', '.').strip()
    try:
        lead.budget = float(raw)
    except ValueError:
        lead.budget = 0.0
    log('budget_updated', f'Budget: R$ {lead.budget:.2f}', lead_id=lead.id)
    db.session.commit()
    flash('Orçamento atualizado.', 'success')
    return redirect(url_for('conversas', lead=lead.id))


@app.route('/conversas/<int:lead_id>/stage', methods=['POST'])
@login_required
def change_stage(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        abort(403)
    new_stage = request.form.get('stage')
    if new_stage not in STAGE_LABELS:
        abort(400)
    old = lead.stage
    if old == new_stage:
        return redirect(url_for('conversas', lead=lead_id))

    # ===== FORMULÁRIO OBRIGATÓRIO POR ETAPA =====
    required = STAGE_FORMS.get(new_stage, [])
    q = lead.quotation  # cotação atual (1:1)

    if new_stage == 'cotacao_enviada':
        operadora_id = request.form.get('operadora_id', type=int)
        subproduto = request.form.get('subproduto', '').strip()
        valor_raw = request.form.get('valor', '').replace('.', '').replace(',', '.').strip()
        vidas = request.form.get('vidas', type=int)
        bairro = request.form.get('bairro', '').strip()
        try:
            valor = float(valor_raw) if valor_raw else 0
        except ValueError:
            valor = 0
        if not (operadora_id and subproduto and valor > 0 and vidas and bairro):
            flash('Preencha todos os campos da cotação (operadora, sub-produto, valor, vidas, bairro).', 'danger')
            return redirect(url_for('conversas', lead=lead_id))
        if not q:
            q = Quotation(lead_id=lead.id, operadora_id=operadora_id,
                          subproduto=subproduto, valor=valor, vidas=vidas, bairro=bairro)
            db.session.add(q)
        else:
            q.operadora_id = operadora_id; q.subproduto = subproduto
            q.valor = valor; q.vidas = vidas; q.bairro = bairro
        lead.budget = valor  # sincroniza budget com valor da cotação
        lead.vidas = vidas

    elif new_stage == 'proposta_digitada':
        if not q:
            flash('Lead não tem cotação. Avance primeiro para "Cotação Enviada".', 'danger')
            return redirect(url_for('conversas', lead=lead_id))
        # Confirma os itens (permite editar)
        if 'subproduto' in request.form:
            q.subproduto = request.form.get('subproduto', q.subproduto).strip()
            try:
                q.valor = float(request.form.get('valor', q.valor).replace('.', '').replace(',', '.'))
            except ValueError: pass
            q.vidas = request.form.get('vidas', type=int) or q.vidas
            q.bairro = request.form.get('bairro', q.bairro).strip()
            lead.budget = q.valor; lead.vidas = q.vidas
        q.confirmed_at_proposta = datetime.utcnow()

    elif new_stage == 'em_analise':
        if not q:
            flash('Lead não tem cotação. Avance primeiro para "Cotação Enviada".', 'danger')
            return redirect(url_for('conversas', lead=lead_id))
        if 'subproduto' in request.form:
            q.subproduto = request.form.get('subproduto', q.subproduto).strip()
            try:
                q.valor = float(request.form.get('valor', q.valor).replace('.', '').replace(',', '.'))
            except ValueError: pass
            q.vidas = request.form.get('vidas', type=int) or q.vidas
            q.bairro = request.form.get('bairro', q.bairro).strip()
            lead.budget = q.valor; lead.vidas = q.vidas
        q.confirmed_at_analise = datetime.utcnow()

    elif new_stage == 'aguardando_pagamento':
        if not q:
            flash('Lead não tem cotação.', 'danger')
            return redirect(url_for('conversas', lead=lead_id))
        try:
            data_boleto = datetime.strptime(request.form.get('data_boleto', ''), '%Y-%m-%d').date()
            data_vigencia = datetime.strptime(request.form.get('data_vigencia', ''), '%Y-%m-%d').date()
        except ValueError:
            flash('Informe data prevista do boleto e da vigência (formato AAAA-MM-DD).', 'danger')
            return redirect(url_for('conversas', lead=lead_id))
        q.data_boleto = data_boleto
        q.data_vigencia = data_vigencia

    # ===== APLICA MUDANÇA =====
    lead.stage = new_stage
    lead.stage_entered_at = datetime.utcnow()
    # Histórico
    history = LeadStageHistory(
        lead_id=lead.id, user_id=u.id,
        from_stage=old, to_stage=new_stage,
    )
    db.session.add(history)
    log('stage_change', f'{STAGE_LABELS.get(old)} → {STAGE_LABELS.get(new_stage)}', lead_id=lead.id)
    db.session.commit()
    flash(f'Etapa atualizada para "{STAGE_LABELS.get(new_stage)}".', 'success')
    return redirect(url_for('conversas', lead=lead_id))


@app.route('/conversas/<int:lead_id>/note', methods=['POST'])
@login_required
def add_note(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    note = request.form.get('note', '').strip()
    if note:
        msg = Message(lead_id=lead.id, user_id=u.id, direction='out', body=note, kind='note')
        db.session.add(msg)
        log('note_added', f'Nota interna: {note[:80]}', lead_id=lead.id)
        db.session.commit()
    return redirect(url_for('conversas', lead=lead_id))


# ----------------------------------------------------------------------------
# ROTAS — PIPELINE / KANBAN
# ----------------------------------------------------------------------------

@app.route('/pipeline')
@login_required
def pipeline():
    run_automations()
    u = current_user()
    q = Lead.query
    if u.role != 'admin':
        q = q.filter(Lead.owner_id == u.id)
    leads = q.order_by(desc(Lead.last_message_at)).all()
    columns = {stage_id: [] for stage_id, _ in PIPELINE_STAGES}
    for lead in leads:
        if lead.stage in columns:
            columns[lead.stage].append(lead)
    return render_template('pipeline.html', columns=columns)


@app.route('/pipeline/move/<int:lead_id>', methods=['POST'])
@login_required
def pipeline_move(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        return jsonify({'ok': False}), 403
    new_stage = request.json.get('stage') if request.is_json else request.form.get('stage')
    if new_stage not in STAGE_LABELS:
        return jsonify({'ok': False}), 400
    old = lead.stage
    lead.stage = new_stage
    log('stage_change_kanban', f'{STAGE_LABELS.get(old)} → {STAGE_LABELS.get(new_stage)}', lead_id=lead.id)
    db.session.commit()
    return jsonify({'ok': True})


# ----------------------------------------------------------------------------
# ROTAS — LEAD DETAIL
# ----------------------------------------------------------------------------

@app.route('/lead/<int:lead_id>')
@login_required
def lead_detail(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_see_lead(u, lead):
        abort(403)
    timeline = AuditLog.query.filter_by(lead_id=lead.id).order_by(desc(AuditLog.created_at)).all()
    return render_template('lead_detail.html', lead=lead, timeline=timeline)


@app.route('/lead/<int:lead_id>/update', methods=['POST'])
@login_required
def lead_update(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        abort(403)
    lead.name = request.form.get('name', lead.name)
    lead.phone = request.form.get('phone', lead.phone)
    lead.email = request.form.get('email', lead.email)
    lead.company = request.form.get('company', lead.company)
    lead.tags = request.form.get('tags', lead.tags)
    lead.notes = request.form.get('notes', lead.notes)
    log('lead_updated', 'Dados do lead atualizados', lead_id=lead.id)
    db.session.commit()
    flash('Lead atualizado.', 'success')
    return redirect(url_for('lead_detail', lead_id=lead.id))


@app.route('/leads/novo', methods=['POST'])
@login_required
def lead_create():
    """Cria lead manual. Cadastro pelo próprio consultor → origem visível ao corretor."""
    u = current_user()
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    source = request.form.get('source', 'manual')
    pref = request.form.get('preferencia_contato', 'whatsapp')
    tem_cnpj_raw = request.form.get('tem_cnpj', '')  # 'sim' | 'nao' | ''
    tem_cnpj = True if tem_cnpj_raw == 'sim' else False if tem_cnpj_raw == 'nao' else None
    categoria = 'PME' if tem_cnpj is True else 'PF' if tem_cnpj is False else None
    vidas_raw = request.form.get('vidas', '').strip()
    try:
        vidas = int(vidas_raw) if vidas_raw else None
    except ValueError:
        vidas = None

    if not name:
        flash('Nome do lead é obrigatório.', 'warning')
        return redirect(url_for('conversas'))

    # Quem é o owner: master/admin → distribuição; consultor → ele mesmo; coordenador → distribuição
    if u.role in ('master', 'admin', 'coordenador'):
        owner = pick_next_owner() or u
    else:
        owner = u

    lead = Lead(
        name=name, phone=phone, email=email,
        source=source, owner_id=owner.id,
        stage='mensagem_enviada',
        tem_cnpj=tem_cnpj, categoria=categoria,
        vidas=vidas, preferencia_contato=pref,
        # Cadastro manual pelo CONSULTOR: ele vê a origem (ele preencheu)
        # Cadastro por outro role: também marcamos como visível, pois é manual
        source_visible_to_consultor=True,
        last_message_at=datetime.utcnow(),
        stage_entered_at=datetime.utcnow(),
    )
    db.session.add(lead)
    db.session.flush()

    # Registra histórico inicial
    db.session.add(LeadStageHistory(
        lead_id=lead.id, user_id=u.id,
        from_stage=None, to_stage='mensagem_enviada',
    ))
    log('lead_created', f'Lead manual criado, atribuído a {owner.name}', lead_id=lead.id)
    db.session.commit()
    flash(f'Lead "{name}" criado e atribuído a {owner.name}.', 'success')
    return redirect(url_for('conversas', lead=lead.id))


# ----------------------------------------------------------------------------
# 1ª MENSAGEM AUTOMÁTICA — Quando lead chega via API, dispara a mensagem
# preferida do consultor dono (1ª template favorita)
# ----------------------------------------------------------------------------

def trigger_first_message(lead):
    """Envia automaticamente a 1ª template favorita do consultor (se houver)
    quando o lead chega via API. Retorna a Message criada ou None."""
    owner = lead.owner
    if not owner:
        return None
    fav_ids = owner.fav_template_ids
    if not fav_ids:
        return None
    template = Template.query.get(fav_ids[0])
    if not template:
        return None
    body = render_variables(template.body, lead, owner)
    msg = Message(lead_id=lead.id, user_id=owner.id, direction='out',
                  body=body, kind='template')
    db.session.add(msg)
    lead.last_message_at = datetime.utcnow()
    lead.last_outbound_at = datetime.utcnow()
    log('auto_first_message',
        f'1ª mensagem disparada (template: {template.title})', lead_id=lead.id)
    return msg


# A rota /api/leads/inbound (que usa este trigger_first_message) está logo abaixo.
@app.route('/api/leads/inbound', methods=['POST'])
def api_leads_inbound():
    """Endpoint público para criar leads via webhook/API.
    Auth: header X-API-Token = CRM_INBOUND_TOKEN
    Body JSON: name, phone, email, tem_cnpj, vidas, source, preferencia_contato, owner_id (opt)
    """
    token = request.headers.get('X-API-Token') or request.args.get('token')
    if token != INBOUND_API_TOKEN:
        return jsonify({'error': 'token inválido'}), 401
    data = request.get_json(silent=True) or request.form.to_dict()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name é obrigatório'}), 400

    tem_cnpj = data.get('tem_cnpj')
    if isinstance(tem_cnpj, str):
        tem_cnpj = tem_cnpj.lower() in ('true', '1', 'sim', 'yes', 's')
    categoria = 'PME' if tem_cnpj else 'PF'

    owner = None
    if data.get('owner_id'):
        owner = User.query.get(int(data['owner_id']))
    if not owner:
        owner = pick_next_owner()

    lead = Lead(
        name=name,
        phone=(data.get('phone') or '').strip(),
        email=(data.get('email') or '').strip(),
        company=(data.get('company') or '').strip(),
        source=(data.get('source') or 'api').strip(),
        source_visible_to_consultor=False,
        owner_id=owner.id if owner else None,
        stage='mensagem_enviada',
        tem_cnpj=bool(tem_cnpj),
        categoria=categoria,
        vidas=int(data['vidas']) if data.get('vidas') else None,
        preferencia_contato=(data.get('preferencia_contato') or 'whatsapp').strip(),
        last_message_at=datetime.utcnow(),
        stage_entered_at=datetime.utcnow(),
    )
    db.session.add(lead)
    db.session.flush()

    db.session.add(LeadStageHistory(lead_id=lead.id, user_id=owner.id if owner else None,
                                    from_stage=None, to_stage='mensagem_enviada'))
    log('lead_inbound_api',
        f'Lead via API → {owner.name if owner else "—"} (origem: {lead.source})',
        lead_id=lead.id)

    # Dispara 1ª mensagem automática
    if data.get('auto_first_message', True):
        trigger_first_message(lead)

    db.session.commit()
    return jsonify({'ok': True, 'lead_id': lead.id,
                    'owner': owner.name if owner else None,
                    'categoria': categoria}), 201


# ----------------------------------------------------------------------------
# ROTAS — TEMPLATES (somente admin cria; consultor escolhe favoritos)
# ----------------------------------------------------------------------------

@app.route('/templates')
@login_required
def templates_list():
    templates = Template.query.order_by(Template.category, Template.title).all()
    u = current_user()
    return render_template('templates.html', templates=templates, user=u)


@app.route('/templates/criar', methods=['POST'])
@admin_required
def template_create():
    t = Template(
        title=request.form.get('title', '').strip(),
        category=request.form.get('category', 'geral').strip(),
        body=request.form.get('body', '').strip(),
    )
    if not t.title or not t.body:
        flash('Título e corpo são obrigatórios.', 'warning')
        return redirect(url_for('templates_list'))
    db.session.add(t)
    log('template_created', f'Template criado: {t.title}')
    db.session.commit()
    flash('Template criado.', 'success')
    return redirect(url_for('templates_list'))


@app.route('/templates/<int:tid>/del', methods=['POST'])
@admin_required
def template_delete(tid):
    t = Template.query.get_or_404(tid)
    log('template_deleted', f'Template removido: {t.title}')
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('templates_list'))


@app.route('/templates/favoritar', methods=['POST'])
@login_required
def templates_favorite():
    u = current_user()
    ids = request.form.getlist('fav')
    if len(ids) > 3:
        flash('Você pode escolher no máximo 3 templates favoritos.', 'warning')
        return redirect(url_for('templates_list'))
    u.favorite_templates = ','.join(ids)
    log('templates_favorited', f'Favoritos: {u.favorite_templates}')
    db.session.commit()
    flash('Favoritos atualizados.', 'success')
    return redirect(url_for('templates_list'))


# ----------------------------------------------------------------------------
# ROTAS — SNIPPETS (cada usuário até 5)
# ----------------------------------------------------------------------------

@app.route('/snippets', methods=['GET', 'POST'])
@login_required
def snippets():
    u = current_user()
    if request.method == 'POST':
        if Snippet.query.filter_by(user_id=u.id).count() >= 5:
            flash('Limite de 5 snippets atingido.', 'warning')
        else:
            shortcut = request.form.get('shortcut', '').strip()
            body = request.form.get('body', '').strip()
            if shortcut and body:
                if not shortcut.startswith('/'):
                    shortcut = '/' + shortcut
                s = Snippet(user_id=u.id, shortcut=shortcut, body=body)
                db.session.add(s)
                log('snippet_created', f'Snippet criado: {shortcut}')
                db.session.commit()
                flash('Snippet criado.', 'success')
        return redirect(url_for('snippets'))
    user_snippets = Snippet.query.filter_by(user_id=u.id).all()
    return render_template('snippets.html', snippets=user_snippets)


@app.route('/snippets/<int:sid>/del', methods=['POST'])
@login_required
def snippet_delete(sid):
    u = current_user()
    s = Snippet.query.get_or_404(sid)
    if s.user_id != u.id:
        abort(403)
    log('snippet_deleted', f'Snippet removido: {s.shortcut}')
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for('snippets'))


# ----------------------------------------------------------------------------
# ROTAS — FOLLOW-UPS (somente admin cria)
# ----------------------------------------------------------------------------

@app.route('/followups')
@login_required
def followups_list():
    fups = FollowUp.query.order_by(FollowUp.sequence).all()
    u = current_user()
    return render_template('followups.html', followups=fups, user=u)


@app.route('/followups/criar', methods=['POST'])
@admin_required
def followup_create():
    f = FollowUp(
        title=request.form.get('title', '').strip(),
        body=request.form.get('body', '').strip(),
        sequence=int(request.form.get('sequence', 1)),
        days_after=int(request.form.get('days_after', 1)),
    )
    if not f.title or not f.body:
        flash('Preencha título e corpo.', 'warning')
        return redirect(url_for('followups_list'))
    db.session.add(f)
    log('followup_created', f'Follow-up criado: {f.title}')
    db.session.commit()
    flash('Follow-up criado.', 'success')
    return redirect(url_for('followups_list'))


@app.route('/followups/<int:fid>/del', methods=['POST'])
@admin_required
def followup_delete(fid):
    f = FollowUp.query.get_or_404(fid)
    log('followup_deleted', f'Follow-up removido: {f.title}')
    db.session.delete(f)
    db.session.commit()
    return redirect(url_for('followups_list'))


@app.route('/followups/favoritar', methods=['POST'])
@login_required
def followups_favorite():
    u = current_user()
    ids = request.form.getlist('fav')
    if len(ids) > 5:
        flash('Máximo 5 favoritos.', 'warning')
        return redirect(url_for('followups_list'))
    u.favorite_followups = ','.join(ids)
    log('followups_favorited', f'Favoritos: {u.favorite_followups}')
    db.session.commit()
    flash('Favoritos atualizados.', 'success')
    return redirect(url_for('followups_list'))


# ----------------------------------------------------------------------------
# ROTAS — DISTRIBUIÇÃO (admin)
# ----------------------------------------------------------------------------

@app.route('/distribuicao', methods=['GET', 'POST'])
@admin_required
def distribuicao():
    if request.method == 'POST':
        for u in User.query.filter_by(role='consultor').all():
            q = request.form.get(f'quota_{u.id}')
            if q is not None:
                u.weekly_quota = int(q)
        rule = DistributionRule.query.first()
        if not rule:
            rule = DistributionRule()
            db.session.add(rule)
        rule.redistribute_offline = bool(request.form.get('redistribute_offline'))
        rule.cold_after_days = int(request.form.get('cold_after_days', 3))
        log('distribution_updated', 'Regras de distribuição atualizadas')
        db.session.commit()
        flash('Distribuição atualizada.', 'success')
        return redirect(url_for('distribuicao'))

    consultants = User.query.filter_by(role='consultor', is_active=True).all()
    week_start = datetime.utcnow() - timedelta(days=7)
    stats = []
    for c in consultants:
        week_count = Lead.query.filter(Lead.owner_id == c.id, Lead.created_at >= week_start).count()
        stats.append({
            'user': c,
            'week_count': week_count,
            'pressure': round((week_count / max(c.weekly_quota, 1)) * 100, 1),
        })
    rule = DistributionRule.query.first() or DistributionRule()
    return render_template('distribuicao.html', stats=stats, rule=rule)


@app.route('/distribuicao/simular', methods=['POST'])
@admin_required
def distribuicao_simular():
    """Simula distribuição de N leads e mostra a previsão"""
    n = int(request.form.get('n_leads', 10))
    # snapshot dos contadores atuais
    users = User.query.filter_by(role='consultor', is_active=True, is_online=True).all()
    if not users:
        users = User.query.filter_by(role='consultor', is_active=True).all()

    week_start = datetime.utcnow() - timedelta(days=7)
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week = {u.id: Lead.query.filter(Lead.owner_id == u.id, Lead.created_at >= week_start).count() for u in users}
    day = {u.id: Lead.query.filter(Lead.owner_id == u.id, Lead.created_at >= day_start).count() for u in users}
    quotas = {u.id: max(u.weekly_quota, 1) for u in users}
    names = {u.id: u.name for u in users}

    sequence = []
    for i in range(n):
        # escolhe o de menor pressure, desempate por menor day
        best = min(users, key=lambda u: (week[u.id] / quotas[u.id], day[u.id], u.id))
        sequence.append({'idx': i+1, 'user': names[best.id]})
        week[best.id] += 1
        day[best.id] += 1

    summary = defaultdict(int)
    for s in sequence:
        summary[s['user']] += 1

    return render_template('distribuicao_simular.html',
        sequence=sequence,
        summary=dict(summary),
        n=n
    )


# ----------------------------------------------------------------------------
# ROTAS — USUÁRIOS (admin)
# ----------------------------------------------------------------------------

@app.route('/usuarios')
@admin_required
def usuarios():
    users = User.query.order_by(User.role.desc(), User.name).all()
    return render_template('usuarios.html', users=users)


@app.route('/usuarios/criar', methods=['POST'])
@admin_required
def usuario_create():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    role = request.form.get('role', 'consultor')
    quota = int(request.form.get('weekly_quota', 20))
    if not name or not email or not password:
        flash('Preencha todos os campos.', 'warning')
        return redirect(url_for('usuarios'))
    if User.query.filter_by(email=email).first():
        flash('Email já cadastrado.', 'warning')
        return redirect(url_for('usuarios'))
    u = User(name=name, email=email, role=role, weekly_quota=quota)
    u.set_password(password)
    db.session.add(u)
    log('user_created', f'Usuário criado: {email} ({role})')
    db.session.commit()
    flash('Usuário criado.', 'success')
    return redirect(url_for('usuarios'))


@app.route('/usuarios/<int:uid>/toggle', methods=['POST'])
@admin_required
def usuario_toggle(uid):
    u = User.query.get_or_404(uid)
    u.is_active = not u.is_active
    log('user_toggle', f'Usuário {u.email} ativo={u.is_active}')
    db.session.commit()
    return redirect(url_for('usuarios'))


# ----------------------------------------------------------------------------
# ROTAS — AUDITORIA / LOGS
# ----------------------------------------------------------------------------

@app.route('/auditoria')
@admin_required
def auditoria():
    page = request.args.get('page', 1, type=int)
    logs = AuditLog.query.order_by(desc(AuditLog.created_at)).limit(500).all()
    return render_template('auditoria.html', logs=logs)


# ----------------------------------------------------------------------------
# ROTAS — RELATÓRIOS
# ----------------------------------------------------------------------------

@app.route('/relatorios')
@login_required
def relatorios():
    u = current_user()
    week_start = datetime.utcnow() - timedelta(days=7)

    if u.role == 'admin':
        users = User.query.filter_by(role='consultor', is_active=True).all()
    else:
        users = [u]

    report = []
    for c in users:
        total = Lead.query.filter_by(owner_id=c.id).count()
        week = Lead.query.filter(Lead.owner_id == c.id, Lead.created_at >= week_start).count()
        responded = Lead.query.filter(Lead.owner_id == c.id, Lead.last_inbound_at != None).count()
        closed = Lead.query.filter(Lead.owner_id == c.id, Lead.stage == 'plano_fechado').count()
        cold = Lead.query.filter(Lead.owner_id == c.id, Lead.stage == 'lead_frio').count()
        parados = Lead.query.filter(
            Lead.owner_id == c.id,
            Lead.last_outbound_at != None,
            Lead.last_outbound_at < datetime.utcnow() - timedelta(days=2),
            Lead.last_inbound_at == None
        ).count()
        report.append({
            'user': c,
            'total': total,
            'week': week,
            'responded': responded,
            'response_rate': round((responded/total*100), 1) if total else 0,
            'closed': closed,
            'cold': cold,
            'parados': parados,
            'conversion': round((closed/total*100), 1) if total else 0,
        })

    # gargalo: maior estágio
    stage_totals = {}
    for sid, label in PIPELINE_STAGES:
        if u.role == 'admin':
            stage_totals[label] = Lead.query.filter_by(stage=sid).count()
        else:
            stage_totals[label] = Lead.query.filter_by(stage=sid, owner_id=u.id).count()

    return render_template('relatorios.html', report=report, stage_totals=stage_totals)


# ----------------------------------------------------------------------------
# ROTAS — CONFIGURAÇÕES, NOTIFICAÇÕES, PERFIL
# ----------------------------------------------------------------------------

@app.route('/configuracoes', methods=['GET', 'POST'])
@admin_required
def configuracoes():
    rule = DistributionRule.query.first()
    if not rule:
        rule = DistributionRule()
        db.session.add(rule)
        db.session.commit()
    if request.method == 'POST':
        rule.mode = request.form.get('mode', 'round_robin_proporcional')
        rule.redistribute_offline = bool(request.form.get('redistribute_offline'))
        rule.cold_after_days = int(request.form.get('cold_after_days', 3))
        log('config_updated', 'Configurações gerais atualizadas')
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(url_for('configuracoes'))
    return render_template('configuracoes.html', rule=rule)


@app.route('/notificacoes')
@login_required
def notificacoes():
    u = current_user()
    # notificações baseadas em SLA quebrado, leads sem resposta há muito tempo, novos leads
    base = Lead.query if u.role == 'admin' else Lead.query.filter_by(owner_id=u.id)

    novos = base.filter(Lead.created_at >= datetime.utcnow() - timedelta(hours=24)).all()
    sla_quebrado = []
    for lead in base.all():
        if lead.sla_minutes and lead.sla_minutes > 60:
            sla_quebrado.append(lead)

    frios_recentes = base.filter(Lead.stage == 'lead_frio').limit(10).all()

    return render_template('notificacoes.html',
        novos=novos,
        sla_quebrado=sla_quebrado,
        frios=frios_recentes,
    )


@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    u = current_user()
    if request.method == 'POST':
        u.name = request.form.get('name', u.name)
        new_password = request.form.get('new_password', '')
        if new_password:
            u.set_password(new_password)
        u.is_online = bool(request.form.get('is_online'))
        log('profile_updated', 'Perfil atualizado', user_id=u.id)
        db.session.commit()
        flash('Perfil atualizado.', 'success')
        return redirect(url_for('perfil'))
    return render_template('perfil.html', u=u)


# ----------------------------------------------------------------------------
# API auxiliar (snippets, distribuição, etc) — para realtime/AJAX
# ----------------------------------------------------------------------------

@app.route('/api/snippets')
@login_required
def api_snippets():
    u = current_user()
    snippets = Snippet.query.filter_by(user_id=u.id).all()
    return jsonify([{'shortcut': s.shortcut, 'body': s.body} for s in snippets])


@app.route('/api/render-template/<int:tid>/<int:lead_id>')
@login_required
def api_render_template(tid, lead_id):
    u = current_user()
    t = Template.query.get_or_404(tid)
    lead = Lead.query.get_or_404(lead_id)
    return jsonify({'body': render_variables(t.body, lead, u)})


@app.route('/api/render-followup/<int:fid>/<int:lead_id>')
@login_required
def api_render_followup(fid, lead_id):
    u = current_user()
    f = FollowUp.query.get_or_404(fid)
    lead = Lead.query.get_or_404(lead_id)
    return jsonify({'body': render_variables(f.body, lead, u)})


# ----------------------------------------------------------------------------
# TAREFAS — agendamento com trigger por popup
# ----------------------------------------------------------------------------
@app.route('/tarefas', methods=['GET', 'POST'])
@login_required
def tarefas():
    u = current_user()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        kind = request.form.get('kind', 'lembrete')
        scheduled_at_raw = request.form.get('scheduled_at', '').strip()
        lead_id_raw = request.form.get('lead_id', '').strip()
        if not title or not scheduled_at_raw:
            flash('Título e data/hora são obrigatórios.', 'danger')
            return redirect(url_for('tarefas'))
        try:
            scheduled_at = datetime.strptime(scheduled_at_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Data/hora inválida.', 'danger')
            return redirect(url_for('tarefas'))
        task = Task(
            user_id=u.id,
            lead_id=int(lead_id_raw) if lead_id_raw.isdigit() else None,
            title=title,
            description=description,
            kind=kind,
            scheduled_at=scheduled_at,
        )
        db.session.add(task)
        log('task_created', f'Tarefa: {title} @ {scheduled_at_raw}')
        db.session.commit()
        flash('Tarefa agendada.', 'success')
        return redirect(url_for('tarefas'))

    # Listar tarefas do usuário separadas por status
    now = datetime.utcnow()
    pending = Task.query.filter_by(user_id=u.id, done=False).order_by(Task.scheduled_at.asc()).all()
    done = Task.query.filter_by(user_id=u.id, done=True).order_by(desc(Task.done_at)).limit(20).all()
    overdue = [t for t in pending if t.scheduled_at < now]
    upcoming = [t for t in pending if t.scheduled_at >= now]
    # leads do user para vincular ao criar
    leads_q = Lead.query if u.role == 'admin' else Lead.query.filter_by(owner_id=u.id)
    leads = leads_q.order_by(Lead.name).all()
    return render_template('tarefas.html',
                           overdue=overdue, upcoming=upcoming, done=done,
                           leads=leads, now=now)


@app.route('/tarefas/<int:tid>/done', methods=['POST'])
@login_required
def task_done(tid):
    u = current_user()
    t = Task.query.get_or_404(tid)
    if t.user_id != u.id and u.role != 'admin':
        abort(403)
    t.done = True
    t.done_at = datetime.utcnow()
    log('task_done', f'Tarefa concluída: {t.title}', lead_id=t.lead_id)
    db.session.commit()
    return redirect(request.referrer or url_for('tarefas'))


@app.route('/tarefas/<int:tid>/delete', methods=['POST'])
@login_required
def task_delete(tid):
    u = current_user()
    t = Task.query.get_or_404(tid)
    if t.user_id != u.id and u.role != 'admin':
        abort(403)
    log('task_deleted', f'Tarefa removida: {t.title}', lead_id=t.lead_id)
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('tarefas'))


# ----------------------------------------------------------------------------
# REMARKETING — leads com cadência esgotada (3 dias + 4 FUPs/dia)
# ----------------------------------------------------------------------------
@app.route('/remarketing')
@login_required
def remarketing():
    u = current_user()
    base = Lead.query if u.role == 'admin' else Lead.query.filter_by(owner_id=u.id)
    leads = base.filter(Lead.moved_to_remarketing_at.isnot(None))\
                .order_by(desc(Lead.moved_to_remarketing_at)).all()
    # leads que estão prestes a entrar (>2 dias com FUPs e sem resposta) -> warning
    prestes = []
    for lead in base.all():
        if lead.moved_to_remarketing_at:
            continue
        if lead.sent_without_response >= 2 and lead.last_inbound_at is None:
            prestes.append(lead)
    return render_template('remarketing.html', leads=leads, prestes=prestes[:10])


@app.route('/remarketing/<int:lead_id>/call-done', methods=['POST'])
@login_required
def remarketing_call_done(lead_id):
    """Marca que uma ligação de remarketing foi feita"""
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if lead.owner_id != u.id and u.role != 'admin':
        abort(403)
    note = request.form.get('note', '').strip()
    # Cria mensagem de nota
    msg = Message(lead_id=lead.id, user_id=u.id, direction='out',
                  body=f'[LIGAÇÃO REALIZADA] {note}', kind='note')
    db.session.add(msg)
    log('remarketing_call', f'Ligação realizada: {note}', lead_id=lead.id)
    db.session.commit()
    flash('Ligação registrada.', 'success')
    return redirect(url_for('remarketing'))


@app.route('/remarketing/<int:lead_id>/reactivate', methods=['POST'])
@login_required
def remarketing_reactivate(lead_id):
    """Tira o lead do remarketing e volta para 'mensagem_enviada' ou 'em_conversacao'."""
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if lead.owner_id != u.id and u.role != 'admin':
        abort(403)
    lead.moved_to_remarketing_at = None
    lead.stage = 'em_conversacao'
    lead.sent_without_response = 0
    log('remarketing_reactivated', 'Lead reativado a partir do remarketing', lead_id=lead.id)
    db.session.commit()
    flash('Lead reativado.', 'success')
    return redirect(url_for('conversas', lead_id=lead.id))


# ----------------------------------------------------------------------------
# PREFERÊNCIAS — unifica snippets, favoritos e cadência pessoal
# ----------------------------------------------------------------------------
@app.route('/preferencias', methods=['GET', 'POST'])
@login_required
def preferencias():
    u = current_user()
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'cadence':
            u.cadence_per_day = max(1, min(4, int(request.form.get('cadence_per_day', 2))))
            u.cadence_days = max(1, min(3, int(request.form.get('cadence_days', 3))))
            u.cadence_interval_hours = max(1, min(12, int(request.form.get('cadence_interval_hours', 3))))
            log('cadence_updated',
                f'Cadência: {u.cadence_per_day}x/dia por {u.cadence_days} dias (intervalo {u.cadence_interval_hours}h)',
                user_id=u.id)
            db.session.commit()
            flash('Cadência atualizada.', 'success')
        elif action == 'favorites':
            fav_t = request.form.getlist('fav_templates')
            fav_f = request.form.getlist('fav_followups')
            u.favorite_templates = ','.join(fav_t[:3])
            u.favorite_followups = ','.join(fav_f[:5])
            log('favorites_updated', 'Favoritos atualizados', user_id=u.id)
            db.session.commit()
            flash('Favoritos salvos.', 'success')
        elif action == 'snippet_add':
            shortcut = request.form.get('shortcut', '').strip()
            body = request.form.get('body', '').strip()
            if not shortcut.startswith('/'):
                shortcut = '/' + shortcut
            existing = Snippet.query.filter_by(user_id=u.id).count()
            if existing >= 5:
                flash('Máximo de 5 snippets por usuário.', 'warning')
            elif shortcut and body:
                s = Snippet(user_id=u.id, shortcut=shortcut, body=body)
                db.session.add(s)
                log('snippet_created', shortcut, user_id=u.id)
                db.session.commit()
                flash('Snippet criado.', 'success')
        elif action == 'snippet_delete':
            sid = int(request.form.get('snippet_id', 0))
            s = Snippet.query.get(sid)
            if s and s.user_id == u.id:
                log('snippet_deleted', s.shortcut, user_id=u.id)
                db.session.delete(s)
                db.session.commit()
                flash('Snippet removido.', 'success')
        return redirect(url_for('preferencias'))

    snippets = Snippet.query.filter_by(user_id=u.id).all()
    templates = Template.query.filter_by(is_active=True).order_by(Template.title).all()
    followups = FollowUp.query.filter_by(is_active=True).order_by(FollowUp.sequence).all()
    return render_template('preferencias.html',
                           u=u, snippets=snippets,
                           templates=templates, followups=followups)


# ----------------------------------------------------------------------------
# UPLOAD de anexos (imagem, pdf, áudio, qualquer arquivo)
# ----------------------------------------------------------------------------
ALLOWED_MIME_PREFIXES = ('image/', 'audio/', 'video/', 'application/', 'text/')

def _classify_attachment(mime):
    if not mime:
        return 'file'
    if mime.startswith('image/'):
        return 'image'
    if mime.startswith('audio/'):
        return 'audio'
    if mime == 'application/pdf':
        return 'pdf'
    if mime.startswith('video/'):
        return 'video'
    return 'file'


@app.route('/conversas/<int:lead_id>/upload', methods=['POST'])
@login_required
def upload_attachment(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_act_on_lead(u, lead):
        abort(403)

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'nenhum arquivo'}), 400

    original_name = secure_filename(file.filename)
    ext = os.path.splitext(original_name)[1].lower()
    stored_name = f'{uuid.uuid4().hex}{ext}'
    abs_path = os.path.join(_UPLOAD_DIR, stored_name)
    file.save(abs_path)
    size = os.path.getsize(abs_path)
    mime = file.mimetype or mimetypes.guess_type(original_name)[0] or 'application/octet-stream'
    kind = _classify_attachment(mime)

    caption = request.form.get('caption', '').strip()
    body_marker = f'📎 {original_name}' if not caption else caption

    msg = Message(lead_id=lead.id, user_id=u.id, direction='out',
                  body=body_marker, kind='attachment')
    db.session.add(msg)
    db.session.flush()

    att = Attachment(message_id=msg.id, filename=original_name, stored_name=stored_name,
                     mime_type=mime, size_bytes=size, kind=kind)
    db.session.add(att)

    lead.last_message_at = datetime.utcnow()
    lead.last_outbound_at = datetime.utcnow()
    log('attachment_sent', f'{kind}: {original_name}', lead_id=lead.id)
    db.session.commit()
    return jsonify({
        'ok': True,
        'attachment': {
            'id': att.id, 'filename': original_name,
            'url': url_for('static', filename=f'uploads/{stored_name}'),
            'kind': kind, 'mime': mime, 'size': size,
            'caption': caption,
        }
    })


# ----------------------------------------------------------------------------
# API de eventos (popup novo lead, lembrete de tarefa)
# Front faz long-poll a cada ~15s
# ----------------------------------------------------------------------------
@app.route('/api/events')
@login_required
def api_events():
    u = current_user()
    now = datetime.utcnow()
    since_raw = request.args.get('since')
    try:
        since = datetime.fromisoformat(since_raw) if since_raw else now - timedelta(minutes=2)
    except ValueError:
        since = now - timedelta(minutes=2)

    # 1) Leads novos atribuídos a este usuário desde "since"
    new_leads = Lead.query.filter(
        Lead.owner_id == u.id,
        Lead.created_at >= since
    ).order_by(desc(Lead.created_at)).limit(5).all()

    # 2) Tarefas que venceram (scheduled <= now) e ainda não foram triggered
    due_tasks = Task.query.filter(
        Task.user_id == u.id,
        Task.done == False,
        Task.triggered == False,
        Task.scheduled_at <= now,
    ).all()
    # Marca como triggered para não repetir o popup
    for t in due_tasks:
        t.triggered = True
    if due_tasks:
        db.session.commit()

    return jsonify({
        'now': now.isoformat(),
        'new_leads': [
            {'id': l.id, 'name': l.name, 'source': l.source or 'manual',
             'phone': l.phone or '', 'url': url_for('conversas', lead_id=l.id)}
            for l in new_leads
        ],
        'due_tasks': [
            {'id': t.id, 'title': t.title, 'kind': t.kind,
             'description': t.description or '',
             'lead_id': t.lead_id,
             'url': url_for('conversas', lead_id=t.lead_id) if t.lead_id else url_for('tarefas')}
            for t in due_tasks
        ],
    })


# ----------------------------------------------------------------------------
# REDISTRIBUIR LEAD (master / coordenador)
# ----------------------------------------------------------------------------
@app.route('/lead/<int:lead_id>/redistribuir', methods=['POST'])
@login_required
def lead_redistribuir(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if u.role not in ('master', 'coordenador'):
        abort(403)
    if not can_see_lead(u, lead):
        abort(403)

    target_id = request.form.get('owner_id', type=int)
    if target_id:
        target = User.query.get(target_id)
    else:
        target = pick_next_owner()
    if not target:
        flash('Nenhum consultor disponível.', 'danger')
        return redirect(url_for('conversas', lead=lead_id))

    old_name = lead.owner.name if lead.owner else '—'
    lead.owner_id = target.id
    log('lead_redistributed',
        f'Lead transferido de {old_name} para {target.name}', lead_id=lead.id)
    db.session.commit()
    flash(f'Lead transferido para {target.name}.', 'success')
    return redirect(url_for('conversas', lead=lead_id))


# ----------------------------------------------------------------------------
# BLOQUEAR / DESBLOQUEAR CORRETOR (master / coordenador)
# ----------------------------------------------------------------------------
@app.route('/usuario/<int:uid>/toggle-block', methods=['POST'])
@login_required
def user_toggle_block(uid):
    u = current_user()
    if u.role not in ('master', 'coordenador', 'admin'):
        abort(403)
    target = User.query.get_or_404(uid)
    if u.role == 'coordenador' and target.id not in visible_user_ids(u):
        abort(403)
    target.is_blocked = not target.is_blocked
    target.blocked_reason = request.form.get('reason', '').strip()
    log('user_blocked' if target.is_blocked else 'user_unblocked',
        f'{target.name}: {target.blocked_reason or "—"}',
        user_id=target.id)
    db.session.commit()
    flash(f'Corretor {"bloqueado" if target.is_blocked else "desbloqueado"}.',
          'warning' if target.is_blocked else 'success')
    return redirect(request.referrer or url_for('usuarios'))


# ----------------------------------------------------------------------------
# EQUIPE — visão por consultor (master / coordenador)
# Mostra cada consultor visível com KPIs rápidos + lista de leads/conversas
# ----------------------------------------------------------------------------
@app.route('/equipe')
@login_required
def equipe():
    u = current_user()
    if u.role not in ('master', 'coordenador'):
        abort(403)

    # Consultores que esse user pode supervisionar
    if u.role == 'master':
        consultores = User.query.filter_by(role='consultor').order_by(User.name).all()
    else:
        visible = visible_user_ids(u)
        consultores = User.query.filter(
            User.role == 'consultor', User.id.in_(visible)
        ).order_by(User.name).all()

    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    consultor_data = []
    for c in consultores:
        leads_q = Lead.query.filter_by(owner_id=c.id)
        total = leads_q.count()
        leads_today = leads_q.filter(Lead.created_at >= today).count()
        leads_week = leads_q.filter(Lead.created_at >= week_start).count()
        em_conversa = leads_q.filter(Lead.stage == 'em_conversacao').count()
        fechados = leads_q.filter(Lead.stage == 'plano_fechado').count()
        # Leads com SLA quebrado
        sla_broken = 0
        for l in leads_q.filter(Lead.last_inbound_at.isnot(None)).all():
            if l.sla_minutes and l.sla_minutes > 60:
                sla_broken += 1
        # Faturamento em aberto (potencial nas etapas ativas)
        active_stages = ['em_conversacao','cotacao_enviada','proposta_digitada',
                         'em_analise','aguardando_pagamento']
        revenue_open = leads_q.filter(Lead.stage.in_(active_stages))\
            .with_entities(func.coalesce(func.sum(Lead.budget), 0.0)).scalar() or 0
        revenue_closed = leads_q.filter(Lead.stage == 'plano_fechado')\
            .with_entities(func.coalesce(func.sum(Lead.budget), 0.0)).scalar() or 0
        consultor_data.append({
            'user': c,
            'total': total,
            'leads_today': leads_today,
            'leads_week': leads_week,
            'em_conversa': em_conversa,
            'fechados': fechados,
            'sla_broken': sla_broken,
            'revenue_open': float(revenue_open),
            'revenue_closed': float(revenue_closed),
            'pressure': round((leads_week / max(c.weekly_quota, 1)) * 100, 1),
        })

    # Filtro opcional: focar num consultor específico → lista de conversas dele
    focus_id = request.args.get('consultor', type=int)
    focus_user = None
    focus_leads = []
    if focus_id:
        focus_user = User.query.get(focus_id)
        if focus_user and focus_user.id in {c['user'].id for c in consultor_data}:
            focus_leads = Lead.query.filter_by(owner_id=focus_id)\
                .order_by(desc(Lead.last_message_at), desc(Lead.created_at)).all()
        else:
            focus_user = None

    return render_template('equipe.html',
                           consultor_data=consultor_data,
                           focus_user=focus_user,
                           focus_leads=focus_leads,
                           now=now)


# ----------------------------------------------------------------------------
# API: visualizar conversa de um lead (modal) — master / coordenador
# Retorna JSON com mensagens e dados do lead
# ----------------------------------------------------------------------------
@app.route('/api/lead/<int:lead_id>/thread')
@login_required
def api_lead_thread(lead_id):
    u = current_user()
    lead = Lead.query.get_or_404(lead_id)
    if not can_see_lead(u, lead):
        return jsonify({'error': 'forbidden'}), 403

    msgs = []
    for m in lead.messages:
        attachments = [{
            'kind': a.kind,
            'filename': a.filename,
            'url': url_for('static', filename=f'uploads/{a.stored_name}'),
            'mime': a.mime_type,
        } for a in m.attachments]
        msgs.append({
            'id': m.id,
            'direction': m.direction,
            'kind': m.kind,
            'body': m.body,
            'created_at': m.created_at.strftime('%d/%m/%Y %H:%M:%S'),
            'sender': m.user.name if m.user else (lead.name + ' (lead)'),
            'attachments': attachments,
        })

    return jsonify({
        'lead': {
            'id': lead.id, 'name': lead.name,
            'phone': lead.phone, 'email': lead.email,
            'source': lead.source,
            'stage': lead.stage, 'stage_label': lead.stage_label,
            'budget': lead.budget,
            'owner': lead.owner.name if lead.owner else None,
            'owner_id': lead.owner_id,
            'categoria': lead.categoria,
            'vidas': lead.vidas,
        },
        'messages': msgs,
        'can_act': can_act_on_lead(u, lead),
    })


# ----------------------------------------------------------------------------
# OPERADORAS — CRUD para admin/master
# ----------------------------------------------------------------------------
@app.route('/operadoras', methods=['GET', 'POST'])
@login_required
def operadoras_list():
    u = current_user()
    if not can_manage_users(u):
        abort(403)
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'create':
            categoria = request.form.get('categoria', '').strip()
            nome = request.form.get('nome', '').strip()
            if categoria and nome:
                db.session.add(Operadora(categoria=categoria, nome=nome))
                db.session.commit()
                flash('Operadora criada.', 'success')
        elif action == 'toggle':
            op = Operadora.query.get(int(request.form.get('id', 0)))
            if op:
                op.is_active = not op.is_active
                db.session.commit()
        elif action == 'delete':
            op = Operadora.query.get(int(request.form.get('id', 0)))
            if op:
                db.session.delete(op); db.session.commit()
                flash('Operadora removida.', 'success')
        return redirect(url_for('operadoras_list'))
    operadoras = Operadora.query.order_by(Operadora.categoria, Operadora.nome).all()
    return render_template('operadoras.html', operadoras=operadoras)



# ----------------------------------------------------------------------------

def seed_data():
    if User.query.first():
        return
    print('Populando dados de demonstração...')

    # ===== HIERARQUIA: MASTER → COORDENADOR → LÍDER → CONSULTORES =====
    master = User(name='Master', email='master@crm.com', role='master', weekly_quota=0)
    master.set_password('master')
    db.session.add(master); db.session.flush()

    admin = User(name='Admin', email='admin@crm.com', role='admin', weekly_quota=0,
                 manager_id=master.id)
    admin.set_password('admin')
    db.session.add(admin)

    coord = User(name='Carolina (Coord)', email='coord@crm.com', role='coordenador',
                 weekly_quota=0, manager_id=master.id)
    coord.set_password('123456')
    db.session.add(coord); db.session.flush()

    lider = User(name='Lucas (Líder)', email='lider@crm.com', role='lider',
                 weekly_quota=0, manager_id=coord.id)
    lider.set_password('123456')
    db.session.add(lider); db.session.flush()

    # Consultores: 3 reportam ao líder
    roberto = User(name='Roberto', email='roberto@crm.com', role='consultor',
                   weekly_quota=50, manager_id=lider.id)
    roberto.set_password('123456')
    marcio = User(name='Márcio', email='marcio@crm.com', role='consultor',
                  weekly_quota=40, manager_id=lider.id)
    marcio.set_password('123456')
    fernando = User(name='Fernando', email='fernando@crm.com', role='consultor',
                    weekly_quota=20, manager_id=lider.id)
    fernando.set_password('123456')
    db.session.add_all([roberto, marcio, fernando])
    db.session.flush()

    # ===== OPERADORAS oficiais =====
    for categoria, nome in PLANOS_OFICIAIS:
        db.session.add(Operadora(categoria=categoria, nome=nome))

    # Templates globais
    templates = [
        Template(title='Abordagem Inicial', category='abordagem',
                 body='Olá {{nome}}! Aqui é {{consultor}}. Tudo bem? Vi que você se interessou pelos nossos serviços e queria entender melhor o que está buscando.'),
        Template(title='Follow-up Consultivo', category='followup',
                 body='Oi {{nome}}, conseguiu pensar sobre nossa conversa? Posso te ajudar com alguma dúvida específica?'),
        Template(title='Cobrança Amigável', category='cobranca',
                 body='Olá {{nome}}, passando para verificar se conseguiu providenciar o documento que combinamos. Qualquer coisa estou à disposição!'),
        Template(title='Reativação', category='reativacao',
                 body='Oi {{nome}}, faz um tempo que não conversamos. Surgiu uma novidade que pode te interessar muito. Posso te enviar?'),
        Template(title='Apresentação Comercial', category='apresentacao',
                 body='{{nome}}, segue a apresentação completa do nosso plano. Qualquer dúvida estou à disposição para conversar.'),
    ]
    db.session.add_all(templates)
    db.session.flush()

    # Marca primeira template como favorita do Roberto (para a 1ª msg automática via API funcionar)
    roberto.favorite_templates = str(templates[0].id)

    # Follow-ups globais
    fups = [
        FollowUp(title='FUP 1 - Verificação', sequence=1, days_after=1,
                 body='Olá {{nome}}, conseguiu analisar?'),
        FollowUp(title='FUP 2 - Dúvidas', sequence=2, days_after=2,
                 body='Passando para verificar se ficou alguma dúvida.'),
        FollowUp(title='FUP 3 - Retorno', sequence=3, days_after=3,
                 body='Consegue me dar um retorno hoje?'),
        FollowUp(title='FUP 4 - Última tentativa', sequence=4, days_after=5,
                 body='{{nome}}, vou encerrar seu atendimento por aqui. Se mudar de ideia, é só me chamar!'),
    ]
    db.session.add_all(fups)

    # Snippets de exemplo (Roberto)
    db.session.add_all([
        Snippet(user_id=roberto.id, shortcut='/oi', body='Bom dia!'),
        Snippet(user_id=roberto.id, shortcut='/verif', body='Vou verificar e já te retorno.'),
        Snippet(user_id=roberto.id, shortcut='/prop', body='Segue a proposta em anexo.'),
        Snippet(user_id=roberto.id, shortcut='/conf', body='Pode me confirmar, por favor?'),
        Snippet(user_id=roberto.id, shortcut='/obg', body='Obrigado pelo retorno!'),
    ])

    # Leads de demonstração (com BUDGET)
    sample_leads = [
        # name, phone, email, company, source, owner, stage, budget, tem_cnpj, vidas, pref
        ('Carlos Mendes', '21999990001', 'carlos@empresa.com', 'Tech Solutions', 'meta_ads', roberto.id, 'em_conversacao', 4500, True, 8, 'whatsapp'),
        ('Ana Souza', '21999990002', 'ana@empresa.com', '', 'site', roberto.id, 'cotacao_enviada', 12000, False, 2, 'whatsapp'),
        ('Pedro Lima', '21999990003', 'pedro@empresa.com', 'PL Comercial', 'meta_ads', marcio.id, 'mensagem_enviada', 3200, True, 5, 'whatsapp'),
        ('Juliana Costa', '21999990004', 'ju@empresa.com', 'JC Consultoria', 'site', marcio.id, 'proposta_digitada', 8800, True, 12, 'email'),
        ('Rafael Torres', '21999990005', 'rafa@empresa.com', 'RT Group', 'evento', fernando.id, 'em_analise', 15000, True, 18, 'whatsapp'),
        ('Mariana Alves', '21999990006', 'mari@empresa.com', 'MA Indústria', 'google_ads', roberto.id, 'aguardando_pagamento', 22000, True, 30, 'whatsapp'),
        ('Bruno Pereira', '21999990007', 'bruno@empresa.com', 'BP Logística', 'indicacao', roberto.id, 'plano_fechado', 9500, True, 14, 'whatsapp'),
        ('Camila Silva', '21999990008', 'cami@empresa.com', '', 'site', marcio.id, 'lead_frio', 2400, False, 1, 'whatsapp'),
        ('Diego Rocha', '21999990009', 'diego@empresa.com', 'DR Veículos', 'meta_ads', fernando.id, 'em_conversacao', 6700, True, 10, 'telefone'),
        ('Eduardo Faria', '21999990010', 'edu@empresa.com', 'EF Imóveis', 'site', roberto.id, 'mensagem_enviada', 5000, True, 6, 'whatsapp'),
    ]
    now = datetime.utcnow()
    saved_leads = []
    # Pega operadora padrão para criar cotações
    op_amil_pme = Operadora.query.filter_by(categoria='PME', nome='Amil').first()
    op_sulam_pf = Operadora.query.filter_by(categoria='PF', nome='Assim').first()
    for i, (n, p, e, c, s, oid, stage, budget, tem_cnpj, vidas, pref) in enumerate(sample_leads):
        categoria = 'PME' if tem_cnpj else 'PF'
        lead = Lead(
            name=n, phone=p, email=e, company=c, source=s,
            source_visible_to_consultor=False,  # origem oculta para consultor
            owner_id=oid, stage=stage, budget=budget,
            tem_cnpj=tem_cnpj, categoria=categoria, vidas=vidas,
            preferencia_contato=pref,
            created_at=now - timedelta(days=i, hours=i*2),
            last_message_at=now - timedelta(hours=i*3),
            last_outbound_at=now - timedelta(hours=i*3),
            stage_entered_at=now - timedelta(hours=i*3),
        )
        db.session.add(lead)
        db.session.flush()
        saved_leads.append(lead)

        # Histórico inicial
        db.session.add(LeadStageHistory(lead_id=lead.id, user_id=oid,
                                        from_stage=None, to_stage='mensagem_enviada',
                                        entered_at=lead.created_at))
        # Histórico de mudança para stage atual (se != mensagem_enviada)
        if stage != 'mensagem_enviada':
            db.session.add(LeadStageHistory(lead_id=lead.id, user_id=oid,
                                            from_stage='mensagem_enviada', to_stage=stage,
                                            entered_at=lead.stage_entered_at))

        # Cria cotação se stage >= cotacao_enviada
        stages_with_quote = ('cotacao_enviada', 'proposta_digitada', 'em_analise',
                             'aguardando_pagamento', 'plano_fechado')
        if stage in stages_with_quote:
            op = op_amil_pme if tem_cnpj else op_sulam_pf
            q = Quotation(
                lead_id=lead.id, operadora_id=op.id if op else None,
                subproduto='Plano Saúde Pro' if tem_cnpj else 'Saúde Individual',
                valor=budget, vidas=vidas, bairro='Copacabana',
            )
            if stage in ('proposta_digitada', 'em_analise', 'aguardando_pagamento', 'plano_fechado'):
                q.confirmed_at_proposta = lead.stage_entered_at
            if stage in ('em_analise', 'aguardando_pagamento', 'plano_fechado'):
                q.confirmed_at_analise = lead.stage_entered_at
            if stage in ('aguardando_pagamento', 'plano_fechado'):
                q.data_boleto = (now + timedelta(days=5)).date()
                q.data_vigencia = (now + timedelta(days=15)).date()
            db.session.add(q)

        # Mensagens de exemplo
        if stage != 'mensagem_enviada':
            db.session.add(Message(
                lead_id=lead.id, user_id=oid, direction='out',
                body=f'Olá {n}! Tudo bem? Vi seu interesse.',
                created_at=lead.created_at + timedelta(minutes=5)
            ))
            db.session.add(Message(
                lead_id=lead.id, user_id=None, direction='in',
                body='Oi! Tudo certo, quero entender mais.',
                created_at=lead.created_at + timedelta(minutes=15)
            ))
            lead.last_inbound_at = lead.created_at + timedelta(minutes=15)
            db.session.add(Message(
                lead_id=lead.id, user_id=oid, direction='out',
                body='Perfeito! Vou te explicar tudo. Qual o melhor horário?',
                created_at=lead.created_at + timedelta(minutes=20)
            ))
        else:
            db.session.add(Message(
                lead_id=lead.id, user_id=oid, direction='out',
                body=f'Olá {n}! Aqui é da equipe. Tudo bem?',
                created_at=lead.created_at
            ))

    # Marca Camila como remarketing (esgotou cadência)
    camila = next((l for l in saved_leads if l.name.startswith('Camila')), None)
    if camila:
        camila.moved_to_remarketing_at = now - timedelta(hours=8)
        camila.sent_without_response = 4

    # Tarefas de demonstração
    db.session.add_all([
        Task(user_id=roberto.id, lead_id=saved_leads[0].id,
             title='Retornar para Carlos com a cotação detalhada',
             description='Cliente pediu detalhamento da Suite Pro.',
             kind='followup_manual',
             scheduled_at=now + timedelta(hours=3)),
        Task(user_id=roberto.id, lead_id=saved_leads[1].id,
             title='Ligar para Ana — fechamento',
             description='Ana está em estágio de cotação enviada. Avançar.',
             kind='ligacao',
             scheduled_at=now + timedelta(days=1, hours=2)),
        Task(user_id=marcio.id, lead_id=saved_leads[3].id,
             title='Enviar contrato para Juliana',
             kind='followup_manual',
             scheduled_at=now + timedelta(hours=6)),
        Task(user_id=roberto.id, lead_id=saved_leads[5].id,
             title='Confirmar pagamento Mariana',
             kind='lembrete',
             scheduled_at=now - timedelta(hours=1)),  # vencida (para mostrar destaque)
    ])

    # Configuração padrão
    rule = DistributionRule(mode='round_robin_proporcional', redistribute_offline=True, cold_after_days=3)
    db.session.add(rule)

    db.session.commit()
    print('Seed concluído!')
    print('  Master:      master@crm.com / master')
    print('  Admin:       admin@crm.com / admin')
    print('  Coordenador: coord@crm.com / 123456')
    print('  Líder:       lider@crm.com / 123456')
    print('  Consultor:   roberto@crm.com / 123456 (Márcio e Fernando idem)')


# ----------------------------------------------------------------------------
# RUN
# ----------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    seed_data()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
