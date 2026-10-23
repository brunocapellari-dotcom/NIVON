# NIVON marítimo — implantação no Google Cloud

## Arquitetura canônica

Google Cloud é a infraestrutura operacional: Cloud Run Jobs para coleta,
Cloud Storage para histórico de evidências imutáveis por SHA-256, BigQuery
como fonte analítica única, Cloud Scheduler para execuções agendadas.

O GitHub Actions executa apenas QA/inspeções públicas read-only.
A persistência Neon foi desativada do workflow; tabelas antigas não são
apagadas. Implementação em PR não equivale a implantação no Google Cloud.

## Recursos já implementados no código

- src/nivon/maritimo_lote.py: lote de coletores HTML com quarentena CDP.
- src/nivon/maritimo_cloud_storage.py: evidências por hash no bucket GCS.
- src/nivon/maritimo_bigquery.py: estágio SQLite local e MERGE BigQuery.
- src/nivon/maritimo_gcp_job.py: entrada para Cloud Run Job, usa ADC.
- infra/google_cloud/maritimo_bigquery.sql: DDL versionado, particionamento,
  clusterização e visão de frescor das fontes.
- infra/google_cloud/Dockerfile.maritimo e cloudbuild.maritimo.yaml: imagem.


## Configuração confirmada do projeto NIVON (sem credenciais)

Projeto: nivon-data; região: southamerica-east1 (São Paulo);
BigQuery: dataset já criado nivon_raw; bucket GCS: nivon-data-raw-2026;
identidade dos coletores: nivon-coletor-de-dados@nivon-data.iam.gserviceaccount.com.

Essas identificações vieram da configuração anterior da conta. **Não foram
revalidadas por acesso autenticado nesta execução.** Não criar outro bucket
nem outro projeto. Adotar NIVON_BQ_PROJECT, NIVON_BQ_DATASET e
NIVON_GCS_BUCKET como variáveis compartilhadas com o PR #147 de fontes GCP.
No primeiro go-live, tabelas marítimas usam o dataset já existente nivon_raw;
se um dataset analítico dedicado for criado depois, migrar por processo
versionado, sem criar por suposição.

O MERGE BigQuery tem agora limite padrão de 100.000.000 bytes faturáveis
por query, mesmo no replay/backfill. Um lote que exceder esse teto deve
falhar com evidência preservada no GCS; custos zero NÃO são garantidos.
O limite deve ser ajustado somente com medição de jobs reais.

## Pré-requisitos para executar no Google Cloud real

1. Descobrir qual PROJECT_ID, REGION, bucket e repositório Artifact Registry
   o NIVON já utiliza. Evitar duplicação de projetos/recursos.
2. Confirmar billing, quotas, permissões e localização do BigQuery antes de
   criar dataset nivon_maritimo. Aplique o DDL (substituindo placeholders
   exatos) com um papel administrativo uma única vez.
3. Identidade de Cloud Run dedicada: roles/bigquery.jobUser no projeto,
   roles/bigquery.dataEditor somente no dataset, permissão para criar e
   ler metadados de objetos GCS no bucket selecionado; não usar chaves JSON.
4. Cloud Scheduler com identidade independente autorizada para run.jobs.run
   no job específico, autenticação OAuth para a API Cloud Run Jobs.
5. Validar fontes e direitos operacionais. Santarém/Vila do Conde sempre em
   quarentena até reconciliação; Amaggi não é embarque confirmado via AIS.
6. Ativar NIVON_MARITIMO_COLETA_HABILITADA=true somente após os testes
   E2E reais de GCS -> BQ e observabilidade/contagem/custos.

## Exemplo: build e job (NÃO executado nesta sessão)

Substituir as variáveis pelas configurações reais já existentes:

    PROJECT_ID='projeto-real'
    REGION='southamerica-east1'
    DATASET_ID='nivon_maritimo'
    BUCKET='bucket-privado-existente'
    REPO='artifact-registry-existente'
    JOB_SA='service-account-job'
    SCHEDULER_SA='service-account-scheduler'
    IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/nivon-maritimo:20261023"

    gcloud builds submit --project="$PROJECT_ID" \
      --config=infra/google_cloud/cloudbuild.maritimo.yaml \
      --substitutions="_IMAGE_URI=$IMAGE" .

    gcloud run jobs deploy nivon-maritimo \
      --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
      --service-account="$JOB_SA" --tasks=1 --parallelism=1 \
      --max-retries=0 --task-timeout=900s --memory=1Gi --cpu=1 \
      --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,NIVON_MARITIMO_DATASET=$DATASET_ID,NIVON_MARITIMO_BUCKET=$BUCKET,NIVON_MARITIMO_COLETA_HABILITADA=false,NIVON_PORTWATCH_COLETA_HABILITADA=false"

