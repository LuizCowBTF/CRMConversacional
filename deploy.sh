#!/bin/bash
# ============================================================================
# deploy.sh - Script de deploy para produção
# ============================================================================
# Uso: chmod +x deploy.sh && ./deploy.sh
# ============================================================================

set -e  # Para o script se qualquer comando falhar

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                                                               ║"
echo "║     CRM CONVERSACIONAL - DEPLOY AUTOMATIZADO                  ║"
echo "║                                                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar se .env existe
if [ ! -f .env ]; then
    echo -e "${RED}❌ Arquivo .env não encontrado!${NC}"
    echo -e "${YELLOW}Copie .env.example para .env e configure as variáveis${NC}"
    exit 1
fi

# Carregar variáveis de ambiente
source .env

# Verificar Docker
echo -e "${BLUE}📦 Verificando Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker não está instalado!${NC}"
    echo -e "${YELLOW}Instale o Docker: https://docs.docker.com/get-docker/${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose não está instalado!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Docker OK${NC}"

# Criar diretórios necessários
echo -e "${BLUE}📁 Criando diretórios...${NC}"
mkdir -p instance static/uploads logs
touch logs/crm.log
echo -e "${GREEN}✅ Diretórios criados${NC}"

# Parar containers antigos (se existirem)
echo -e "${BLUE}🛑 Parando containers antigos...${NC}"
docker-compose down 2>/dev/null || true

# Baixar imagens mais recentes
echo -e "${BLUE}📥 Baixando imagens Docker...${NC}"
docker-compose pull

# Build da imagem
echo -e "${BLUE}🔨 Buildando imagem Docker...${NC}"
docker-compose build

# Rodar migrações do banco de dados
echo -e "${BLUE}🗄️ Rodando migrações do banco de dados...${NC}"
docker-compose run --rm web python -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✅ Banco de dados inicializado com sucesso!')
"

# Verificar se admin existe
echo -e "${BLUE}👤 Verificando usuário admin...${NC}"
docker-compose run --rm web python -c "
from app import app, db
from models import User
with app.app_context():
    admin = User.query.filter_by(email='${ADMIN_EMAIL:-admin@crm.com}').first()
    if not admin:
        admin = User(
            name='Administrador',
            email='${ADMIN_EMAIL:-admin@crm.com}',
            role='admin'
        )
        admin.set_password('${ADMIN_PASSWORD:-admin123}')
        db.session.add(admin)
        db.session.commit()
        print('✅ Usuário admin criado com sucesso!')
    else:
        print('✅ Usuário admin já existe!')
"

# Subir os containers
echo -e "${BLUE}▶️ Subindo containers...${NC}"
docker-compose up -d

# Aguardar sistema ficar saudável
echo -e "${BLUE}⏳ Aguardando sistema ficar saudável...${NC}"
sleep 10

# Verificar healthcheck
echo -e "${BLUE}🏥 Verificando healthcheck...${NC}"
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f http://localhost:5000/health &> /dev/null; then
        echo -e "${GREEN}✅ Sistema saudável!${NC}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT+1))
    echo -e "${YELLOW}⏳ Aguardando... ($RETRY_COUNT/$MAX_RETRIES)${NC}"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "${RED}⚠️ Healthcheck falhou. Verifique os logs: docker-compose logs web${NC}"
fi

# Mostrar status
echo -e "${BLUE}📊 Status dos containers:${NC}"
docker-compose ps

# Mostrar logs recentes
echo -e "${BLUE}📝 Últimos logs:${NC}"
docker-compose logs --tail=20 web

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                                                               ║"
echo "║     ✅ DEPLOY CONCLUÍDO COM SUCESSO!                          ║"
echo "║                                                               ║"
echo "║     🌐 Acesse: http://localhost:5000                         ║"
echo "║                                                               ║"
echo "║     📧 Email: ${ADMIN_EMAIL:-admin@crm.com}                   ║"
echo "║     🔑 Senha: ${ADMIN_PASSWORD:-admin123}                     ║"
echo "║                                                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Dicas
echo -e "${YELLOW}📌 Dicas úteis:${NC}"
echo -e "   Ver logs:        ${BLUE}docker-compose logs -f web${NC}"
echo -e "   Parar sistema:   ${BLUE}docker-compose down${NC}"
echo -e "   Reiniciar:       ${BLUE}docker-compose restart${NC}"
echo -e "   Acessar shell:   ${BLUE}docker-compose exec web bash${NC}"