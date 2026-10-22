# NIVON — inspeção NOAA RONI com amostra publicada (21/10/2026)

**Escopo:** parser e contrato offline testados contra **24 valores 1950–1951 transcritos da publicação NOAA CPC**. A transcrição testada não é um arquivo RAW original baixado, autenticado ou arquivado. Nenhum job remoto, coleta periódica ou persistência foi ativado.

## Checagem da fonte oficial

- Origem primária e versão: [NOAA CPC RONI ERSSTv6](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/).
- Arquivo `SEAS YR ANOM`: [RONI.ascii.txt](https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt). Consulta de leitura da página exibiu **921 linhas, incluindo cabeçalho, até JAS 2026**; não implica captura de bytes originais no runtime do NIVON.
- Valores de controle: DJF 1950 = -1,19 °C; MJJ 1950 = -0,75 °C; NDJ 1950 = -0,50 °C; MAM 1951 = +0,63 °C; SON 1951 = +0,98 °C; NDJ 1951 = +0,71 °C. Os 24 valores sequenciais 1950–1951 constam como **excerto textual transcrito** em `tests/test_inspecao_roni_offline.py`.
- A NOAA descreve temporadas de três meses sobrepostos, limiar ±0,5 °C durante cinco temporadas consecutivas para episódios históricos. Valores recentes podem ser revisados até dois meses após publicação. A data central de referência não é a data de publicação por linha.
- Direitos: a [política NWS](https://www.weather.gov/disclaimer/) informa que suas informações são de domínio público, salvo indicação em contrário, com restrições de atribuição, uso indevido da marca e falsa associação ou apresentação de material modificado como oficial. Isso é **referência geral, não parecer jurídico de licença de cada fonte**; verificar condições específicas/atribuição do CPC e eventual reutilização antes de habilitar coleta e armazenamento.

## Implementação versionada

`src/nivon/inspecao_roni_offline.py` recebe os **bytes fornecidos pelo usuário/processo autorizado**, URL declarada, instante de coleta e SHA-256 esperado. Confere o hash dos bytes, bloqueia caminhos que não são o arquivo NOAA RONI ERSSTv6, delega ao parser canônico `noaa_roni.importar_roni_ascii` e devolve somente **resumo sem RAW**, com número de temporadas, início, fim, quantidade retrospectiva de episódios, tamanho, instante de coleta e hash.

- `EXCERTO_24_OU_MAIS`: permite inspeção estrutural de amostras >=24 meses centrais; **não** admite status de histórico integral.
- `HISTORICO_DESDE_1950`: exige que o arquivo comece em 1950-01 e tenha >=900 temporadas consecutivas. Isso é apenas **gate de cobertura estrutural**, não prova de originalidade, atualidade ou vintages.
- Os flags `origem_autenticada_externamente`, `sha256_ancorado_externamente`, `observacoes_reais_comprovadas`, `licencas_e_atribuicao_auditadas`, `publicacao_individual_conhecida`, `reconstrucao_historica_asof_aprovada`, `aptidao_uso_preditivo`, `pode_ativar_coletor` e `homologado` permanecem `false`.
- O SHA passado pelo chamador é uma comparação de integridade **local**; se o próprio chamador calcular SHA sobre bytes adulterados, a verificação de origem não detectará falsificação. Certificação externa exige evidência imutável de resposta/assinatura oficial obtida e armazenada na data correta.
- Não registrar o RONI de 2026 como previsão de chuva/produção; manter separado de MJO, análise por estação/grade e NWP.
- `registro_motores.py` e `motores_inteligencia.v1.json` incluem só a função de inspeção offline na meteorologia, mantendo fontes e motores com flags OFF.

## Limite de execução desta rodada

O acesso de leitura ao texto da página oficial funcionou. A tentativa de baixar diretamente o arquivo RAW pelo mecanismo de download do ambiente **falhou**, portanto não há hash SHA-256 verificável **dos bytes oficiais integrais**, nem ensaio E2E com esse arquivo integral. O CI reproduz o processamento somente do excerto **transcrito** a partir da publicação oficial e de séries artificiais usadas nos testes de erro/completude. Não afirmar validação real da coleção completa.

## Próximo passo

Usar recurso local autorizado para baixar uma única vez o arquivo oficial ASCII, manter RAW e SHA em storage privado com origem, UTC da captura, headers HTTP (se disponíveis), política de direitos, hash conferido independentemente e relatório QA; comparar com datas/valores âncora sem presumir datas de publicação por linha. Somente depois validar a série completa e modelar diagnóstico ENSO corrente; nenhuma feature point-in-time histórica deve ser habilitada sem vintages autênticos de sua época.
