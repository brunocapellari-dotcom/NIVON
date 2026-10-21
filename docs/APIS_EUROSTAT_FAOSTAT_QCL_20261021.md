# NIVON — Integração Eurostat e FAOSTAT QCL, 21/10/2026

## Novas consultas gratuitas

**Eurostat**: API JSON-stat `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tag00100`, conjunto derivado do `apro_cpsh1`, área de culturas oleaginosas (colza, girassol, soja) em **milhares de hectares** por país europeu e ano. API gratuita, sem token, versão mais recente substitui versões anteriores; `updated` da base não comprova quando cada observação foi publicada. O filtro impõe um país, um ano, no máximo 200 posições JSON-stat, validando `strucpro=AR_THS_HA`, status e flags de qualidade. NÃO confundir área com produção física ou preço.

**FAOSTAT**: dataset canônico `FAO_FAOSTAT_LONG_RUN` já existia no NIVON. Foi implementado um cliente limitado a QCL `https://fenixservices.fao.org/faostat/api/v1/en/data/QCL` e países/culturas aprovados: Brasil/EUA/Argentina, soja/milho/trigo e elemento 5510 (quantidade produzida). Retorna código de país, cultura, ano, unidade física e flags; nunca assume produção brasileira de safra 2026 ou dados observados no talhão. Apoia histórico internacional, comparação de oferta, produtividade e exportação.

## Código e segurança

- `src/nivon/eurostat_faostat_agro.py`: planejador de endpoints, GET HTTPS host/path allowlist, sem redirects, timeout 20s, JSON limitado a 1,5 MB, JSON-stat decodificado com índice de dimensões, datas, flags, validações e SHA256.
- `tests/test_eurostat_faostat_agro.py`: transporte sintético sem rede e testes de recusa de injeção, país, cultura, status, unidade e períodos inconsistentes.
- `scripts/smoke_eurostat_faostat.py`: diagnóstico pontual em runner autorizado. Sem flag `--executar`, nenhuma solicitação é enviada.

Comandos de smoke:

```bash
PYTHONPATH=src python scripts/smoke_eurostat_faostat.py --fonte eurostat --executar
PYTHONPATH=src python scripts/smoke_eurostat_faostat.py --fonte faostat --executar
```

## Gates

A existência de acesso público não comprova licença para republicação de séries ou operação contínua. Os registros de catálogo permanecem com `enabled=false`, `runtime_enabled=false`, `scheduled_enabled=false`, `collection_authorized=false`. Não houve cron, banco novo, pagamento ou armazenamento automático.

Verificar HTTP real, comparar código/cultura com o dicionário FAO atual, registrar data de emissão revisada da Eurostat, manter snapshots por data_coleta para evitar look-ahead e persistir somente após validação de checksum/deduplicação/backup.

Fontes oficiais:
- https://ec.europa.eu/eurostat/en/web/user-guides/data-browser/api-data-access/api-introduction
- https://ec.europa.eu/eurostat/databrowser/view/tag00100/default/table
- https://www.fao.org/faostat/en/#developer-portal
- https://fenixservices.fao.org/faostat/api/v1/en/data/QCL
