# NIVON — Pesquisa rastreável de APIs e bases gratuitas (21/10/2026)

## Objetivo e limites

Escopo NIVON **não comercial**: agricultura, commodities, pecuária, clima, solos/uso da terra, comércio exterior, fretes/granéis, transporte rodoviário, ferroviário, aquaviário, diesel, energia, risco e relatórios. Não há motor de receitas agronômicas.

**Importante:** "gratuito para consulta" não comprova direito para scraping, coleta recorrente, armazenamento e redistribuição. Catalogar/documentar uma API não comprova resposta HTTP válida nem coletor operacional. A branch de integração possui contratos com bloqueio default-deny; NÃO ativar agendamento, backfill integral ou custos.

## 1. Resultado da busca e incorporação

- **Quatro fontes novas**: OPEN_METEO; INPE_QUEIMADAS (separado de CPTEC); INPE_TERRABRASILIS (separado de MAPBIOMAS); DADOS_GOV_BR (metadados, separado do GOV/Radar).
- **Oito datasets novos**: dois de Open-Meteo, dois do INPE Queimadas, um PRODES WFS, um de descoberta de metadados, um de indicadores do Banco Mundial e um da Selic diária BCB.
- **Dois normalizadores offline novos**: Open-Meteo previsto/reanálise e BCB SGS 11, com testes de esquema, unidades, UTC, dados faltantes, limites e datas; **não realizam requisições**.
- Reconciliadas rotas já existentes do USDA (FAS ESR/GATS/PSD e chave API.Data.Gov gratuita) e CFTC (COT via API Socrata). Nenhum módulo duplicado, sem chave no GitHub.

## 2. Fontes de maior impacto no NIVON

| Prioridade | Fonte | Dados e endpoint/portal | Acesso/limites | Estado na branch |
| --- | --- | --- | --- | --- |
| P0 | Open-Meteo Weather Forecast | https://open-meteo.com/en/docs ; https://api.open-meteo.com/v1/forecast | Gratuito para não comercial; CC BY 4.0; 10 mil chamadas/dia, 5 mil/h, 600/min | Parser offline + rota, sem teste HTTP desta sessão |
| P1 | Open-Meteo Historical Weather | https://open-meteo.com/en/docs/historical-weather-api ; https://archive-api.open-meteo.com/v1/archive | Reanálise, não estações; modelos/vintages variam; limites gratuitos | Parser offline + rota |
| P0 | INPE Focos de Queimadas | https://data.inpe.br/queimadas/dados-abertos/ | CSV históricos e quase-real-time (informado a cada ~10 min); URL exata por arquivo e direitos ainda conferir | Catálogo/rota índice, sem parser CSV |
| P1 | INPE Risco de Fogo | https://data.inpe.br/queimadas/dados-abertos/ | Observado diário vs previsto 3 dias; formatos e downloads por variável | Catálogo/rota índice, sem parser |
| P1 | TerraBrasilis PRODES | https://www.terrabrasilis.dpi.inpe.br/faq/ ; WFS https://terrabrasilis.dpi.inpe.br/geoserver/ows | PRODES anual, camadas públicas via WFS; acesso DETER antecipado restrito | Catálogo/rota documentação; camada WFS ainda não resolvida |
| P2 | Portal Dados Abertos Brasil | https://dados.gov.br/swagger-ui/index.html ; GET /dados/api/publico/conjuntos-dados | Descoberta; metadados não equivalem dados e suas licenças | Catálogo/rota, sem coleta integral |
| P2 | World Bank API v2 | https://datahelpdesk.worldbank.org/knowledgebase/articles/889392 | Indicadores macro anuais, API sem chave; usar fonte WB existente | Novo dataset/rota, sem parser |
| P0 | BCB SGS Selic diária | https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json | Dado com campo data no formato DD/MM/YYYY; valores da série 11 são taxa diária, NÃO meta anual | Parser offline + rota, sem validação real nova |

Fontes já presentes com oportunidade de maior aproveitamento:

