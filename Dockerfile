# ============================================================================
# Dockerfile - CRM Conversacional
# ============================================================================
# Build: docker build -t crm-conversacional .
# Run:   docker run -p 5000:5000 crm-conversacional
# ============================================================================

FROM python:3.11-slim-bookworm AS builder

# Instalar dependências do sistema para compilar algumas libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primeiro (melhor aproveitamento do cache)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============================================================================
# Estágio final (produção)
# ============================================================================
FROM python:3.11-slim-bookworm

# Instalar dependências de runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar Python packages do estágio builder
COPY --from=builder /root/.local /root/.local

# Copiar código fonte
COPY . .

# Criar diretórios necessários
RUN mkdir -p instance static/uploads logs && \
    chmod 755 instance static/uploads logs

# Criar usuário não-root para segurança
RUN useradd -m -u 1000 -s /bin/bash crmuser && \
    chown -R crmuser:crmuser /app

USER crmuser

# Garantir que local bin está no PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Expor porta do Flask
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Comando de entrada (usando gunicorn em produção)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--timeout", "120", "app:app"]