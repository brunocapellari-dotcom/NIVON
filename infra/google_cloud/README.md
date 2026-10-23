# Módulo marítimo NIVON — entrada isolada na main

**Projeto:** `nivon-data` · **Dataset:** `nivon_raw` · **Região:** `southamerica-east1` · **Bucket:** `nivon-data-raw-2026`.

Estas são configurações de referência recuperadas do projeto; a existência,
as permissões e a localização devem ser verificadas pelo inventário GCP autenticado.
A implantação automática permanece desabilitada. Neon não é necessário.

Esta PR consolida o **núcleo operacional mínimo** dos coletores marítimos
separadamente da stack ampla AIS/UI do PR #141. Isso evita alterar componentes
centrais e antigas branches pendentes. O motor completo AIS/ETA permanece em
desenvolvimento no PR #141.

## Contratos

- `lineup_portos.py`: HTML oficial Suape/Imbituba/CDP, importação GPV autorizada,
  inferência AIS (sem afirmar toneladas realizadas).
- `maritimo_lote.py`: processamento das fontes em lote, execução isolada,
  controle de falhas e quarentena CDP.
- `portwatch_fluxos.py`: contagens AIS e **volume de trânsito estimado** pelo FMI.
- `maritimo_cloud_storage.py`: evidências imutáveis por hash SHA-256 no GCS.
- `maritimo_bigquery.py`: staging e MERGE idempotente, máximo inicial
  de 100 MB faturáveis por consulta.
- `maritimo_gcp_job.py`: ponto de entrada Cloud Run Job via service account/ADC.
- `maritimo_replay_gcp.py`: reconstrução a partir de manifesto GCS.
- `maritimo_portwatch_backfill.py`: histórico fragmentado, bloqueado por padrão.

As quatro tabelas e a view usam prefixo físico `maritimo_`
no dataset compartilhado `nivon_raw` para não colidir com outras fontes.
A migração é aditiva e requer `--aplicar`. Não há nova base nem bucket.

## Pipeline de liberação

1. Testes integrados + construção Docker real no GitHub (não faz deploy).
2. Inspeção da conta Google Cloud via
   `.github/workflows/nivon-gcp-conexao-readonly.yml` na main (WIF, somente leitura).
3. Migração DDL explícita e verificação de quatro tabelas e view (admin restrito).
4. Publicação em Artifact Registry e criação/atualização do Cloud Run Job
   com a identidade de coleta existente e variáveis compartilhadas.
5. Primeira execução real de Imbituba/PortWatch: GCS → BigQuery → consulta/replay,
   comparando histórico e evitando duplicatas.
6. Aprovação e ativação do Cloud Scheduler, jamais em paralelo a cron do GitHub.

**Não habilitar o job antes do E2E real**. A CI não tem acesso GCP de produção
em PRs. Documentação mais abrangente da frente marítima continua no PR #141.
