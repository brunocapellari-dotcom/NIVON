# NIVON — Auditoria científica inicial de Meteorologia e Hidrologia

**Data-base:** 2026-10-20. **Branch isolada:** `feat/meteo-hidro-verificacao-vazao-asof-20261020`, baseada na branch de integração do PR #13. Nenhum merge na `main`, implantação, coleta automática, licença presumida ou custo externo.

## 1. Achados verificados diretamente no repositório

Em `main` permanece só README; o código está em branches de desenvolvimento. A branch do PR #1 já contém:
- `motores_meteo_hidro.py`: graus-dia, anomalia de chuva, balde de água do solo, indicadores de estação/rio; não calcula navegabilidade.
- `motores_agrometeorologia_fao56.py`: ET0 Penman–Monteith com Rn líquido, umidade e vento a 2 m.
- `hidrologia_chuva_vazao.py` e `hidrograma_bacia.py`: NRCS SCS-CN cumulativo e roteamento Muskingum/convolução com conservação.
- `ensemble_hidrologico_bacia.py` e `chuva_areal_ensemble.py`: cascata de membros NWP por pesos GIS externos, sem calibrar frequências.
- `motores_hidrologia_cientifica.py`: curva-chave interpola entre aforos, balanço de reservatório e métricas NSE/RMSE; função de vazão baseada em ARRAYS não garante identidade, alinhamento, disponibilidade das edições nem regularidade temporal.
- `validacao_previsoes_ambientais.py` e `meteorologia_probabilistica.py`: gates de publicação e lead time, CRPS/Brier, ainda com independência fora da amostra autodeclarada.
- PR #9: `inmet_horario_qc.py`, `confronto_climatico_qc.py`, `noaa_roni.py`, etc. Essas diferenças AINDA NÃO ESTÃO reconciliadas no PR de integração.
- PR #11: `mjo_rmm.py`, parser de dados RMM com corte temporal, também NÃO incorporado à branch de integração.
**Não houve avaliação de desempenho com históricos observacionais reais nesta entrega.**

## 2. Correção nova implementada

`src/nivon/verificacao_vazao_asof.py:avaliar_hidrograma_asof` e seus testes:
- exige estação, modelo, versão e datum únicos; não compara postos incompatíveis;
- aceita **somente vazão MÉDIA POR INTERVALO** (m³/s) para integração volumétrica, com duração fixa e datas de fim de intervalo ordenadas; leituras instantâneas são rejeitadas;
- exige emissão, publicação e captura da previsão antes da validade, features disponíveis antes da emissão, baseline disponível até a publicação, observação e captura posteriores à validade; rejeita timestamps sem fuso, faltantes, `NaN`, negativos e duplicatas;
- calcula MAE, RMSE, viés, NSE, KGE 2009 (correlação, variabilidade e razão de médias), erro de volume em m³ e %, comparação MSE com baseline e defasagem temporal entre máximos de **médias intervalares**;
- deixa KGE/NSE ou horário de pico `null` quando matematicamente não identificáveis. Pico intervalar **não é pico instantâneo de cheia**;
- requer ao menos 30 pares sintéticos/realizados como limiar de integridade computacional, mas 30 observações não homologam skill;
- retorna `homologado=false`, `independencia_treino_auditada=false` e `origem_vintages_auditada_externamente=false`. Flags e horários fornecidos pelo chamador **não provam** arquivos point-in-time nem independência dos dados reais.

Integração: entrypoint inserido sob `CLIMA_HIDRO` e `HIDROLOGIA` em `config/motores_inteligencia.v1.json`, com importação restrita na allowlist de `registro_motores.py`. **Todos os gates `scheduled_enabled`, `operational_enabled` e `previsao_homologada` permanecem OFF.**

## 3. Catálogo priorizado de dados e bibliotecas

