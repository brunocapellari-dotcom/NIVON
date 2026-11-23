# NIVON — Uma única ativação das tabelas e primeira coleta Google Cloud

Atualização de 25/10/2026.

## Evidência real mais recente

A última inspeção na `main` registrou autenticação WIF com `nivon-data` e consultas de metadados de `nivon_raw` e `nivon-data-raw-2026`. Não há confirmação de que `nivon_observacoes` e `agro_publicacoes_staging` tenham sido criadas. O workflow agrícola automático de 24/10 foi ignorado por gates. Coletores CEPEA/IMEA/CONAB executaram separadamente com saída para Neon, **não** equivale à alimentação BigQuery.

## Execução única, sem Cloud Shell

Workflow existente, agora ampliado:
`.github/workflows/ativar-tabelas-nivon-gcp.yml`

No GitHub: **Actions → NIVON - Ativar dois destinos BigQuery para coletores → Run workflow**.

Campos:
- `aplicar=false`, `primeira_fonte=NENHUMA`: ler os dois destinos. Se estiverem ausentes, o job reprova com evidência; não escreve.
- `aplicar=true`, `primeira_fonte=NENHUMA`: verificar e criar apenas as tabelas ausentes, com contrato, partições e clustering.
- `aplicar=true`, selecionar **uma** dentre `BCB_SGS11`, `IMEA`, `CONAB`, `CEPEA_SOJA`, `CEPEA_MILHO`: primeiro validar/criar tabelas; depois fazer uma coleta real até o GCS e BigQuery usando somente pipelines existentes.

O workflow exige quatro gates de esquema/IAM/orçamento já preexistentes antes de qualquer criação. Para uma primeira carga, exige também `NIVON_RAW_ARCHIVE_APPROVED` e um gate específico da fonte:

| Fonte | Pré-requisitos adicionais | Destino |
|---|---|---|
| SGS11 | `NIVON_SGS11_GCP_WRITE_APPROVED` e `NIVON_SGS11_EVIDENCIA_USO` | `nivon_observacoes`; arquivo/manifesto RAW no GCS e readback GCS/BQ |
| IMEA | `NIVON_IMEA_FONTE_AUTORIZADA` e `NIVON_AGRO_STAGING_BIGQUERY_APPROVED` | `agro_publicacoes_staging` **QUARANTINED**; nunca preços físicos publicados automaticamente |
| CONAB | `NIVON_CONAB_FONTE_AUTORIZADA` e `NIVON_AGRO_STAGING_BIGQUERY_APPROVED` | `agro_publicacoes_staging` **QUARANTINED** |
| CEPEA soja/milho | `NIVON_CEPEA_FONTE_AUTORIZADA` e `NIVON_CEPEA_HOMOLOGACAO_APROVADA` | `nivon_observacoes` somente após conferência de data e direitos |

O fluxo só executa em `main`, com identidade federada GCP, ambiente `nivon-gcp-producao` e sem salvar chave JSON. A opção `primeira_fonte` fica **NENHUMA** por padrão. Ativar esse campo não liga agendamentos recorrentes ou aprova custos automaticamente. Um fail no meio preserva objetos/DDL criados, e uma nova execução retoma idempotentemente; não há `DROP` ou apagamento de dados.

## Testes

`tests/test_workflow_ativacao_carga_integrada.py` verifica especificamente cada caminho, seus gates e a ordem bootstrap → coletor. Também executar:
```bash
python -m unittest discover -s tests -p 'test_bootstrap_tabelas_gcp.py' -v
python -m unittest discover -s tests -p 'test_sgs11_gcp.py' -v
```

## Critério real de conclusão

Não confundir CI sintética com a operação GCP. Conclusão exige evidência dos recursos criados, SHA RAW no Storage, MERGE do primeiro registro, leitura posterior das mesmas identidades no BigQuery e replay sem duplicidade. Para IMEA/CONAB, verificação do histórico `QUARANTINED` sem promoção de dados cuja referência seja desconhecida. O sistema deve registrar também custo, IAM e tamanho dos arquivos.

**Este patch é apenas a orquestração da ativação, não a execução no Google Cloud.**
