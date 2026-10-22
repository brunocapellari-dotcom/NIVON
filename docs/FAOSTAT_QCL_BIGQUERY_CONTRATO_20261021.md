# NIVON — Ponte SQLite → BigQuery sem execução cloud (21/10/2026)

## Contexto verificado
A infraestrutura planejada do NIVON tem um projeto Google Cloud `nivon-data` criado, mas **não há confirmação operacional de dataset, IAM, faturamento, região, acesso ao BigQuery nem custo verificado**. A árvore GitHub não continha migrações de banco que comprovassem esse setup. Por isso este pacote é inteiramente offline e não cria recursos.

## Construído
- `src/nivon/faostat_qcl_bigquery_export.py`: exporta observações QCL já filtradas e persistidas em SQLite local para NDJSON/JSONL UTF-8, em lote limitado, atomicamente e com SHA256, sem contato com APIs Google.
- `sql/bigquery/001_faostat_qcl_snapshots.sql`: contrato de tabela temporal particionada por `data_referencia` e com clustering em país/cultura/elemento/SHA. **Template não executado**, com placeholders para projeto e dataset que não podem ser interpolados sem confirmação de recursos/permissões e custos.
- `tests/test_faostat_qcl_bigquery_export.py`: confere data_referencia anual 31/12, campo data_publicacao nulo, consistência de hash, lote vazio/corrompido, revisões por SHA, export determinística e ausência de escrita cloud.

## Modelagem
- Fonte: `FAO`, domínio `QCL`, dataset `FAO_FAOSTAT_LONG_RUN`.
- `valor` registrado como decimal/string JSONL para BigQuery NUMERIC, sem perda silenciosa de precisão por float.
- `data_referencia` mapeia ANO (e.g. 2023) para 2023-12-31 somente como **convenção técnica de particionamento**; ano agronômico/safra não é inferido.
- `competencia` guarda ano literal `2023`.
- `data_coleta` UTC, `data_publicacao` NULL até prova individual de publicação.
- `data_atualizacao_fonte` reflete metadado do lote FAO, não publicação do dado.
- `source_sha256` controla versões. BigQuery não aplica chave única; o futuro carregador deve usar MERGE atômico por dataset/país/cultura/elemento/ano/sha, preservando vintages.
- Não há autorização para despachar jobs Cloud Run, habilitar APIs pagas ou colocar datasets em produção.

## Gate de ativação futura
1. Verificar ID de dataset **real e existente**, localização e IAM do projeto Google Cloud `nivon-data`; nunca criar banco por pressuposição.
2. Confirmar orçamento/alertas/free tier e licenças de coleta/armazenamento antes de qualquer escrita.
3. Validar DDL, job de carga idempotente, logs, partições, backup/restauração, observações reais e query via camada Gateway, com dados brutos e linhagem.
4. Agendar apenas após validação de custos, qualidade e retomada de falhas.

O estágio SQLite já passou em execução FAOSTAT QCL real na prova https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698793414. O exportador BigQuery deste pacote é **código pronto para integração**, não prova de upload ou existência do BigQuery.
