# NIVON — Consolidação de Meteorologia e Hidrologia

**Data:** 21/10/2026. **Estado:** código testado apenas com dados sintéticos; sem merge, coleta ou deploy. **Branch-alvo:** `integration/nivon-auditoria-20261020` (PR #13).

## Dependências e decisão de merge

A árvore consolidada preserva a cadeia de commits
`#13 → #19 (vazão e precipitação as-of) → #46 (parser INMET da #9) → #55 (MJO/RMM da #11)`.
A PR de consolidação deve ser revisada **como uma unidade**, sem reaplicar os dois parsers importados pela integração central e sem declarar as PRs #9 e #11 totalmente incorporadas (elas possuem **outros arquivos**, não transferidos aqui).

| Frente | Preservado | Ainda pendente |
|---|---|---|
| #19 | Verificadores as-of de vazão média e precipitação acumulada, SHA RAW, adapter QC INMET | Dados reais, skill OOS, autenticação de QC |
| #46 ↔ #9 | `inmet_horario_qc.py` e teste originais em blobs Git idênticos | Outros motores, modelos e catálogos da #9 continuam fora da consolidação |
| #55 ↔ #11 | `mjo_rmm.py`, teste e 2 documentos originais por blobs Git idênticos | Fonte BOM_RMM e licenças, vintages históricas reais, previsão regional condicionada |
| #13 | Destino de integração existente, preservado | Reconciliação transversal com todas as outras frentes |

`config/integracao_meteo_hidro.v1.json` é o manifesto auditável desta cadeia.
`tests/test_integracao_meteo_hidro_gates.py` calcula **Git SHA-1 do conteúdo byte a byte**, verifica os 6 blobs upstream, controla entrypoints, duplicações, permissões e fontes em estado OFF. Alterar parser importado exige reconciliação intencional com a PR de origem e atualização explícita do manifesto.

## Correção científica: CPTEC/MERGE NÃO é previsão NWP

Uma versão anterior de `pacotes_chuva_asof.py` permitia `CPTEC_MERGE` entre as fontes que entregariam forecasts NWP ensemble. Foi **bloqueada** essa classificação: MERGE combina dados observados de precipitação com estimativas por satélite e constitui **produto de análise/monitoramento**, usado inclusive como referência para verificar previsões. Não é um ensemble prognóstico de múltiplos membros emitidos antes do período a avaliar. A verificação NWP permite somente os candidatos `NOAA_GFS` e `ECMWF_MODELOS` no contrato atual e, mesmo assim, só pacotes efetivamente ensemble 3–100 membros com emissão e arquivo previamente publicados/capturados.

**Origem técnica oficial:** [INPE – acervo de dados MERGE](https://data.inpe.br/dados/merge/). Dados de grade MERGE exigem contratos de observação específicos (janela espacial, reprocessamento, latência, QC e proveniência) antes de serem usados como referência; a correção NÃO habilita MERGE como observação de estação. Catálogo e coletores permanecem OFF.

## Gatilhos obrigatórios antes do próximo estágio

1. CI íntegra no **SHA final** da PR consolidada, sem ignorar falhas dos novos testes.
2. Origem RAW, SHA, data de referência, de publicação e de **disponibilidade real** para observação e forecast arquivado; prova externa e controle de revisões. Snapshot baixado hoje não reconstitui automaticamente dados disponíveis em data passada.
3. Revisão de direitos de coleta, armazenamento, tratamento/pesquisa e eventual redistribuição, individual por dataset; evitar registrar segredos, tokens ou dados brutos privados no Git.
4. Confirmação do horário físico de precipitação horária INMET, regras QC instrumentais, mudança de estação, fuso da estação e integridade de 24 horas; parser e adapter não conferem qualidade real por si.
5. Edição histórica fora da amostra, separação temporal e espacial, baselines meteorológicos sem look-ahead, métricas por horizonte, safra, região e extremos; nenhuma decisão operacional de safra, frete, rio ou estrada até homologação.
6. Alinhar a estratégia de merge com o integrador central para não aplicar versões divergentes dos mesmos módulos. PRs seguem draft.

**Resultado pretendido desta PR:** uma única proposta revisável contra a integração #13, mais um gate executável de proveniência e estado OFF. Não é uma PR de go-live.