Aplicar o DDL com projeto e dataset confirmados antes do primeiro job.
O container não cria dataset e não ativa coleta automaticamente.

Depois de inspeção e autorização operacional, o Cloud Scheduler pode usar
HTTP POST para a API run.googleapis.com/v2/projects/PROJECT/locations/REGION/
jobs/nivon-maritimo:run, autenticada por OAuth do Scheduler (escopo cloud-platform),
no cron 12 */6 * * * (UTC). Configurar na região do projeto e confirmar custos.
Não agendar também pelo GitHub Actions.

## Limitações e validação

- Testes de GCS/BQ em CI são simulados, não comprovam credenciais ou deploy.
- Imbituba e PortWatch foram lidos em testes read-only na rodada anterior.
- Captura HTML GCS hoje é o HTML decodificado e reencodado UTF-8, não a
  sequência literal de bytes do HTTP upstream.
- MERGE por chaves naturais impede duplicata de registros; erros parciais
  entre tabelas podem ser recuperados por replay das evidências GCS.
- Partição de escalas por data_referencia (nula quando fonte não fornece);
  nunca substituir implicitamente pelo timestamp de coleta.
- AIS Amaggi necessita geocerca validada e cobertura real; não inventar carga.
- São necessárias checagens de limites BigQuery, custos, retenção GCS,
  monitoramento, freshness, IAM, rollback e reconciliador de revisões.
- No código, o modo GCP exige explicitamente bucket/dataset/projeto,
  variáveis e service account via ADC; não há segredo Neon em uso.

## Portas de entrada reais pendentes

Nao há plugin GCP com escrita habilitada nesta conversa. Para go-live,
um operador autenticado precisa configurar esses recursos na conta Google
Cloud verdadeira; não pedir senha, chave de service account ou credencial
privilegiada em mensagens. Sem isso, não afirmar coleta em produção.


## Recuperação de falhas na gravação BigQuery

A execução Cloud Run arquiva snapshots e páginas PortWatch por SHA-256
e grava um manifesto de coleta imutável ANTES da etapa BigQuery.
A rotina nivon.maritimo_replay_gcp reconstrói o staging a partir dos
objetos GCS, verifica os hashes e aplica MERGE idempotente sem consultar
novamente os portais.

Acionamento de exemplo (não executado no Google Cloud real):

    python -m nivon.maritimo_replay_gcp --bucket=BUCKET_REAL \
       --manifesto=gs://BUCKET_REAL/nivon/maritimo/raw/_manifestos/RUN_UUID.json \
       --projeto=PROJETO_REAL --dataset=nivon_maritimo --dry-run

Após validação, remover o parâmetro dry-run para sincronizar.
Se houver falha antes de arquivar o manifesto, os snapshots já escritos
no GCS permanecem, mas a reconstrução automática do lote não é garantida.

## Inspeção de infraestrutura Google Cloud (somente leitura)

No ambiente gcloud/bq já autenticado, executar:

    python infra/google_cloud/preflight_maritimo.py --projeto=PROJETO_REAL \
      --regiao=REGIAO_REAL --bucket=BUCKET_REAL --dataset=nivon_maritimo

A ferramenta consulta existência e estado do projeto, APIs necessárias,
BigQuery dataset, bucket, Cloud Run Job e Cloud Scheduler. Não faz mutações,
não imprime credenciais nem confunde falta de permissão com recurso ausente.
É uma inspeção: NÃO ativa serviços.

## Retrocarga histórica PortWatch (limitada)

Existe o módulo nivon.maritimo_portwatch_backfill, separado da coleta
rotineira. Ele fragmenta períodos em janelas de até 31 dias, permitindo
no máximo quatro janelas por execução. Cada janela arquiva evidências,
gera manifesto GCS e sincroniza por MERGE BigQuery, preservando
classificação de carga estimada (não oficialmente realizada).

Acionamento de exemplo somente após GCP IAM/recursos homologados:

    NIVON_PORTWATCH_BACKFILL_HABILITADO=true \
       python -m nivon.maritimo_portwatch_backfill \
       --inicio=2019-01-01 --fim=2019-01-31 \
       --projeto=PROJETO_REAL --bucket=BUCKET_REAL

Não há evidência de retrocarga real no Google Cloud ainda. Limites,
cotas, permissões, custos e proveniência deverão ser verificados
antes da execução de intervalos maiores.

## Status de homologação

Testes automatizados validaram esses componentes sem credenciais por
simulações; faltam project ID, bucket e dataset reais e direitos
GCP de execução para testar Cloud Run -> GCS -> BigQuery na conta NIVON.
Não confundir código no PR #141 com deploy/producao efetivamente implantada.
