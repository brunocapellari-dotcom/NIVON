# MDIC → série mensal controlada → cenário preditivo

`series_mdic_modelos.montar_serie_mdic` utiliza **exclusivamente o SQLite de agregados anuais versionados**: seleciona a edição conhecida até `corte_coleta`, por ano civil, exportação ou importação, NCM8/SH4, UF fiscal, código de produto e variável (`PESO_LIQUIDO_KG` ou `VALOR_FOB_USD`). Exige de 2 a 10 anos completos, todos os 12 meses por ano e todos os meses com produto/UF **explicitamente observados**; ausência nunca vira zero. Soma recortes por país e rota internacional preservando unidade, código fiscal e vinhos de SHA/data de captura, sem inferir origem agrícola, porto ou frete rodoviário.

O caminho padrão `incluir_sinteticos=False` consulta somente registros `REAL_AUTORIZADO`, que ainda não foram homologados. O resultado sempre traz flags `apta_publicacao_preditiva=False`, `apta_backtest_por_publicacao=False` e `qualidade_reconciliada_com_total_oficial=False`. Isso porque os snapshots MDIC ainda não comprovam a data **de publicação** nem total oficial.

`avaliar_cenario_mensal_mdic` reutiliza o motor mensal `previsoes_bibliotecas.prever_mensal` e obriga opt-in para usar sintéticos, mesmo nos testes. Nunca promove modelo nem libera notícia/previsão ao usuário. O backend de testes é injetável (sem instalar dependências ou acesso remoto). A solução é um contrato técnico para a futura inteligência preditiva, não uma previsão real confiável.

Próximas etapas: homologação das fontes e direitos, dicionários NCM/SH4 com vigência, meses historicamente completos, reconciliação dos totais reais, revisão de vintages/publicação e backtesting walk-forward independente antes do uso em produção. Sem agendamento, deploy, merge, custos ou ativação.
