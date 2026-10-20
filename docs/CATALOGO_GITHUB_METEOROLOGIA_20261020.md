# Catálogo GitHub — Motor Meteorológico NIVON
Data da verificação: 20/10/2026. Escopo: pesquisa técnica, sem instalação, coleta, deploy ou custo autorizado.

## Candidatos por função

| Repositório | Aplicação | Licença do código observada | Decisão | Condição |
|---|---|---|---|---|
| https://github.com/ecmwf/ecmwf-opendata | Coletar IFS/AIFS aberto | Apache-2.0 | ADAPT | Produtos, metadados, direitos dos dados e custo de tráfego |
| https://github.com/blaylockbk/Herbie | GFS e outros modelos NWP | MIT | ADAPT | Endpoints disponíveis, lead/run, latência |
| https://github.com/ecmwf/cfgrib | Decodificar GRIB | Apache-2.0 | USE opcional | Dependência nativa ecCodes, RAM |
| https://github.com/Unidata/MetPy | Física meteorológica | BSD-3-Clause | ADAPT | Fórmulas e unidades validadas |
| https://github.com/pySTEPS/pysteps | Radar-nowcasting e ensembles | BSD-3-Clause | ADAPT | Radar legal, QC, cobertura e skill regional |
| https://github.com/wradlib/wradlib | Processar radar | Código MIT; documentação CC BY-SA 4.0 | ADAPT | Conferir cada licença de arquivo, formatos BR |
| https://github.com/ARM-DOE/pyart | Radar/QC | BSD-3-Clause segundo README | REFERENCE | Evitar duplicação com wradlib e dependências pesadas |
| https://github.com/pytroll/satpy | Satélite ABI/GLM | Apache-2.0 | ADAPT | Geometria, memória e produto correto |
| https://github.com/blaylockbk/goes2go | Descarga GOES em NOAA NODD | MIT | ADAPT | Fixar versão >=2025.2.0 com suporte GOES-19 |
| https://github.com/earthaccess-dev/earthaccess | Busca NASA GPM/IMERG | MIT | ADAPT | Autenticação e termos por dataset |
| https://github.com/meteostat/meteostat | Séries climatológicas | Código MIT | REFERENCE | Fonte/direitos dos dados e cobertura BR |
| https://github.com/Ouranosinc/xclim | Índices extremos e climatologia | Apache-2.0 | USE | Normal do mesmo período, gaps e resolução |
| https://github.com/pyet-org/pyet | Evapotranspiração | MIT | USE para benchmark | FAO-56 e parâmetros locais |
| https://github.com/xarray-contrib/xskillscore | Skill meteorológico | Apache-2.0 | USE | Leakage, baselines e amostras |
| https://github.com/nci/scores | Brier, CRPS e outras métricas | Apache-2.0 | USE para auditoria | Evitar bibliotecas redundantes |
| https://github.com/pangeo-data/climpred | Hindcasts e S2S | MIT | ADAPT | Vintages e independência temporal |
| https://github.com/brandonwkerns/mjo_rmm_index | BOM RMM + diagrama de fases | MIT | REFERENCE/ADAPT | Dados reais BOM, cronologia e licença dos dados |
| https://github.com/khalilv/mjo-predict | Pesquisa de previsão MJO | MIT | REFERENCE | Sem evidência de validação regional operacional |
| https://github.com/openclimatefix/skillful_nowcasting | DGMR radar com PyTorch | MIT | REFERENCE | Requer radar e recursos; candidato experimental |
| https://github.com/meteofrance/original-dgmr | DGMR francês | Apache-2.0 | REFERENCE | Não pressupor skill no Brasil |
| https://github.com/Deltares/hydromt | Estruturação de bacias | MIT | ADAPT no módulo hidrológico | Não duplicar motor clima |
| https://github.com/ocfgaldino/inmetpy | Antigo cliente INMET | Não validada | REJECT runtime | README informa descontinuação por mudança da API |
| https://github.com/open-meteo/open-meteo | API meteorológica e servidor | AGPL-3.0 | REFERENCE | API gratuita anuncia uso não comercial; autohospedagem e compliance requerem estudo |

USE = candidato a benchmark/dependência opcional; ADAPT = integração planejada após homologação; REFERENCE = estudar sem incorporar; REJECT = não adotar como runtime no estado atual. A licença de código não substitui a autorização de dados.

## Fonte primária de satélite GOES-19

Catálogo NOAA NODD: https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-goes.yaml
Bucket público: s3://noaa-goes19/ (leitura sem conta AWS com --no-sign-request). NOAA pede atribuição e veda alegar endosso. Leitura pública não garante custo zero de armazenamento/processamento/transferência. O GOES-19 assumiu GOES-East em 2025.
ABI/GLM não são medições pluviométricas. Guardar horário, nível, resolução, produto, hash e proveniência; selecionar produto/cena adequada para evitar saturar VM pequena.

## Integração de MJO

O BOM fornece histórico RMM: https://www.bom.gov.au/climate/mjo/ . Usar https://github.com/brandonwkerns/mjo_rmm_index como referência de NetCDF e gráfico; NIVON já tem parser offline próprio, ainda não homologado com arquivo real.
Comparar amostra real do BOM: campos, sentinelas, fase, amplitude e eventuais sinalizadores. Índices retrospectivos capturados hoje não são garantia de disponibilidade passada para backtests as-of. Fase isolada não prevê município; amplitude <1 é sinal fraco.

## Prioridade técnica

P0: integrar de modo licenciado e testado INMET atual, observações NASA/ANA e NOAA GOES-19, e modelos GFS/IFS (Herbie/ecmwf-opendata); não baixar dados em massa; manter feeds desligados por padrão.
P1: comparar os motores NIVON com xskillscore/scores/pyet e realizar validação fora de amostra por município, estação, horizonte e evento extremo.
P2: Satpy e, havendo radar legal e cobertura, wradlib + pySTEPS. Separar mapa de observações, nowcasting e previsão; jamais interpolar observação sintética como medida.
P3: xclim, MJO, ENSO, projeções subestacionais integradas a culturas e hidrologia com incerteza. Ivo só comunica alertas derivados de modelos homologados.
P4: DGMR apenas P&D com dados e GPU disponíveis legalmente e desempenho comparado a baselines. Não pressupor GPU gratuita.

Estado: documento de seleção técnica, não implementação. Revisar versões, compatibilidade e licenças antes de instalar. Sem novos coletores ativos, chaves, agendamentos ou deploy.