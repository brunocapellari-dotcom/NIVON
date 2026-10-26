# NIVON — Primeira interface operacional privada

Implementação WSGI + interface sem dependências externas para os recortes ANTT ferroviário e rodoviário 2025 que já possuem consultas BigQuery e reconciliação. Não cria dados ou APIs novos.

- Rodovia: somente TOP-16 anual de fluxos RGI, todos os produtos, não matriz MDF-e nacional.
- Ferrovia: TU por estação de origem nos 9 polos do estudo, sem comprovação de transbordos.
- Hidrovia: SEM microdados ANTAQ primários homologados na apresentação; a réplica terciária não compõe totais.
- O ano da informação é 2025. Data da consulta no sistema não significa atualização da origem.
- O backend consulta somente duas views limitadas, usando src/nivon/corredores_multimodais_2025.py, com limite de bytes por consulta já definido.
- GET /api/v1/painel só executa com NIVON_TERMINAL_READ_APPROVED=true. Essa flag NÃO é autenticação.
- A autenticação de produção deve estar no perímetro Cloud Run IAM, com serviço privado, --no-allow-unauthenticated e conta de serviço de LEITURA. Não habilitar o acesso público.
- O servidor local só escuta em 127.0.0.1. Dockerfile.terminal é preparação para deploy controlado, não ativa billing nem cria recurso.
- Sem autenticação IAM configurada e teste read-only real, NÃO declarar go-live público/privado em nuvem.

Teste local sem GCP: PYTHONPATH=src python -m unittest tests.test_terminal_ro -v
Servidor local: python -m nivon.terminal_ro --porta 8080 (html servido, API bloqueada sem flag)
Para teste real com Google ADC de leitura e custo aprovado: NIVON_TERMINAL_READ_APPROVED=true python -m nivon.terminal_ro --porta 8080
O endpoint /healthz mede processo, NÃO frescor das fontes ou saúde do BigQuery.

Portas de lançamento: PR #246 de auditoria, issue #263 de proteção da main/IAM/billing, CI verde, deploy privado e readback independente. Não usar valores da réplica hidroviária para inferir cargas realizadas.
