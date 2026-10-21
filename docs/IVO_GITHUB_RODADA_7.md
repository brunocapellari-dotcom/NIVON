# IVO — Integração com históricos do NIVON (rodada 7)

**Data-base: 20/10/2026.** PR de desenvolvimento, custo adicional zero, sem deploy, sem merge,
sem fontes comerciais habilitadas e sem previsão real homologada.

## Objetivo

Parar de criar laboratórios isolados e permitir que o IVO **leia os bancos
que o NIVON já sabe produzir**. Nesta rodada a integração é real em nível
de *código e contrato* e testada sobre bancos SQLite sintéticos: o sistema
não afirma que o banco de produção já foi preenchido.

## Componentes integrados

### 1. CONAB: séries históricas por safra

`src/nivon/ivo_conab_bridge.py` consulta por arquivo oficial previsto no
`conab_series.ARQUIVOS`, unidade, UF, indicador e corte temporal. Usa as
tabelas existentes `conab_edicoes`, `conab_coletas` e
`conab_observacoes`, sem copiar o histórico ou modificar o schema.

A saída conserva versão de arquivo SHA-256, data de publicação, data de
captura, safra, distinção entre soja e milho (total, 1ª, 2ª e 3ª safras),
unidade, cabeçalho inferido e **classificação de verdade original**:
- `INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO`;
- `PROJETADO_CONAB`.

Somente edições com publicação informada e captura anterior ao corte
participam da visão `as-of`. Uma revisão posterior não altera uma
resposta produzida com corte histórico anterior.

**Gate importante:** a planilha CONAB registra safras informadas e
projetadas; esse contrato NÃO certifica a produção agrícola final
efetivamente realizada. Portanto nenhuma dessas linhas é convertida em
`historico.Observacao(natureza="OBSERVADO")` ou rótulo de treino.
O laboratório mensal existente não deve confundir safras com meses.

### 2. ANA / INMET: indicadores mensais de estação

`src/nivon/ivo_ambiental_bridge.py` consulta o SQLite já existente
`series_ambientais.consultar_asof`, exigindo:
- mesmo dataset, mesma estação, mesma grandeza, unidade e natureza observada;
- existência dos **28/29/30/31 dias** da competência, sem interpolação
  e sem substituir dia não registrado por zero;
- referência, publicação, captura e revisão temporalmente válidas;
- manutenção da origem do registro `SINTETICO` ou `REAL_AUTORIZADO`,
  sem misturar as duas classes num mesmo agregado;
- rejeição de fonte sem prova de direitos para armazenamento real.

São implementadas as regras físicas básicas: chuva diária acumulada soma
em mm por mês; cotas/vazões, temperaturas, umidade e vento recebem média
das medidas diárias no respectivo escopo. Média de temperaturas mínimas
diárias NÃO representa mínima absoluta mensal. Média de valores diários de
vazão NÃO equivale a volume mensal sem integração temporal e perfil
hidrológico; não extrapolar um único ponto de estação para bacia inteira.

O retorno é um **candidato mensal não homologado**, mesmo quando a classe
da fonte está registrada como `REAL_AUTORIZADO`: coleta/armazenamento
não prova automaticamente direito de treinamento, publicação, modelagem
preditiva ou redistribuição.

### 3. Dossiê agrícola + ambiental

`src/nivon/ivo_dossie_agroclimatico.py` integra as duas consultas em
um único resultado estruturado. Expõe a disponibilidade de cada fonte,
linhas/safras, evidências e o corte solicitado, mas **não** declara:
- que a estação consultada está georreferenciada na UF escolhida;
- que há causalidade entre precipitação e produção;
- que mês meteorológico corresponde à safra inteira;
- que CONAB informou volume realizado;
- que os dados autorizam automaticamente treinamento e divulgação.

### 4. Testes E2E

`tests/test_ivo_conab_bridge.py`, `tests/test_ivo_ambiental_bridge.py`
e `tests/test_ivo_dossie_agroclimatico.py` criam bancos SQLite com os
próprios esquemas/métodos do NIVON; validam cortes anteriores e posteriores,
revisões, anos de safra, ausência de publicação, estações distintas,
dias faltantes, chuva, temperatura, vazão, direitos, data e não inferência
causal. Todos os dados desses testes são explicitamente sintéticos.

## Próximos bloqueios técnicos

1. **Dados reais**: coletores autorizados precisam popular bancos de
   histórico no ambiente cloud, preservando SHA, referência, publicação,
   captura e revisões. O código offline sozinho não faz backfill.
2. **Rótulos agrícolas realizados**: localizar/verificar oficialmente os
   números finais de safra e condições de uso em relação aos boletins
   CONAB, mantendo separação da primeira estimativa e dados revisados.
3. **Fenologia/geo**: associar estação e grade a geometria e cultura
   apenas com mapa de localização, resolução, cobertura espacial,
   janela fenológica e método meteorológico documentado.
4. **Modelo apropriado à frequência**: não impor modelo mensal de variáveis
   não negativas a temperatura negativa, chuva diária, nível de rio,
   percentual de plantio ou séries por safra.
5. **Dados, treino e avaliação**: preparar features exógenas as-of e
   backtest walk-forward com baseline, intervalos e métricas por safra,
   região, regime e horizonte; aprovar modelo por evidência independente.
6. **Direitos e produção**: obter prova de licenças por operação; integrar
   a Knowledge Factory e Hermes por contrato autenticado; testar extras
   opcionais reais, recursos cloud, logs, backups e rollback; GO-LIVE
   exige segurança, confiabilidade e observabilidade.

Status: **integração de código e testes, NÃO dados reais ou IA em produção**.
