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


## 6. Continuação — prevenção de vazamento intraintervalo (20/10/2026)

**Bug científico corrigido:** métricas de acumulados (mm) e vazão média de período (m³/s) não podem validar como previsão ex ante um cenário capturado depois do início da janela cuja observação agrega. Exigir `emissao <= publicacao_previsao <= captura_previsao <= inicio_da_janela` e `features_publicadas_ate <= emissao`, além de publicação/captura da observação posterior ao fechamento da janela.

- `src/nivon/verificacao_chuva_ensemble_asof.py`: motor de verificação de previsão de **chuva acumulada por intervalo**. Requer identidade da estação, produto e versão; janelas não sobrepostas; antecedência ex ante; climatologia disponibilizada antes da janela; membros completos; QC; dados não negativos e nunca converter faltantes em 0. Reutiliza o CRPS empírico do motor já existente e calcula Brier/Brier Skill, MAE/RMSE/viés da média dos membros e confiabilidade por decil, sem promover desempenho.
- `src/nivon/verificacao_vazao_asof.py`: reforça regra para volume integrado a partir de **vazão média intervalar**; vazão instantânea continua inelegível para essa integração. Calcula agora também antecedência mínima efetiva da **captura ao início do intervalo**.
- Novas regressões sintéticas em `tests/test_verificacao_chuva_ensemble_asof.py` e `tests/test_verificacao_vazao_asof.py`; todas as flags de produção e homologação continuam desligadas.
- `config/motores_inteligencia.v1.json` registra verificação de chuva nas frentes METEOROLOGIA e CLIMA_HIDRO; allowlist de `registro_motores.py` preserva importação restrita.
- **Limites:** a fonte pode rotular incorretamente intervalos e timestamps; os contratos internos não atestam vintages originais, controle de qualidade instrumental, climatologia verdadeiramente livre de look-ahead ou validade dos membros NWP. Correção de viés, probabilidades calibradas e skill em safra dependem de backtests com dados autorizados, holdouts espaciais e edições históricas originais.

**Gate CI:** vincular a execução GitHub Actions ao HEAD final deste PR; nunca reutilizar aprovação de commit anterior para declarar aprovação de alteração posterior.

**Próxima tarefa executável:** ingestão e verificação offline de um conjunto real autorizado de previsões arquivadas (emitidas antes do intervalo) + pluviômetros INMET na mesma janela, com snapshot SHA, calendário de disponibilidade e prova de independência. Enquanto isso não existir, métricas são somente testes sintéticos, sem precisão operacional.


## 7. Continuação — pareamento de previsões e observações com hash RAW (21/10/2026)

### Código implementado

`src/nivon/pacotes_chuva_asof.py:montar_e_verificar_pares_chuva` recebe snapshots **offline** de uma previsão NWP e de uma observação de chuva para cada período, sem baixar nada. É uma ponte entre parsers/coletores e o verificador `verificacao_chuva_ensemble_asof`; NÃO substitui os parsers INMET/ANA existentes.

- Exige bytes JSON limitados (até 250 kB por snapshot) + manifesto explícito com SHA-256 coincidente, dataset/source ID canônicos, horário de coleta com fuso, classe de aquisição e hash de prova externa de disponibilidade.
- Os datasets previstos são `NOAA_GFS`, `ECMWF_MODELOS` e `CPTEC_MERGE`; observações normalizadas `INMET_ESTACOES` ou `ANA_HIDRO`. Isso é contrato de entrada, NÃO prova disponibilidade de produtos ensemble reais nestes datasets. Na ausência de forecast ensemble genuíno com 3+ membros, o verificador recusa o dado em vez de fabricar membros.
- Recusa metadados incompletos, JSON com chaves duplicadas/NaN, fontes com identificadores incompatíveis, observação sem QC declarado aprovado, unidades implícitas, intervalos observados de duração diferente, captura de forecast intraintervalo, previsão publicada depois da captura e observação coletada antes da publicação. A **climatologia de baseline** precisa ter sido publicada **até a emissão** da previsão, não apenas antes da captura ou do intervalo, evitando avaliação com benchmark futuro.
- Alinha exatamente um snapshot de previsão com um de observação por `estacao_id` e fim do intervalo UTC; não faz interpolação nem ignora lacunas, duplicatas, edições ou diferenças de versão.
- Preserva lista de SHAs das duas séries e produz métricas delegadas ao motor existente com `homologado=false`, `prova_externa_vintages_validada=false`, `qc_instrumental_validado_independentemente=false` e `holdout_validado_independentemente=false`. O campo `modo_validacao=FORA_AMOSTRA` enviado ao verificador é **contratual** e não prova independência da amostra.
- Para `REAL_AUTORIZADO`, bloqueia o processamento se catálogo canônico não aprovar cada dataset (`enabled` + `collection_authorized`), sem `COLETA/ARMAZENAMENTO/PESQUISA` e referência de direitos. Atualmente esses datasets estão **desativados**, portanto nenhum dado real foi promovido.
- Não registra dados RAW reais no GitHub nem armazena segredo; operação continua offline e sem alteração em ambiente de produção.

### Fronteira científica importante

O parser `inmet_horario_qc.py` da PR #9 recebe CSV horário e retorna `BRUTO_HORARIO_SEM_QC`. Mesmo quando 24 valores estão presentes, isso **não basta** para colocar `qc=APROVADO` nem para confirmar o início/fim físico do acumulado. A ligação com essa PR só pode ocorrer após convenção temporal documentada, QC instrumental atestado e testes com amostras reais autorizadas; **nenhum atestado foi criado automaticamente nesta etapa**.

### Testes e próximo gate

`tests/test_pacotes_chuva_asof.py` cobre hash adulterado, identidade e versão, intervalos, captura tardia, não pareamento, faltantes, duplicações, fonte incorreta, JSON malformado, direitos e bloqueio de dados reais. A CI da branch determina a aceitação do HEAD final; resultados anteriores de testes sintéticos não são evidência de precisão real.

**Próxima tarefa executável:** coordenar a reconciliação dos parsers/QC da PR #9 e MJO da PR #11 pela integração central; preparar conjuntos reais permitidos com snapshots originais de NWP, QC de estações e comprovantes históricos point-in-time. Sem evidência externa, apenas classificação `CODE_TESTED_SYNTHETIC_ONLY`, sem ativar fonte nem previsão.
