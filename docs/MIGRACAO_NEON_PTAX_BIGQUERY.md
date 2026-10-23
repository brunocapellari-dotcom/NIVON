# NIVON — Plano de cópia auditável PTAX Neon → BigQuery

**Estado: preparação sem migração real.** Não há dataset GCP provisionado por esta PR.

## Evidência da origem (consulta read-only Neon, 21/10/2026)

| Moeda | Linhas | Primeira referência | Última referência |
|---|---:|---|---|
| EUR | 663 | 2020-01-02 | 2026-10-21 |
| USD | 133 | 2020-01-02 | 2026-10-21 |

**Contagem instantânea, não cobertura completa:** o backfill segue em operação. Os números podem mudar.

## Modelo preservado

Origem: public.nivon_ptax_quotes (Neon, PR #58). Destino proposto: nivon_core.ptax_quotes; template em database/bigquery/nivon_ptax_schema.sql.

- Preservar moeda, data, quote_time_original, bulletin_type, buy_brl, sell_brl, unit, source, license, published_at, first_collected_at, last_verified_at, observation_kind e id de origem.
- Nunca converter published_at desconhecido em data de coleta, nem atribuir fuso ao horário original.
- quote_id: SHA-256 da chave moeda/data/horário/boletim/compra/venda, com decimais normalizados. Revisions de preço geram quote_id distintos; valores monetários são representados sem float.
- record_sha256 identifica representação normalizada da linha Neon exportada; não é checksum do payload original do BCB. origem_sha256 fica NULL, até o RAW ser verificado.
- quality_status=NEON_EXPORT_UNVERIFIED, até reconciliação posterior. source_neon_row_id serve apenas para auditoria de origem.
- A saída JSONL representa NUMERIC como strings de exatidão decimal. Verificar carregamento no BigQuery primeiro com fixtures sintéticas.

## Uso local, sem rede

Após obter export JSONL por canal autorizado e PRIVADO, fora do GitHub público, usar:

    python3 scripts/ptax_neon_to_bigquery_jsonl.py --input /tmp/ptax-neon-private.jsonl --output /tmp/ptax-bq-private.jsonl

O arquivo local precisa ter cada linha em JSON compatível com SELECT * FROM public.nivon_ptax_quotes. O conversor exige saída nova e privada (0600), fora do repositório; falhas apagam a saída parcial. O relatório público de stdout contém só total, contagem por moeda, datas extremas e SHA-256 do arquivo exportado. Não compartilhar DATABASE_URL, credenciais ou cotações em issues/PRs.

## Reconciliação registro a registro (somente leitura, sem nuvem)

Arquivo `scripts/reconcile_ptax_neon_bigquery.py` compara uma exportação JSONL **bruta da tabela Neon** com uma exportação JSONL da tabela BigQuery, ambas de acesso privado, fora do GitHub. Nenhum SQL/HTTP/API é executado pelo comparador. Para executar:

```sh
python3 scripts/reconcile_ptax_neon_bigquery.py \
  --source-neon /tmp/ptax-neon-private.jsonl \
  --target-bigquery /tmp/ptax-bigquery-private.jsonl
```

Contrato: a exportação Neon precisa conter todos os campos de `public.nivon_ptax_quotes`. A exportação BigQuery precisa conter **todas** as colunas descritas em `database/bigquery/nivon_ptax_schema.sql` (sem extras) com tipos compatíveis. O JSONL BigQuery aceita campos `NUMERIC` como strings/JSON decimal; campos `TIMESTAMP` exigem offset, `Z` ou sufixo explícito `UTC`. Campo `source_neon_row_id` aceita inteiro ou string inteira positiva.

O reconciliador analisa: contagens por moeda, chaves/cotações ausentes, registros inesperados, versões com metadados divergentes, duplicações, `quote_id`, `record_sha256`, `vintage_id`, preço exato, compra/venda, boletim, horário de origem, datas, natureza, atributos de licença. Para adulteração ou contrato inconsistente, **bloqueia a verificação** sem publicar nenhuma cotação ou caminho privado.

Saída JSON: apenas números agregados, SHA-256 dos **arquivos completos**, status de conciliação e decisões que permanecem bloqueadas. Nenhum preço, amostra de registro, URL interna ou credencial aparece no relatório. Códigos de saída:

- `0`: os **dois snapshots locais não vazios** são consistentes. Isso **não** comprova carga em GCP, backup/restore, completude temporal ou autorização de migração.
- `3`: arquivo ausente, malformado, dados de destino adulterados ou violação do contrato.
- `4`: snapshots válidos, mas com registros ausentes, extras, alterados, duplicados ou ambos vazios.

Há limite de 500.000 linhas por arquivo; separar períodos maiores em janelas auditáveis sem descartar nenhuma. Dois arquivos vazios nunca são considerados êxito.

**Snapshot em movimento:** o Neon mantém o backfill e `last_verified_at` pode mudar. Duas extrações em momentos diferentes podem produzir divergência legítima. Exportar a origem sob snapshot transacional consistente e registrar início/fim, contagens, hashes, cobertura e corte. No BigQuery, registrar versão do load e job id, manter a mesma janela, reexportar, verificar diferenças e repetir a reconciliação após o backfill. **Não aceitar diferença "quase zero", deduplicação silenciosa ou truncamento de arquivos como aprovação.** O BigQuery não garante unicidade de chaves automaticamente.

O script nunca muda `quality_status`, nunca gera SQL `MERGE`, nunca altera a programação Neon e **sempre** retorna `cutover_approved:false`, mesmo no resultado consistente. Autorização de mudança requer restore testado, auditoria de direitos e aprovação independente dos dados.

## Gates

1. Verificar resultado sanitizado da auditoria do projeto nivon-data: billing, IAM e APIs. O Cloud Shell não devolve essa saída automaticamente à conversa.
2. Confirmar custo permitido, direito de armazenamento por fonte e política de privacidade; não vincular billing, criar bucket ou rodar jobs por suposição.
3. Fazer backup privado restaurável no Neon e validar contagem e integridade. Recontar origem imediatamente antes e depois da cópia, pois o backfill continua.
4. Homologar schema e NUMERIC em staging com dados sintéticos; depois validar SHA, versão, horários, preços e revisões reais sem usar GitHub como transporte.
5. Verificar idempotência, reprocessamento incremental e consultas por partição/vintage com diferença zero. Manter Neon operacional até cutoff reversível com monitoramento.
6. Nenhum Neon, job, trigger ou dado real será desligado/excluído por estes arquivos.

## Testes automatizados

    python3 -m unittest discover -s tests -p 'test_gcp_ptax_migration_offline.py' -v

Esses testes usam apenas fixtures sintéticas e não provam execução real em GCP.
