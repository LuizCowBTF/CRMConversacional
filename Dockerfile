FROM python:3.11-slim

WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copiar requirements primeiro (melhor para cache)
COPY requirements.txt .

# Instalar dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto da aplicação
COPY . .

# Criar diretórios necessários
RUN mkdir -p instance static/uploads logs

# Expor porta
EXPOSE 5000

# Comando para rodar
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
