# NIVON — Base histórica, científica e preditiva integrada

**Referência:** 20/10/2026. **Estado:** implementação e documentação versionadas, sem deploy, coleta recorrente ou previsão homologada.

## Fonte de verdade e sem duplicação

A fonte de verdade de metadados operacionais permanece nos arquivos:
- `config/fontes_nivon_master.v1.json`: **101 fontes e 139 datasets** após a reconciliação de outubro de 2026.
- `config/rotas_coleta.v1.json`: endpoint, documentação, tipo de aquisição, direitos separados, status, código e bloqueios por dataset.
- `config/matriz_produtos_indicadores.v1.json`: dependências de dados para as 28 frentes.
- `config/motores_inteligencia.v1.json`: funções matemáticas/ambientais ligadas às frentes, **sem habilitar operação**.
- `config/catalogo_tecnico_historico.v1.json`: evidências documentais e cobertura histórico-científica sem criar outros cadastros de operação.
- `config/bibliotecas_cientificas.v1.json`: bibliotecas e códigos do AgroLog/GitHub com licença e finalidade.

**Aliases conceituais removidos para impedir duplicação de séries:**

| ID redundante da pesquisa anterior | Dataset canônico único na plataforma |
| --- | --- |
| `NASA_POWER_AGRO_DAILY` | `NASA_POWER_AG` |
| `UCSB_CHIRPS_V3` | `CHIRPS_V3_CHUVA` |
| `COPERNICUS_ERA5_LAND` | `ERA5_LAND_CDS` |

**Não executar os antigos módulos concorrentes de coleta NASA** (`nasa_power_nivon.py`, `pipeline_historico_nasa.py`, `vinculo_historico_nasa.py`), cuja lógica foi superada por componentes mais completos incorporados em paralelo pelo desenvolvimento principal. Os commits antigos ficam preservados no histórico Git, mas esses arquivos não integram o tree reconciliado.

## Coletores oficiais canônicos e profundidade histórica

| Fonte/dataset | Histórico | Implementação no repositório / restrição |
|---|---|---|
| NASA POWER / `NASA_POWER_AG` | diário de 1981 a quase tempo real | `nasa_power_diario.py`, `nasa_power_backfill.py`, `nasa_power_captura_manual.py`, `grade_meteorologica_store.py`; UTC explícito, cache, origem, QA e direitos; sem ingestão de longo período homologada |
| CHIRPS v3 / `CHIRPS_V3_CHUVA` | 1981+, preliminar/final | `chirps_v3_conservacao.py`; separar RNL/SAT e reconciliar pêntadas; sem série nacional materializada |
| ERA5-Land / `ERA5_LAND_CDS` | 1950+, horário | CDS/ECMWF, registro/termos; sem extração em lote validada |
| NOAA RONI / `NOAA_ENSO_RONI` | 1950+, séries mensais e médias móveis | pesquisa documental, sem API específica homologada; não concatenar índices ONI/RONI sem método |
| USDA/WASDE / `USDA_WASDE_RELEASE_VINTAGES` | arquivo de edições desde 1973 | `AgroLogMT/collector/usda_wasde.py`; exige parser, versionamento real e evidência de publicação |
| USDA NASS / `USDA_NASS` | por cultura/estatística | `AgroLogMT/collector/nass_quickstats.py`; chave e licença por operação |
| IBGE PAM/PPM/ABATE | conforme tabela, município e competência | SIDRA e módulos de ingestão já existentes, sem presumir ausência de revisão |
| CONAB, MDIC, ANP e ANA | conforme dataset oficial | preservar coletores e contratos de progresso, safra, exportação, diesel e hidrologia da branch integrada |
| CFTC COT / `CFTC_COT_WEEKLY` | varia por tipo de relatório | Socrata/CFTC; posição de terça é divulgada depois, usar data de disponibilidade |
| FAO FAOSTAT / `FAO_FAOSTAT_LONG_RUN` | séries anuais variam por domínio | dados oficiais, agrupar por área/produto/ano/método, sem inferir série municipal |
| CME/ICE/B3 | conforme licença contratual | **direitos restritos**; não automatizar a página B3 nem tratar contratos contínuos sem ajuste explícito |

**Fontes/documentação:** https://power.larc.nasa.gov/docs/services/api/temporal/daily/ ; https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land ; https://www.chc.ucsb.edu/data/chirps3 ; https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report ; https://publicreporting.cftc.gov/

## Motores matemáticos e qual módulo usar

Aproveitamento científico do AgroLog e complementos do Nivon devem ser tratados como **biblioteca única com testes de paridade**:
- `motores_agrometeorologia_fao56.py`: entrada completa observacional (temperatura, umidade, radiação *líquida*, vento a 2m e altitude), ET0 FAO-56, déficit hídrico e percentil de chuva. **A radiação solar de onda curta do NASA POWER não equivale a Rn líquida**.
- `modelos_fisicos.py`: equação FAO-56 reduzida independente; teste de concordância com a implementação meteorológica principal; reconciliação do estoque do rebanho por espécie e categoria; métricas hidrológicas NSE e KGE-2009.
- `motores_hidrologia_cientifica.py`: curvas-chave apenas **interpoladas entre aforos confiáveis**, balanço físico de reservatórios e skill de vazão contra persistência. Não converter automaticamente cota de régua em calado navegável.
- `verificacao_probabilistica.py`: Brier, Pinball e cobertura de intervalos sem confundir score com probabilidade calibrada.
- `analogos_historicos.py`: método AgroLog de distância euclidiana padronizada com filtro de disponibilidade temporal; anos análogos **não** são previsão causal nem probabilidade.
- `unidades_mercado.py`: conversão em Decimal de massa, bushels específicos da CBOT e US¢/lb, sem inferir preço produtor, basis, câmbio ou prêmios.
- `qualidade_cientifica.py`: identidades safra e estoques, erros de conservação e backtests sem uso de dados futuros.
- `historico_vintages.py`: índice genérico SQLite de edições e disponibilidades comprovadas; complementa `registro_snapshots.py` (ledger de metadados) e `avaliacao_vintages.py` (avaliação preditiva).

