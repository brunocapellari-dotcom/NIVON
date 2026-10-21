# NIVON — Catalogação controlada NOAA CPC RONI (ERSSTv6)
**Data:** 21/10/2026. **Situação:** descoberta e parser offline documentados; **coleta/agenda/publicação DESLIGADAS**.

## Evidência externa e endpoint

- [NOAA CPC — RONI oficial](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/)
- [Arquivo ASCII oficial](https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt): colunas `SEAS YR ANOM`. O URL do arquivo foi aberto em 21/10/2026, mas esta rodada **não gravou o conteúdo RAW real no repositório** nem demonstrou a execução do parser sobre amostra real em CI. O parser `nivon.noaa_roni:importar_roni_ascii` tem testes sintéticos.
- O NOAA CPC descreve RONI como média de **três meses sobrepostos** com anomalia SST Niño 3.4 relativa aos trópicos, usando ERSSTv6 e baseline 1991–2020; episódios históricos exigem ao menos cinco temporadas consecutivas com limiar ±0,5 °C.
- O portal informa atualização até o **dia 5 de cada mês**, e que valores recentes ainda podem mudar por até **dois meses**. Nenhuma data por linha do arquivo ASCII deve ser inventada a partir da competência central da temporada.
- A série retrospectiva obtida hoje **não reconstitui** vintages disponibilizadas em 1950, 2015 ou na data de previsão de anos anteriores. Não usar como feature retrospectiva sem arquivo arquivado naquela época.

## Implementação no catálogo

- `config/fontes_nivon_master.v1.json`: `NOAA_ENSO_RONI` no grupo `CLIMA`, `stage=CANDIDATE`, periodicidade proposta `MONTHLY`, `source_id=NOAA`, `existing_module=nivon.noaa_roni:importar_roni_ascii`.
- `config/rotas_coleta.v1.json`: `DIRECT_PUBLIC_FILE` para o URL ASCII exato do CPC, com origem documental no portal. Ter um URL conhecido **não ativa** o acesso, não prova atualização nem resolve licença.
- `src/nivon/rotas_coleta.py`: o único hostname NOAA CPC aceito como alias neste registro é `www.cpc.ncep.noaa.gov`, com trava adicional da **rota RONI completa**, impedindo substituição de ONI/RONI ERSSTv5 ou outro caminho.
- Nenhuma chamada HTTP adicionada ao código; nenhuma coleta ou login, dado RAW, secret, agendamento, Google Cloud ou deploy realizados.
- Direitos de **coleta, armazenamento, redistribuição, atribuição e uso** ainda exigem confirmação explícita. O NIVON não comercial não dispensa avaliação de termos.
- Os flags `enabled`, `collection_authorized`, `commercial_redistribution_authorized`, `runtime_enabled` e `scheduled_enabled` seguem `false` e `last_verified_data` permanece `null`.

## Checagens de regressão

`tests/test_noaa_roni_catalogo_off.py` protege:
1. Fonte e rota únicas no catálogo mestre.
2. URL institucional e link para prova do recurso documental.
3. Consistência da contagem catálogo↔rotas e consulta offline no plano.
4. Falha fechada quando qualquer flag operacional ou de redistribuição fica `true`.
5. Rejeição de alteração da rota para outro produto/versão ou domínio não permitido.
6. Comportamento honesto do parser: valores retrospectivos importados **não são** vintages point-in-time homologadas.

A correção dos testes anteriores substitui a hipótese de dataset ausente pela classificação correta `CANDIDATE` **sem autorização operacional**.

## Próximo gate real

Verificar direitos aplicáveis e atribuição, obter arquivo real autorizado de maneira pontual com SHA e carimbo de obtenção, testar parser sobre schema do recurso observado, auditar eventuais quebras, persistir snapshots RAW com versões e **prova autêntica de publicação anterior à data da decisão**. Só então discutir diagnóstico ENSO corrente. Qualquer feature preditiva precisa de protocolo separado de backtest OOS e controles de confusão de ENSO com MJO, sazonalidade e geografia.

**Esta nota não representa homologação operacional nem cientificamente validada de previsão regional.**
