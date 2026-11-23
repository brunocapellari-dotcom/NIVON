# Backfill e atualização incremental por pasta — ANTT MDF-e

A ferramenta `scripts/ingest_antt_mdfe_lotes.py` importa arquivos CSV agregados previamente obtidos da ANTT e mantém os snapshots por recorte no SQLite. **Não baixa o painel nem acessa API de Power BI.**

## Estrutura de pasta

```text
entrada-antt/
  manifesto.json
  mt_soja_2026-08.csv
  mt_soja_2026-09.csv
```

Exemplo de `manifesto.json`:

```json
{
  "lotes": [
    {"arquivo": "mt_soja_2026-08.csv", "recorte": "mt_soja_agosto_2026", "nivel": "RGI"},
    {"arquivo": "mt_soja_2026-09.csv", "recorte": "mt_soja_setembro_2026", "nivel": "RGI"}
  ]
}
```

Execução:

```bash
PYTHONPATH=src python scripts/ingest_antt_mdfe_lotes.py \
  --pasta /dados/entrada-antt --db /dados/nivon.sqlite
```

O lote de cada recorte é validado **antes de executar qualquer gravação**; os arquivos de todos os recortes são previamente checados. O código grava cada recorte em transação independente: falha excepcional de disco/conexão posterior poderá deixar alguns recortes atualizados e outros pendentes, passíveis de reexecução idempotente. A importação por pasta pode ser chamada periodicamente depois de um exportador **oficial e autorizado** depositar os CSVs.

A série só pode ser classificada como efetivamente observada após homologação externa de proveniência, nível, universo do recorte e datas de referência. Dados de teste são sintéticos.