Testes de paridade: `tests/test_paridade_motores_cientificos.py` compara a equação FAO-56 e o NSE calculados pelas implementações independentes. Testes de sintaxe e paridade não substituem calibração agronômica.

## Regras matemáticas e critérios de rejeição

1. **Coerência física**: produção = área colhida × produtividade/1000; balanço oferta/uso; conservação de cabeças por categoria; cota-vazão conforme datum/curva-chave; volume de água no reservatório; conversões de energia, massa, velocidade e unidades por contrato. Resíduos são publicados ou reprovados; jamais ajuste escondido.
2. **Qualidade de observação**: sensor versus grade/reanálise e estimativa; coordenadas, resolução, timezone, valores ausentes, mudanças de estação e versões do modelo; não interpolar dados inexistentes como fatos.
3. **Histórico point-in-time**: competência, referência, publicação, disponibilização verificável e coleta. Backfill de arquivo atual sem prova de publicação **não** reconstrói o que era conhecido no passado.
4. **Previsão**: comparar com persistência, sazonal ingênuo, média histórica e modelo científico simples, em folds walk-forward e recortes espaciais/por cultura. Medir MAE/RMSE, NSE/KGE para vazão, Brier e cobertura para probabilidades. A incerteza não deve ser fabricada.
5. **Promoção**: aceitação depende de baselines vencidos fora da amostra, cobertura histórica/espacial, prova de vintages, auditoria de direitos, teste E2E com dados reais, segurança, restore e viabilidade operacional. Não habilitar automaticamente modelos por testes sintéticos.
6. **Licença e segurança**: autorização de leitura, download, armazenamento, derivação e redistribuição são diferentes. Segredos e RAW não entram no GitHub. Não fazer crawling, contornar bloqueios ou iniciar serviço pago.

## Próxima execução necessária

O código possui parsers, planejadores, métricas, histórico e controle de licença. A **próxima etapa verificável** é coletar amostras **reais e autorizadas**, persistir RAW fora do GitHub, cruzar NASA/CHIRPS com INMET, carregar versões CONAB/WASDE, executar backtests point-in-time, calibrar modelos e fazer avaliação independente por região e regime. Até isso ocorrer, não afirmar que o Nivon já possui séries históricas completas ou previsão científica validada.

**Integração:** esta entrega foi reconciliada com a branch de desenvolvimento no commit base `e0a5553175f83650d22e15349ca5d36eee8d0f87` (20/10/2026), sem deploy. Alterações concorrentes posteriores requerem revisão de conflitos.

## INMET horário e confronto estação–grade — 20/10/2026

`inmet_horario_qc.py` interpreta bytes CSV horários INMET do ZIP previamente inspecionado, respeitando WMO, UTC, separadores decimais, SHA do bruto e ausências. Chuva rotulada ao dia UTC somente com 24/24 horas válidas, sem inventar zero. Tmin/Tmax amostradas de bulbo seco não equivalem a extremos de instrumento dedicado.

`confronto_climatico_qc.py` confronta dados preliminares de estação com versões NASA selecionadas por `grade_asof`, somente após prova externa de QC instrumental e do intervalo horário de chuva, coordenadas comprovadas, dados temporais compatíveis e ao menos 30 pares válidos. Produz MAE/RMSE/viés **descritivos**, sem inferir skill preditiva.

INMET informa explicitamente que seus dados automáticos horários são brutos, podem conter 9999/NULL/branco e usam UTC: https://portal.inmet.gov.br/noticias/saiba-como-acessar-os-dados-meteorol%C3%B3gicos-dispon%C3%ADveis-no-site-do-inmet

BDMEP: https://bdmep.inmet.gov.br/ — links privados de exportação são temporários; não os registrar no GitHub. O email BDMEP de 25/08/2026 não é uma amostra CSV já homologada pelo Nivon.

Indicadores hidrológicos SCS-CN/Muskingum restaurados após merges concorrentes; registrar cálculo e resíduo sem assumir navegabilidade de rio.

## ENSO RONI oficial — ERSSTv6 (verificado em 20/10/2026)

Em fevereiro de 2026, o NOAA Climate Prediction Center passou a usar o **Relative Oceanic Niño Index (RONI)** para designação oficial dos episódios ENSO; o ONI segue publicado como índice diferente, não como continuação dos mesmos valores. Fonte: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/announcement.php

O endpoint oficial de dados estruturados é `https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt`, com linhas `SEAS YR ANOM` e valores trimestrais sobrepostos (DJF, JFM, ... NDJ), desde 1950. Foi documentado e ligado ao parser `noaa_roni.py`, que aceita apenas ERSSTv6, exige continuidade dos centros de temporada, identifica episódios a partir de cinco períodos consecutivos e sinaliza observações recentes como provisórias. https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/

O **último snapshot** desse arquivo pode conter reanálises e correções. O parser não inventa horários de publicação de 1950 a 2026; portanto, `pode_treinar_modelo_point_in_time=False` até obter edições com prova de disponibilidade. Correlação ENSO/chuvaprodutividade não é efeito causal e precisa de blocos sazonais, controle espacial, testes de lead/lag e validação fora de amostra. Nenhuma série RONI foi automaticamente baixada ou agendada.
