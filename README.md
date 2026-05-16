# CRMConversacional

## Sistema CRM / SaaS Inteligente + Financeiro + WhatsApp + IA completo, estilo WhatsApp corporativo, focado em vendas consultivas (corretagem, consultoria).

## Stack: **Flask + SQLAlchemy + MySQL + Bootstrap 5**.

### 6 abas para o corretor · Pipeline embutido na conversa · Cadência pessoal · Tarefas com pop-up · Remarketing · Anexos no chat.

---

## 🚀 Rodar em 30 segundos

```bash
pip install flask flask-sqlalchemy werkzeug
python app.py
# abra http://127.0.0.1:5000
```

Para resetar: `rm -rf instance && python app.py`

---

## 🔐 Logins de demonstração

| Papel       | E-mail                 | Senha    | Quota |
|-------------|------------------------|----------|-------|
| Admin       | `admin@crm.com`        | `admin`  | —     |
| Consultor   | `roberto@crm.com`      | `123456` | 50    |
| Consultor   | `marcio@crm.com`       | `123456` | 40    |
| Consultor   | `fernando@crm.com`     | `123456` | 20    |

---

## 🗂️ As 6 abas do corretor

| # | Aba              | O que faz                                                                  |
|---|------------------|----------------------------------------------------------------------------|
| 1 | **Conversas**    | Núcleo — chat estilo WhatsApp + pipeline lateral embutido + anexos         |
| 2 | **Pipeline**     | Visão Kanban com drag-and-drop de 8 estágios                               |
| 3 | **Dashboard**    | KPIs operacionais + faturamento estipulado (potencial · fechado · perdido) |
| 4 | **Tarefas**      | Agendamento com pop-up automático no horário (toast + som)                 |
| 5 | **Remarketing**  | Leads que esgotaram a cadência → fila de ligações                          |
| 6 | **Preferências** | Cadência pessoal · favoritos · snippets (até 5 por usuário)                |


> Admin tem todas as 6 + uma seção extra: Usuários, Distribuição, Templates, Follow-ups, Relatórios, Auditoria, Config.

---

## ⚡ Pipeline embutido na conversa

Sem sair de `/conversas`, o painel lateral direito mostra **as 8 etapas como botões verticais**.
Clicou, moveu. Tudo em uma tela. Ainda no mesmo painel:

- **Orçamento estipulado** (editável) — entra no Dashboard como faturamento
- **SLA** e contador de FUPs do dia
- **Dados do lead** e **tags**
- **Nota interna rápida**
- **Agendar tarefa** vinculada ao lead

---

## ⏰ Cadência pessoal de follow-up

Configurada por cada corretor em **Preferências**:

- **FUPs por dia** (1 a 4) — limite duro por lead/dia
- **Dias mantendo cadência** (1 a 3)
- **Intervalo mínimo** entre FUPs (1h a 12h)

O sistema **bloqueia o envio** se passar do limite e exibe quanto tempo falta para o próximo. Após esgotar a cadência, o lead vai automaticamente para **Remarketing**, onde uma **tarefa de ligação é criada** no horário sugerido.

---

## 🔔 Pop-up de novo lead (som + badge + toast)

Polling a cada 15s em `/api/events`. Quando há:

- Novo lead atribuído ao usuário
- Tarefa que acabou de vencer

→ Toca um **som "ding"** (WebAudio, sem arquivo externo)
→ Atualiza **badge no menu lateral**
→ Mostra **toast no canto direito por 3s** com botão "Atender agora" que abre a conversa

---

## 📎 Anexos na conversa

Botão de clip 📎 no composer aceita:

- Imagens (renderizadas inline, clique para ampliar)
- PDFs (link com ícone)
- Áudios (player nativo)
- Vídeos (player nativo)
- Qualquer arquivo (até 25 MB)

Salvos em `static/uploads/<uuid>.<ext>` e linkados ao `Message` via tabela `Attachment`.

---

## 📁 Estrutura

```
crm_conversacional/
├── app.py                        # 48 rotas, 9 modelos
├── static/
│   ├── css/app.css               # design system ~1400 linhas
│   ├── imgs/
│   ├── js/app.js                 # ~430 linhas (upload, poll, snippets, kanban DnD, som)
│   └── uploads/                  # anexos enviados
├── templates/                    # 19 templates Jinja2
│   ├── base.html
│   ├── login.html
│   ├── conversas.html            # ⭐ núcleo (3 colunas + pipeline embutido)
│   ├── pipeline.html
│   ├── dashboard.html            # KPIs financeiros
│   ├── tarefas.html              # ⭐ novo
│   ├── _task_row.html            # partial
│   ├── remarketing.html          # ⭐ novo
│   ├── preferencias.html         # ⭐ novo (cadência + favoritos + snippets)
│   ├── lead_detail.html
│   ├── templates.html / followups.html / snippets.html
│   ├── distribuicao.html / distribuicao_simular.html
│   ├── usuarios.html / auditoria.html / relatorios.html
│   ├── configuracoes.html / notificacoes.html / perfil.html
└── instance/crm.db               # SQLite criado no 1º run
```

---

## 🧾 Modelo de dados (9 tabelas)

```
User             ┐
                 │ owner
Lead ────────────┴──→ budget, moved_to_remarketing_at, fups_sent_today, ...
  │ messages
  ▼
Message ──→ Attachment (image | audio | pdf | video | file)
  │
  └──→ Template, FollowUp, Snippet (pessoal)

Task             owner_id, lead_id (opcional), scheduled_at, triggered
AuditLog         registro de tudo
DistributionRule mode, redistribute_offline, cold_after_days
```

**Campos:**
- `User`: `cadence_per_day`, `cadence_days`, `cadence_interval_hours`
- `Lead`: `budget`, `moved_to_remarketing_at`, `fups_sent_today`, `fups_last_date`

---

## 🤖 Automações ativas

| Trigger                                               | Ação                                                            |
|-------------------------------------------------------|-----------------------------------------------------------------|
| Lead responde (inbound)                               | Move automaticamente para "Em Conversação"                      |
| Corretor envia FUP além do limite diário              | **Bloqueado** com mensagem explicativa                          |
| Lead esgota cadência (3+ FUPs · 3+ dias sem resposta) | Move para **Remarketing** + cria **Tarefa de ligação** em 2h    |
| Tarefa atinge horário agendado                        | **Pop-up + som** no navegador do consultor                      |
| Novo lead atribuído                                   | **Pop-up + som** no navegador do owner                          |
| Reset diário do contador de FUPs                      | Roda em todo dashboard/conversa                                 |

---

## 🔨 Desenvolvimento

### Criado e desenvolvido em família.

### **Luiz Claudio Dias Gomes**

#### 📧 luizcow@netscape.net

#### 🔗 [GitHub](https://github.com/LuizCowBTF/)

#### 💼 [LinkedIn](https://www.linkedin.com/in/luiz-claudio-dias-gomes/)

#

### **Fábio Damico Olivieri Dias Gomes**

#### 📧 fabiodamicogomes@gmail.com

#### 🔗 [GitHub](https://github.com/FabioDODG/)

#### 💼 [LinkedIn](https://www.linkedin.com/in/fabiodamicoolivieri/)




Pronto para usar. Boa venda! 🟢


