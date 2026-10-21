# NIVON — Rodada de novas bases gratuitas (21/10/2026)

## Estado verificável

- **3 fontes novas**: EARTH_SEARCH (STAC público Element84), ESA_WORLDCOVER e JRC_GSW (European Commission Joint Research Centre).
- **7 datasets novos**: STAC cenas, WorldCover 2021, JRC histórico de água, USDA AMS GTR frete multimodal, USDA AMS GTR basis e preços exportação, NOAA ENSO, WB Pink Sheet.
- **1 conector novo em Python**: `src/nivon/earth_search_stac.py` monta e executa uma única consulta HTTPS STAC GET com AOI máxima de 2° × 2°, janela de até 32 dias, coleção allowlist e limite de 25 cenas. HTTP com timeout e sem redirect, resposta JSON de até 2 MB. Parser offline retorna apenas metadados (ID, coleção, hora da imagem, bbox, porcentagem de nuvens, nomes dos assets e SHA). NÃO baixa imagem nem acessa URLs de assets ou `next` retornadas; rejeita respostas inconsistentes e imagens fora da janela.
- **Quatro produtos importantes sem nova chave**: os dois XLSX oficiais USDA AMS GTR, Earth Search STAC e ESA WorldCover 2021. A USDA FAS chave existente é independente dos arquivos GTR públicos.
- **Estado**: `enabled=false`, `runtime_enabled=false`, `collection_authorized=false`, `scheduled_enabled=false`, sem banco, armazenamento ou deploy. Código de consulta STAC não significa ingestão operacional homologada.

## Por que estas bases fecham lacunas do NIVON

| Fonte | Link | Papel e limitações |
| --- | --- | --- |
| USDA AMS GTR Table 1 | https://www.ams.usda.gov/sites/default/files/media/GTRTable1.xlsx | Indicadores semanais de frete por rodovia, ferrovia, barcaça e navio **nos EUA**; dados usados como proxies, jamais equivalentes a frete contratado em MT |
| USDA AMS GTR Tables 2A/2B | https://www.ams.usda.gov/sites/default/files/media/GTRTable2A_B.xlsx | Comparação de preços interiores/exportação, spreads/basis de soja/milho/trigo, cotações citadas no estudo. Não substitui dados históricos oficiais licenciados CME/CBOT |
| Earth Search STAC v1 | https://earth-search.aws.element84.com/v1 ; https://element84.com/earth-search/examples/ | Catálogo público Sentinel-1/2, Landsat C2 e Copernicus DEM, sem chave. API gratuita sem garantia SLA. Antes de baixar COGs, avaliar licença específica, custos de transferência/processamento e nuvens |
| ESA WorldCover 10m | https://registry.opendata.aws/esa-worldcover/ ; https://esa-worldcover.org/en/data-access | Classes de cobertura terrestre global **2020 e 2021**, produto CC BY 4.0, arquivos por tiles GeoTIFF, não mapa anual 2026. Portal original esteve em manutenção na verificação; distribuir via AWS/Zenodo/ESA |
| JRC Global Surface Water | https://global-surface-water.appspot.com/download | Série de água superficial 1984–2024; atualização publicada em 15/10/2026 requer conciliar V1.4 histórica com V1.5 recente, mudanças Landsat C1/C2 e artefatos da recorrência mensal. Não converter cobertura superficial em vazão/navegabilidade sem calibrar cotas ANA |
| NOAA ENSO | https://psl.noaa.gov/data/timeseries/month/ | Índices mensais ONI/RONI/MEI v2 ajudam regimes climáticos e backtests agrícolas; base e revisão de índice diferentes, não equivaler anomalia a previsão |
| WB Pink Sheet | https://www.worldbank.org/en/research/commodity-markets | Preços internacionais mensais de fertilizantes/energia/agrícolas como contexto, não preços físicos locais, fretes negociados ou CBOT tick |

**Outras melhorias no catálogo existente sem duplicação:**

- UN Comtrade possui plano gratuito com até 500 requisições por dia, 1 req/s e até 100 mil linhas por consulta via conta/chave gratuita (limites detalhados precisam ser conferidos no uso). Arquivos Bulk são produto Premium, portanto não afirmar bulk gratuito. Fontes: https://comtradeplus.un.org/Subscriptions e https://uncomtrade.org/docs/un-comtrade-api/.
- USDA AMS AgTransport (https://www.ams.usda.gov/services/transportation-analysis) oferece API/exportações para dados multimodais, além das planilhas diretas. Priorizar rota exata, metadados, direitos e esquema antes de homologar.
- USGS migra suas APIs de vazão para https://api.waterdata.usgs.gov. **O legado WaterServices será desligado em fevereiro de 2027**, segundo documentação de 2026: não começar conector novo em serviço antigo. Aplicação principal EUA, boa referência logística internacional, mas ANA segue canônica para rios brasileiros.
- Os demais candidatos já cadastrados (FAO WaPOR, Copernicus GloFAS, MAPA/IBGE, ANP, ANTAQ, ONTL, IMEA) continuam prioritários para dados nacionais.

## Critérios de ativação

1. Smoke HTTP real e layout STAC, GTR XLSX, horários, metadados e disponibilidade.
2. Revisão de atribuição/licença/limites por camada. Não tratar catálogo público como licença para toda imagem.
3. Ingestão seletiva por AOI e safra, caches e versões das cenas; não baixar o Brasil inteiro.
4. Histórico com vintage, hash, `competencia`, `referencia`, `publicacao` e `coleta`. Não inventar publicação nem usar série revisada em backtest de antes da revisão.
5. Persistência exportável, deduplicação e backup/restore em banco escolhido do NIVON sem iniciar serviços pagos.

## Links técnicos e testes

- Earth Search: `src/nivon/earth_search_stac.py`
- Testes STAC: `tests/test_earth_search_stac.py`
- Testes de governança: `tests/test_catalogo_earthsearch_gtr.py`

Testes usam somente fixtures sintéticas e conexão injetada; não comprovam resposta real ou processamento de imagem.
