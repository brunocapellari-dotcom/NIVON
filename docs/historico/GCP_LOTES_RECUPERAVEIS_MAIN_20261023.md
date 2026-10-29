# NIVON — Núcleo Google Cloud consolidado, lotes recuperáveis (23/10/2026)

## Resultado verificado em código e CI
Implementação baseada **diretamente na main**, sem recriar um segundo carregador BQ
ou um segundo arquivador RAW. É continuação seletiva da engenharia criada em
#147 → #163 → #171, mas **não** traz a árvore dessas PRs para main.

Componentes canônicos preservados:
- `ingestao_fontes_reais.py`: snapshots e observações históricas SQLite/JSONL;
- `arquivo_raw_gcs.py`: GCS RAW por hash, metadata e upload imutável;
- `carga_bigquery_fontes.py`: staging + MERGE de observações na tabela
  particionada por `data_referencia`;
- `verificacao_cloud_fontes.py`: consulta pós-carga a GCS e BigQuery.

Implementado no lote:
1. Filtro opcional `fonte_dataset` no arquivamento RAW, evitando enviar
   fontes vizinhas/quarentenas do mesmo ledger ao selecionar uma fonte.
2. `lote_cloud_recuperavel.py`: exige que cada linha JSONL exista no
   SQLite com snapshot `NORMALIZED`, valida fingerprint/identidade/referência
   e confronta o RAW **já armazenado no GCS**.
3. Guarda stage JSONL em `nivon/staging/v1/<SHA>.jsonl` e manifesto em
   `nivon/lotes/v1/<SHA>.json` **antes do BigQuery**. Ambos com SHA-256
   no objeto GCS, `if_generation_match=0` e checksum CRC32C.
4. Replay do manifesto após falha do BigQuery **sem SQLite/runner original**,
   validando origem/destino, hashes, contagem, snapshots RAW e stage.
5. Workflow recorrente atualizado e backfill histórico atualizado para usar
   o mesmo contrato. CLI e workflow manual para replay após o merge à main.

## Execução: fluxo automatizado existente
`.github/workflows/coleta-recorrente-fontes.yml`:
  preflight GCP → coleta/RAW SQLite → arquivo RAW GCS →
  manifesto + JSONL GCS → BigQuery MERGE → consulta de confirmação.

As fontes ainda não aprovadas para normalização não podem entrar no replay:
não se transforma `QUARANTINED` em `NORMALIZED`.

## Recuperação sem comandos no PC
Quando incorporado à main, usar GitHub Actions
**NIVON - Recuperar lote BigQuery a partir de GCS** → **Run workflow**
→ informar o SHA-256 do manifesto, que é devolvido pela etapa de
arquivamento do lote no log da execução original.

O workflow usa Workload Identity Federation (OIDC) e verifica
`NIVON_ZERO_COST_BQ_APPROVED`, `NIVON_RAW_ARCHIVE_APPROVED`,
`NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`,
`NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET`,
além de restringir a execução a `refs/heads/main`.
**Aprovação de custos em variables não garante gasto zero.**

O destino só pode ser o mesmo project/dataset que consta no manifesto.
A recuperação não coleta dados da internet nem altera o histórico RAW,
apenas repete o MERGE idempotente.

## CLI sem rede
```bash
python scripts/lote_cloud_recuperavel.py --fase replay \
  --manifesto-sha <sha64> \
  --projeto nivon-data --dataset <dataset_existente> \
  --bucket <bucket_privado_existente>
```

Sem `--executar` apenas valida o formato da solicitação.
A execução real requer variáveis de autorização e ADC/WIF.

## Testes integrados
```bash
python -m unittest discover -s tests -p 'test_lote_cloud_recuperavel.py' -v
python -m unittest discover -s tests -p 'test_backfill_cloud_stage.py' -v
```

Cenários: RAW de uma única fonte, quarentena simultânea, ausência do RAW,
manifesto e stage idempotentes, perda do banco SQLite original, replay,
destino divergente, adulteração de bytes e ordenação backfill→GCS→MERGE.

## Pendências reais
- Não há evidência neste lote de autenticação GCP, bucket, tabela,
  disponibilidade WIF ou gravação real em `nivon-data`. CI usa testes sintéticos.
- O workflow manual de recuperação só fica utilizável após merge na main,
  configuração WIF/ADC e gate da infraestrutura.
- O agendamento só deve ser ativado após autorização de coleta, auditoria
  da tabela existente, custos, retenção, leitura pós-gravação e rollback.
- Futura consolidação CEPEA/IMEA/CONAB: aproveitar **adaptadores**
  e normalizadores das PRs #147/#163 e dos coletores já presentes na main;
  não trazer os motores GCS/BQ antigos que redundam este núcleo.
- `main` não deve receber branches de 600+ commits sem reconciliação.

## Status
**Código e testes offline implementados. Deploy / coleta contínua / migração
real não executados nesta entrega.** O material não representa homologação
operacional, preço vigente ou autorização de redistribuição de terceiros.
