# Complemento consolidado — BCB SGS 11 para Google Cloud

Este complemento é sobreposto ao coletor Google Cloud da PR #147, reutilizando o parser BCB existente, o ledger SQLite, o Cloud Storage com RAW imutável e o carregador BigQuery. **Não é um novo pipeline de persistência.**

- `conectores_publicos_gcp.coletar_selic_diaria`: coleta SGS11 e preserva percentual diário, data de referência e falta de timestamp de publicação.
- `scripts/coletar_sgs_google_cloud.py`: coleta -> RAW/SQLite -> GCS -> JSONL -> BigQuery por MERGE idempotente, com direitos e execução explícitos.
- `.github/workflows/fontes-google-cloud-sgs.yml`: agenda desligada até WIF, projeto, bucket, dataset, orçamento e fonte SGS estarem aprovados.
- `tests/test_conectores_gcp_sgs.py`: E2E sem rede ou Google Cloud real.
- `ingestao_fontes_reais.py`: corrige validação HTTPS para permitir `@dataInicial` no *query* OData BCB, mas continua bloqueando usuário/senha na autoridade ou fragmento.

SICARM/CONAB deve usar **exclusivamente** o coletor canônico de `src/nivon/coletor_conab_sicarm_gcp.py` já atualizado na PR #147. A fonte contém cadastro sensível, permanece `QUARANTINED` e não deve ser promovida ao BigQuery canônico antes de validação de direitos, volume, layout e anonimização.

A tabela física BQ existente ainda precisa de desenho para particionamento por data_referencia, e tanto conexão GCP quanto dados reais e cron dependem dos gates de IAM/custo e de merge nas branches corretas. Nenhuma carga real foi executada por este complemento.
