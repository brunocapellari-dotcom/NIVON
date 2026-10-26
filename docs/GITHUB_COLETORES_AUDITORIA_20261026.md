# NIVON — Auditoria aprofundada de repositórios para coleta de dados
**Data da auditoria:** 2026-10-26  
**Escopo:** pesquisa de software público reutilizável, cotejada com árvore \`main\` e PRs existentes do NIVON.  
**Governança:** o GitHub não é, por si só, fonte primária oficial dos números; código e dados têm permissões independentes.

## Vereditos (ADOTAR / APROVEITAR / REFERÊNCIA / RESERVAR / DESCARTAR)

| Projeto / URL | Capacidade existente | Licença código conforme metadata GitHub | Estado no NIVON / ação |
|---|---|---|---|
| [bruno-portfolio/agrobr](https://github.com/bruno-portfolio/agrobr) | 41 fontes, 55 datasets, contratos e metadados; CONAB, IBGE, MDIC, CFTC, ANEC, USDA, CEPEA, IMEA, B3 etc | MIT | **ADOTAR** somente APIs públicas v2.0.0; \`pyproject.toml\` já fixa 2.0.0; \`conab_agrobr.py\` já existe |
| [StrategicProjects/comexpy](https://github.com/StrategicProjects/comexpy) | API ComexStat, códigos NCM, país, modal e municípios | MIT | **RESERVAR**: para detalhamento avançado quando a camada agrobr for insuficiente; NÃO duplicar consulta geral |
| [Mcamin/cftc-cot](https://github.com/Mcamin/cftc-cot) | Downloads de arquivos CFTC COT históricos | MIT | **RESERVAR**: fallback técnico de arquivos, enquanto agrobr entrega consulta oficial Socrata |
| [mspinola/cotdata](https://github.com/mspinola/cotdata) | Dados CFTC/posições e preços derivados | Licença a conferir | **REFERÊNCIA**; verificar origem e timestamp antes de mesclar |
| [blaylockbk/Herbie](https://github.com/blaylockbk/Herbie) | NOAA GFS, ECMWF/IFS, dados meteorológicos GRIB | MIT | **RESERVAR P2**: só se os coletores meteorológicos já existentes não bastarem |
| [ecmwf/ecmwf-opendata](https://github.com/ecmwf/ecmwf-opendata) | Download ECMWF Open Data | Apache-2.0 | **RESERVAR P2**; dados de previsão demandam pipeline GRIB/grade e análise de custo |
| [meteostat/meteostat](https://github.com/meteostat/meteostat) | Observações meteorológicas históricas | MIT | **REFERÊNCIA P2**: não substituir automaticamente dados oficiais INMET |
| [earthaccess-dev/earthaccess](https://github.com/earthaccess-dev/earthaccess) | API NASA Earthdata / autenticação/download | MIT | **RESERVAR P2** para sensoriamento remoto em fase posterior |
| [ropensci/nasapower](https://github.com/ropensci/nasapower) | Cliente R para NASA POWER | Licença própria/NOASSERTION | **NÃO ADOTAR**: agrobr já coleta NASA POWER em Python |
| [ropensci/rnassqs](https://github.com/ropensci/rnassqs) | Cliente R da API USDA NASS | Licença própria/NOASSERTION | **REFERÊNCIA P2**; priorizar API oficial caso seja necessário |
| [FAOSTAT/faostat-api](https://github.com/FAOSTAT/faostat-api) | API antiga FAOSTAT | GPL-2.0; último push observado em 2016 | **DESCARTAR CÓPIA**; usar serviço oficial contemporâneo |
| [GlobalFishingWatch/gfw-api-python-client](https://github.com/GlobalFishingWatch/gfw-api-python-client) | AIS presence, eventos, visitas a portos e identidades; requer token | Apache-2.0 | **RESERVAR P2**; foco pesqueiro e presença AIS não equivalem a escala confirmada de graneleiros |
| [aisstream/aisstream](https://github.com/aisstream/aisstream) | Streaming AIS | Licença conferir | **REFERÊNCIA**: NIVON já tem \`maritime/ais_stream.py\`, \`ais_ledger.py\` |
| [xang1234/neptune](https://github.com/xang1234/neptune) | Fusão AIS e inferência de visitas | Sem licença identificada | **NÃO COPIAR CÓDIGO**; somente arquitetura/referência |
| [duartejr/pyHidroWeb](https://github.com/duartejr/pyHidroWeb) | Dados hidrológicos ANA | Sem licença identificada | **REFERÊNCIA**: NIVON já tem \`ana_hidrowebservice.py\` |
| [Wwerneck/FuelPrice-Analytics](https://github.com/Wwerneck/FuelPrice-Analytics) | Coleta/ETL preços ANP | Sem licença identificada | **NÃO COPIAR CÓDIGO**: NIVON tem PPI + PRs abertas de diesel |
| [ipea/geobr](https://github.com/ipea/geobr) | Malhas geográficas oficiais brasileiras | Licença não identificada pela API | **RESERVAR P2** para normalização geográfica, preferindo IBGE oficial |
| [AlanTaranti/sidrapy](https://github.com/AlanTaranti/sidrapy) | Cliente SIDRA/IBGE Python | Verificar licença | **RESERVAR**: o NIVON já tem coletores IBGE e agrobr usa SIDRA |
| [wilsonfreitas/python-bcb](https://github.com/wilsonfreitas/python-bcb) | Séries BCB, PTAX, SGS | MIT | **REFERÊNCIA**: NIVON já possui conectores BCB, PTAX e SGS |
| [ipea/pyIpeaData](https://github.com/ipea/pyIpeaData) | Acesso IpeaData | Sem licença identificada | **RESERVAR P2**; atualizações pouco recentes |
| [mapbiomas-brazil/user-toolkit](https://github.com/mapbiomas-brazil/user-toolkit) | Coleções MapBiomas no Google Earth Engine | Sem licença identificada | **RESERVAR P2**: geo remoto requer autorização, custo e metodologia |
| [geo-credito-rural/sicor](https://github.com/geo-credito-rural/sicor) | Crédito rural / BCB/SICOR | GPL-3.0 | **RESERVAR**; melhor usar API SICOR via agrobr |
| [GoogleCloudPlatform/bigquery-utils](https://github.com/GoogleCloudPlatform/bigquery-utils) | Operação/qualidade do BigQuery | Confirmar licença e compatibilidade | **REFERÊNCIA** somente, não criar infraestrutura nova |
| [GoogleCloudPlatform/public-datasets-pipelines](https://github.com/GoogleCloudPlatform/public-datasets-pipelines) | Padrões de ETL e ingestão | Confirmar licença e compatibilidade | **REFERÊNCIA** somente |
| [jmagomez/anp-ppi-dashboard](https://github.com/jmagomez/anp-ppi-dashboard) | Parser de PPI ANP e auditoria de séries semanais | MIT | **JÁ INTEGRADO** à \`main\` NIVON via PR #327; não duplicar |

Licença não identificada significa **não comprovada**; não implica ausência absoluta de permissões. Datas de atualização são sinais de manutenção, não garantias de confiabilidade. Os contratos e autorizações dos **dados** diferem das licenças dos **programas**.

## Auditoria do NIVON antes de alterar código

- \`src/nivon/conab_agrobr.py\`: adaptador CONAB existe na main.
- \`src/nivon/coletores_dados_reais.py\`: Argentina, Canadá, CCEE etc., sem ComexStat/CFTC na main.
- \`src/nivon/ana_hidrowebservice.py\` e \`src/nivon/maritime/ais_stream.py\`: não duplicar.
- \`src/nivon/anp_ppi.py\`: integrado e verificado na main em 26/10.
- PR #56: crosswalk de fontes agrobr não mesclado.
- PR #61: integração ampla agrobr e acessos privados, não mesclada, alto risco de conflito.
- PR #75: CFTC/INPE/ANTT mesclado no passado, mas arquivos \`src/nivon/cftc_cot_publico.py\` não aparecem na árvore atual da main; reconciliar com histórico antes de reintroduzir o módulo legado.
- PRs #40, #42, #53, #154: trabalhos abertos relativos à ANP/LPC, preços e fretes; não alterar esses fluxos.

## Implementação desta auditoria

**Escolhido:** usar os contratos públicos do agrobr v2.0.0 (já pinado) para:
1. Exportações ComexStat por produto, UF, ano e mês.
2. Importações ComexStat com frete/seguro separados do valor FOB.
3. Posições CFTC de fundos, posições abertas e contratos futuros por semana.

**Arquitetura:** \`src/nivon/agrobr_mercados.py\` integra \`agrobr.datasets.exportacao\`, \`importacao\` e \`posicionamento_fundos\` ao ledger existente (\`ingestao_fontes_reais.gravar_lote\` e \`exportar_jsonl\`). Sem novos bancos, secrets, deploys nem fontes sintéticas em produção. Execução opt-in e CI offline.

**Proteções:**
- Dataset/produto/ano/UF/janela limitados antes de qualquer rede.
- \`return_meta=True\`; exigir \`selected_source=comexstat\` ou \`cftc\`, classe \`livre\`, versão agrobr 2.x e contrato compatível. Fallback ABIOVE não é permitido na exportação do NIVON por licença/cobertura diferente.
- Exportação: toneladas podem ser derivadas de \`kg_liquido\`; valor FOB USD e peso kg não podem ser confundidos. Importação: frete/seguro em USD são métricas independentes.
- CFTC: posição líquida pode ser negativa, posição aberta e comprados/vendidos não podem; distinguir referência de terça-feira da publicação de sexta.
- Preservar a identidade de cada observação, hash da versão normalizada, referência mensal/semanal e revisões pontuais.
- O arquivo gravado em \`raw/\` **não é o arquivo original MDIC/CFTC**. É um snapshot JSON serializado dos resultados já normalizados do agrobr, com tipo \`AGROBR_RESULTADO_NORMALIZADO\`; o eventual hash original de upstream é registrado em campo separado. Em etapa posterior, gravar RAW original separado somente se o adaptador autorizado fornecer os bytes.
- Coleta real, existência de dados atuais e carga GCP/BigQuery **NÃO são presumidas** com CI verde.

## Operação orientada a recursos existentes

\`\`\`bash
# ambiente executor que já recebe o extra "agro" do NIVON
python -m nivon.agrobr_mercados --dataset exportacao --produto soja --ano 2026 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_mercados --dataset importacao --produto milho --ano 2026 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_mercados --dataset posicionamento_fundos --produto soja --inicio 2026-01-01 --fim 2026-10-26 --executar --exportar-jsonl
\`\`\`

No Google Cloud utilizar a camada já existente \`carga_bigquery_fontes.py\` com \`--arquivo ... --projeto ... --dataset ...\`, somente após validação do contrato de destino e autorização explícita. Não criar scheduler/deploy adicional durante M1.

## Decisões prioritárias pós-CI

- **P0**: coletar amostra real de ComexStat e CFTC em executor autorizado, conferir dados primários e reconciliação com fonte, depois validar staging BigQuery e carga incremental.
- **P0**: conciliar PRs de agrobr sem duplicar o coletor desta PR.
- **P1**: explorar \`agrobr\` para B3, USDA PSD, pecuária municipal e fertilizantes, via contratos, em mudanças pequenas e auditáveis. USDA exige chave; não há integração real comprovada nesta entrega.
- **P2**: ANEC exige avaliação de direitos de uso das tabelas/PDF, \`agrobr[pdf]\`, separação PROGRAMADO x EFETIVADO; não misturar com line-up observado. Herbie/ECMWF, NASA Earthdata e GFW aguardam justificativa de integração específica.
- **P2**: demais projetos ficam como benchmarks/alternativas, não como dependências extras automáticas.

## Referências primárias da engenharia

- https://agrobr.dev/docs/
- https://agrobr.dev/docs/en/api/
- https://github.com/bruno-portfolio/agrobr/blob/main/docs/contracts/exportacao.md
- https://github.com/bruno-portfolio/agrobr/blob/main/docs/contracts/importacao.md
- https://github.com/bruno-portfolio/agrobr/blob/main/docs/contracts/posicionamento_fundos.md
- https://agrobr.dev/docs/licenses/
- https://github.com/brunocapellari-dotcom/NIVON/pull/327

**Nota:** esta é uma auditoria de código público, não um inventário exaustivo de todos os projetos no GitHub nem homologação de permissões para redistribuir dados.
