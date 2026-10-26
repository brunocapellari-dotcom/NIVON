# NIVON MVP: imagem privada sem dependências externas da aplicação.
# Não executa coletas, não monta credenciais, não implanta Cloud Run.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/nivon/src \
    PORT=8080 \
    NIVON_BIND=0.0.0.0

WORKDIR /opt/nivon

COPY src ./src
COPY config ./config

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home nivon
USER 10001

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).close()"

# Falha até que NIVON_PRIVATE_DEPLOY_APPROVED=true seja definido
# em ambiente privado/IAM. Nunca ativar --allow-unauthenticated.
CMD ["python", "-m", "nivon.mvp_server"]