| Fonte / ferramenta | Uso científico / decisão | Critério antes de integrar |
|---|---|---|
| INMET BDMEP e estações automáticas | observação e climatologias de temperatura, chuva, vento, UR / PRIORIDADE 0 | diferenças entre estação convencional/automática, UTC, faltantes, controle de qualidade, acesso e direitos de republicação |
| ANA HidroWebService/HidroWeb | cotas, vazões e estações de referência / PRIORIDADE 0 | API nova com credenciais autorizadas, datum, curva-chave vigente, qualidade bruto/consistido e disponibilidade temporal |
| NOAA GFS | NWP determinístico e baseline independente / PRIORIDADE 1 | modelo/ciclo/lead/resolução, acumulação de precipitação GRIB, limite espacial, arquivo de edições |
| ECMWF Open IFS e AIFS / `ecmwf-opendata` (Apache-2.0) | NWP multimodelo e ensembles / PRIORIDADE 1 | apenas subconjunto aberto CC-BY-4.0 com atribuição, versões e limites; download direcionado para manter custo zero |
| ERA5-Land / CHIRPS v3 / NASA IMERG / NASA POWER | reanálise e estimativas retrospectivas / PRIORIDADE 1 | **não tratar como previsão futura nem observação pontual**; licenças, QC, versões e pixel versus posto |
| CPTEC/INPE | observações, radar, satélite, modelos regionais / PRIORIDADE 1 | identificar produto concreto, URL atual, licença e suporte de ingestão |
| `pyet` | comparação independente da FAO-56 / BENCHMARK | versão e licença de runtime, confronto com exemplos FAO e biblioteca interna |
| `xclim` (Apache-2.0) | índices de extremos, calendários CF / BENCHMARK | carga de dependências, unidades e validação por bioma |
| `HydroMT` (MIT) | GIS e extração de bacias / BENCHMARK | plugins/licenças independentes, CRS/área e reprodutibilidade |
| `xHydro` (Apache-2.0) | índices e estatística hidrológica / BENCHMARK | extrapolações, séries curtas, tempo de retorno e distribuição adequada |
| `neuralhydrology` (BSD-3-Clause) | experimento de IA para vazão / RESERVE | somente após baselines físicos, dados reais e holdout por bacia, ano e regime |
| `openstreams/wflow` Python antigo | estudo de métodos / NÃO ADOTAR COMO DEPENDÊNCIA | framework Python arquivado em 2026, GPLv3; avaliar evolução atual separadamente |

Referências oficiais:
- https://bdmep.inmet.gov.br/
- https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais
- https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast
- https://www.ecmwf.int/en/forecasts/datasets/open-data
- https://github.com/ecmwf/ecmwf-opendata
- https://github.com/pyet-org/pyet
- https://github.com/Ouranosinc/xclim
- https://github.com/Deltares/hydromt
- https://github.com/hydrologie/xhydro
- https://github.com/neuralhydrology/neuralhydrology
- https://github.com/openstreams/wflow

**Observação operacional 20/10/2026:** ECMWF abriu IFS Open 0,1° além do 0,25° já distribuído; 0,1° aumenta custo de tráfego e processamento e não equivale a medição 9 km em cada fazenda. ANA comunicou migração do serviço SOAP legado para nova API HidroWebService; não iniciar arquitetura nova no SOAP legado.

## 4. Contratos e experiências científicas exigidos antes de go-live

1. **Ingestão:** snapshots RAW com SHA-256, dataset/source ID, geometria, unidade, `competencia`, `data_referencia`, `data_publicacao`, `data_coleta`, timezone, revisão, flags de QC e contrato de direitos por operação. Ao consultar `as-of`, usar a vintage efetivamente disponível na época.
2. **Análise meteorológica:** balanço radiação/energia, controles de chuva acumulada versus taxa, UTC, resoluções, estação/pixel, cobertura e observações conflitantes. Bias-correction apenas com calibração temporal isolada.
3. **Modelos de vazão:** linha base persistência/sazonal ingênua; CN e hidrograma conservativos; avaliação por bacia, sub-bacia e evento; normalização por área somente com consistência hidrológica. Ensaio com hidrograma contínuo e baseflow é etapa posterior, não inferir via simples SCS-CN.
4. **Backtesting:** rolling origin por ano hidrológico; holdout por bacias e regimes (seca, cheia, transição); métricas MAE/RMSE, NSE/KGE quando definidas, erro de volume e de temporização, picos e vazões mínimas, Brier/CRPS/calibração para ensembles; intervalos preditivos com cobertura observada.
5. **Produtos setoriais:** chuva para plantio/colheita/armazenagem; tráfego rodoviário requer informação de solo/via além de chuva; navegação exige régua, datum, vazão, batimetria, corrente e informação oficial. Nunca liberar calado ou porto com uma fórmula simples.
6. **Operacionalidade:** fonte real autorizada, 3+ capturas com integridade, QA independente, histórico em armazenamento durável com restore e custos medidos, execução reprodutível, testes integrados no SHA de release e validação independente fora da amostra.

## 5. Pendências prioritárias de integração entre frentes

- Frente 01: reconciliar PR #9 (QC/NOAA/ANA) e PR #11 (MJO), e este PR, sem sobrescrever arquivos homônimos.
- Frente 02: normalizar API ANA nova/INMET, snapshot e semântica da precipitação acumulada; nenhum token no GitHub.
- Frente 07: implementar avaliação OOS espacial/temporal e calibração por horizonte com edições originais arquivadas.
- Frente 09: hidrologia só fornece indicadores com provenance, não sinal de navegabilidade automático.
- Frente 14: CI verde no commit final, revisões de licenças/dados, QA de resultados reais e gates de liberação.

**Estado editorial:** `CODE_ONLY`; sem alegação de previsão operacional, sem integração paga, sem serviços ligados e sem WhatsApp.
