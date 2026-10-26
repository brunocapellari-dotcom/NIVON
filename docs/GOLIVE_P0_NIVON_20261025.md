# NIVON - Caminho critico de go-live privado (25/10/2026)

EVIDENCIAS REAIS CONSULTADAS:
- GitHub Actions 40257978213: painel interno com duas revisoes privadas no GCS, readback SHA valido.
- GitHub Actions 40257778476: leitura ANTT/SIADE BigQuery comprovada, deploy bloqueado, runtime SA e Artifact Registry ausentes.
- GitHub Actions 40257929205: bucket e dataset na regiao southamerica-east1; tabela agro_fonte_stage AUSENTE, fora do caminho critico da view ferroviaria.
- GitHub Actions 40258654913: CI do terminal web em main verde; isso NAO e deploy Cloud Run.

ENTREGA: inventario GCP read-only por metadados que distingue a view
vw_antt_ferrovia_od_atual (obrigatoria no piloto ANTT) da tabela
agro_fonte_stage (modulo de ingestao mais amplo). Bucket exige Public
Access Prevention enforced. Falta da view ou bucket desprotegido bloqueia
piloto; stage ausente e reportado separadamente.

Workflow de publicacao interna: nao faz GCS write em push; exige
NIVON_PAINEL_INTERNO_WRITE_APPROVED=true e
NIVON_GCP_COST_REVIEWED=true e despacho manual ou agenda explicita.
Workflow de piloto BQ real: consulta no main so com workflow_dispatch,
NIVON_TERMINAL_READ_APPROVED=true e NIVON_GCP_COST_REVIEWED=true.
CI nova roda offline sem credencial de GCP.

OPERACAO:
1. Revisar/mesclar PR P0 na main.
2. Configurar aprovacao explicita de custo/consulta e confirmar
   metadata com scripts/verificar_golive_gcp_readonly.py --executar.
3. Administrador comprovar ou provisionar repositorio Docker existente
   e runtime service account read-only (sem permissao Owner).
4. Homologar limites GCP e acionar o workflow manual de terminal privado.
5. Verificar autenticacao IAM, /healthz, /api/v1/ferrovia e
   ausencia de URL publica. Cloud Run NAO foi implantado nesta PR.

Nao aguardar CEPEA, IMEA, CONAB, maritime ETA ou WhatsApp para pilotar
ferrovia privada real. Nenhum deploy, gasto, cron, acesso IAM, criacao
de recurso, chamada HTTP de dados ou envio nesta PR.
