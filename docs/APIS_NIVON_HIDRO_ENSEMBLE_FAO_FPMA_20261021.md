# NIVON — novos conectores públicos de hidrologia, previsão e preços (21/10/2026)

## Escopo implementado

Foram reaproveitadas **duas fontes já existentes** no Catálogo Mestre: `OPEN_METEO` e `FAO`. Criados **4 datasets, 4 rotas e 2 módulos Python**, sem duplicar fontes, sem credenciais, sem paid tier, sem cron e sem persistência:

| Dataset | API | Papel |
| --- | --- | --- |
| OPEN_METEO_GLOFAS_VAZAO | https://flood-api.open-meteo.com/v1/flood | Vazão **modelada** GloFAS v4, m³/s/dia a ~5 km, sem confundir com cota/vazão observada da ANA, nem com navegabilidade |
| OPEN_METEO_ENSEMBLE_PRECIP_MEMBROS | https://ensemble-api.open-meteo.com/v1/ensemble | Previsão probabilística de precipitação por **membro** do ensemble; modelos podem ter 31/51 membros e necessidade de calibração |
| FAO_FPMA_SERIES_CATALOGO | https://fpma.fao.org/giews/v4/global/price_module/api/v1/FpmaSerie/ | Metadados de séries agrícolas por país, commodity, moeda e unidade; UUID de série canônico |
| FAO_FPMA_PRECOS_SERIES | https://fpma.fao.org/giews/v4/global/price_module/api/v1/FpmaSeriePrice/ | Preços históricos por UUID e periodicidade com moeda original, preços ajustados/convertidos opcionais. Para uso produtivo, associar moeda/unidade da série e licenças |

A FAO FPMA complementa CEPEA, IMEA e preços EUA/USDA AMS, mas não os substitui. Os precios são de mercados/reporters distintos. Nenhum UUID é inventado ou hardcoded no sistema.

## Segurança do conector

- HTTPS com allowlist exata de hosts e caminhos, sem redirect, com MIME JSON, timeout, limite de payload (800 kB–1.5MB), SHA256 e coleta UTC.
- `executar=True` explícito em cada consulta; nenhuma execução remota pelo ato de importar o módulo.
- Vazão modelada e membros ensemble têm estado `PROJETADO_MODELO`, não `OBSERVADO`. Campos de data de publicação inexistentes permanecem `null`, sem *look-ahead*.
- FAO FPMA GET paginado: só uma página por consulta e links `next` não são seguidos; URLs derivadas de conteúdo retornado nunca são abertas. `uuid` validado pela biblioteca de UUID.
- Nenhuma informação de usuário, chave, Fazenda, contrato de frete ou cadastro é exposta.

## Módulos

- `src/nivon/open_meteo_hidro_ensemble.py`
- `src/nivon/fao_fpma_publica.py`
- `tests/test_hidro_ensemble_fao_fpma.py`
- `scripts/smoke_hidro_ensemble_fao.py`

### Diagnósticos pontuais

```bash
PYTHONPATH=src python scripts/smoke_hidro_ensemble_fao.py --fonte flood --executar
PYTHONPATH=src python scripts/smoke_hidro_ensemble_fao.py --fonte ensemble --executar
PYTHONPATH=src python scripts/smoke_hidro_ensemble_fao.py --fonte fao_catalogo --executar
# Usar somente UUID validado e periodicidade do catálogo real FAO:
PYTHONPATH=src python scripts/smoke_hidro_ensemble_fao.py --fonte fao_precos --uuid UUID_DO_CATALOGO --executar
```

**Gates restantes:** HTTP real individual, schema/vintage da FAO, relação entre ID de curso d'água GloFAS e estação ANA, probabilidade ensemble pós-calibração, licenças por operação (fonte, cache, exposição), banco canônico, backfill, checksum, backup e automação controlada. O fato de o código poder consultar a API **não** significa que os dados estejam gravados no BigQuery ou em qualquer banco do NIVON.

## Outras alternativas pesquisadas, não implementadas nesta PR

- **Eurostat Comext**: API oficial de comércio detalhado da UE com países terceiros, inclusive soja, milho e fertilizantes. Endpoint distinto `https://ec.europa.eu/eurostat/api/comext/dissemination`, exige filtros por dataset/período/país/HS; downloads completos não liberados pela interface API. Precisa selecionar um dataset comercial específico para evitar consulta massiva.
- **FAOSTAT fertilizantes por produto/nutriente e matrizes comerciais**: bases históricas e atualizadas em julho/2026, já fonte FAO no catálogo e prioridade posterior de contratos de extração com recortes regionais.
- **Open-Meteo ensemble mean/spread**: API separada, melhor para retenção histórica que todos os membros individuais (que expiram rápido); avaliar histórico de previsão sem *look-ahead* e licenças.

Referências:
- https://open-meteo.com/en/docs/flood-api
- https://open-meteo.com/en/docs/ensemble-api
- https://fpma-documentation.web.app/docs/api-docs/time-series/
- https://fpma-documentation.web.app/docs/api-docs/series-price/
- https://ec.europa.eu/eurostat/en/web/user-guides/data-browser/api-data-access/api-getting-started/comext-database