| Prioridade | Fonte existente | Ação mais útil |
| --- | --- | --- |
| P0 | **MDIC Comex Stat** | https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta — backfill incremental CSV anual desde 1997, correlações NCM/SH4, país, UF, via e URF; não confundir com municípios em SH4. Dados até set/2026 na atualização de 06/10/2026 |
| P0 | **ANP Diesel/Combustíveis** | https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis — séries semanais e CSV por mês/semestre. Leitura regional e municipal, não média nacional sem ponderação |
| P0 | **NASA POWER** | https://power.larc.nasa.gov/docs/services/api/temporal/daily/ — já possui parser e pipeline no NIVON, desde 1981; dados de grade, não posto meteorológico; revisões após meses e limites de requisição |
| P0 | **IBGE Localidades + SIDRA** | https://servicodados.ibge.gov.br/api/docs/localidades e https://apisidra.ibge.gov.br — o NIVON já tem parsers; foco na carga e crosswalk |
| P0 | **CONAB** | https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos — séries históricas, progresso, preços e armazéns, conforme autorização e granularidade |
| P0 | **USDA FAS ESR/PSD/GATS** | https://apps.fas.usda.gov/opendatawebv2/ — APIs oficiais com chave gratuita API.Data.Gov; projetos já têm escopo, faltam testar autenticação e endpoint exato. Guardar API key em secret, nunca no repositório |
| P1 | **CFTC Commitments of Traders** | https://publicreporting.cftc.gov/stories/s/Public-Reporting-FAQ/inwp-fmhz/ — dados semanais de posições e API, históricos Legacy desde 1986 e Disaggregated desde 2006; **não fornece cotação de CBOT** |
| P1 | **FAOSTAT** | https://faostat.fao.org/ — séries de agricultura global; API e bulk download; já catalogada. Evitar baixar arquivo global completo sem necessidade |
| P1 | **INMET** | https://portal.inmet.gov.br/dadoshistoricos/ — séries meteorológicas observadas (estação), validações e backfill controlado |
| P1 | **ANA/SNIRH** | https://www.snirh.gov.br/hidroweb/ — níveis/vazões, estações, hydrologia (acesso e limites específicos já em desenvolvimento) |
| P1 | **ANTAQ** | https://www.gov.br/antaq/pt-br/acesso-a-informacao/dados-abertos — movimentação realizada por produto/instalação, não line-up por navio; alterações históricas |
| P1 | **ONTL/Infra S.A.** | https://ontl.infrasa.gov.br/ — rede, custos, corredores e análises, distinguir estimativas e dados observados |
| P1 | **Copernicus ERA5-Land** | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — reanálise histórica, já catalogada; não duplicar a versão Open-Meteo como se fossem medições independentes |
| P1 | **MapBiomas** | https://brasil.mapbiomas.org/ — uso da terra, anual; conferir licença e versões |
| P2 | **World Bank commodity prices** | https://www.worldbank.org/en/research/commodity-markets — Pink Sheet macro e commodities, já catalogada (WB), não tick de futuro |
| P2 | **CFTC / NASA / INPE auditadas** | Comparar vintage de relatório/extração e persistência para indicadores de risco e tendência |

## 3. Dados que NÃO ficam gratuitos por consequência de outras APIs

- **Frete rodoviário negociado/efetivo por origem-destino:** o catálogo público de ANTT/MDF-e, RNTRC e CIOT não garante série aberta de fretes de mercado por rota com representatividade nacional. O módulo de fretes requer observações autorizadas e classificação de evento.
- **CBOT preços contínuos ou históricos licenciados de negociação:** posições CFTC e notícias gratuitas não são substitutos de preços CME. Manter separado de spreads, basis, prêmio e físico.
- **Line-up navio × terminal × produto em tempo real nacional:** ANTAQ movimentação realizada não é programação ou previsão de escala; cada porto exige fonte, direitos e reconciliador.
- **Dados de fazenda exatos:** ponto Open-Meteo/NASA/ERA5 representa grade; cruzar coordenadas, solos e observações instrumentais sem afirmar medida no talhão.

## 4. Plano de liberação baseado em evidência

1. CI offline valida contratos e bloqueios por fonte (status CODE_PRESENT ≠ coleta ativa).
2. Consultas reais **pontuais**, egress autorizado, limite, resposta, MIME, esquema, direitos de uso, TLS e checksum.
3. Reconciliação com fonte primária quando houver intermediários, amostra com nulos e revisões, atribuição e semântica observada/projetada.
4. Persistência privada com snapshots, versões, logs, backup/restore e consulta \`as-of\`; monitorar atraso de fonte sem inventar publicação.
5. Só então ativar em runtime mediante homologação das operações específicas; agendamento e publicação são gates separados.

## 5. Regras técnicas/legais

- Uso declarado do NIVON é não comercial, mas **não** torna públicos dados fechados nem dispensa licença. O Open-Meteo determina condições específicas e limites por IP; a fonte não pode ser tratada como ilimitada.
- Para risco de fogo, separar *ROI administrativo SISFOGO* × *foco de calor de satélite INPE* × *evento de fogo modelado INPE* × *área queimada estimada*. Nenhum é intercambiável.
- Guardar \`competencia\`, \`referencia\`, \`publicacao\`, \`coleta\`, origem, hash, unidade, modelo/satélite e data da previsão, sem substituições silenciosas.
- Não ativar download maciço, assinaturas pagas, infraestrutura recorrente ou publicação sem verificação.

## 6. Evidências e links técnicos

- https://open-meteo.com/en/terms
- https://open-meteo.com/en/docs
- https://open-meteo.com/en/docs/historical-weather-api
- https://data.inpe.br/queimadas/dados-abertos/
- https://www.terrabrasilis.dpi.inpe.br/faq/
- https://dados.gov.br/swagger-ui/index.html
- https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
- https://apps.fas.usda.gov/opendatawebv2/
- https://publicreporting.cftc.gov/stories/s/Public-Reporting-FAQ/inwp-fmhz/
- https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta
- https://power.larc.nasa.gov/docs/services/api/temporal/daily/
- https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis

**Estado da pesquisa:** documentação e fontes confirmadas; testes reais HTTP para novos endpoints não completados nesta sessão. Código e catálogo em branch/PR; fluxo operacional desativado, custos adicionais R$0. Não afirmar séries baixadas ou banco populado.
