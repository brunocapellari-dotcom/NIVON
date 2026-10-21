# IVO — Integração efetiva de MLForecast, River e DuckDB (rodada 5)

**Data-base:** 20/10/2026. **Sem deploy, merge, coleta de rede ou despesa contratada.**
Este incremento usa bibliotecas existentes *por adaptadores opcionais*; não copia
código de terceiros nem reimplementa todo o framework. Implementa apenas as
funcionalidades faltantes necessárias ao Nivon e conserva os motores originais.

## Catálogo → código → testes

| Componente do catálogo | Implementação | Validação realizada |
|---|---|---|
| MLForecast (Apache-2.0) | `ivo_mlforecast_adapter.py` | interface offline e regras temporais; integração real opcional pendente |
| MLForecast Benchmark | `ivo_benchmark_ml.py` | walk-forward, fonte/competência, MAE/WAPE/baseline, folds e testes sintéticos |
| River (BSD-3-Clause) | `ivo_river_adapter.py` | replay prequential: `predict_one` antes de `learn_one`, treino só após registro do resultado |
| DuckDB (MIT) | `ivo_duckdb_adapter.py` | consulta parametrizada de Parquet local, fonte/escopo, limite de leitura, as-of e hash antes/depois |
| HierarchicalForecast (Apache-2.0) | contrato nativo `ivo_hierarquias.py` | bottom-up aditivo somente; métodos probabilísticos/MinTrace não incorporados |

Esses projetos **não são automaticamente instalados**. O arquivo `pyproject.toml`
registra extras independentes, sem dependências obrigatórias:

- `ivo-ml`: pandas, scikit-learn, mlforecast; Ridge com lags 1, 2, 3 e 12
- `ivo-online`: river; aprendizado incremental de resíduos
- `ivo-query`: duckdb; leitura de Parquet autorizado

Na homologação isolada, instalar no ambiente temporário com
`python -m pip install ".[ivo-ml,ivo-online,ivo-query]"`
**somente após auditoria de versões, dependências transitivas, permissões de rede
e orçamento**. Executar `PYTHONPATH=src python -m unittest discover -s tests -p 'test_ivo_extras_reais.py' -v`
nesse sandbox. Na CI stdlib-only, esses testes serão ignorados, nunca
confundidos com validação real das bibliotecas.

## Comportamento implementado

### Aprendizado supervisionado por MLForecast

O adaptador exige permissão expressa de uso do dataset, fonte, produto, local,
indicador, unidade, calendário mensal e 36 meses contíguos já publicados
e coletados. Não preenche meses faltantes, não promove projeções a observações
e admite atraso de publicação de até três meses. O horizonte desde a última
observação realmente disponível até o mês-alvo é calculado, não pressuposto.
O modelo candidate é um Ridge treinado sobre features de lags; sem download,
tuning oculto ou dependências obrigatórias.

O benchmark retreina a cada fold temporal sobre o snapshot conhecido no
instante da previsão e mede contra baseline sazonal exatamente do mesmo mês
do ano anterior. Mantém folds descartados e corte de avaliação. **Resultado
retrospectivo não comprova previsão emitida em produção.** O módulo não prova
autorização real dos dados: a flag deve vir do controle externo de direitos.

### Aprendizado incremental por River

O replay de resíduos ordena previsões por emissão e só atualiza o modelo
`learn_one` com rótulos de previsões anteriores cujo resultado foi
**publicado e registrado antes da emissão da previsão seguinte**. Mede erro
original e da correção proposta; não persiste pesos, não atualiza modelo
operacional nem treina com a resposta do próprio período futuro. Misturar
horizontes, modelos, unidades ou fontes é bloqueado. Entradas BACKTEST ficam
rotuladas BACKTEST e não servem de comprovação LIVE.

### Histórico via DuckDB

A leitura é local e somente de arquivos Parquet dentro de uma raiz
explicitamente autorizada, sem SQL arbitrário do usuário, symlinks ou
caminho escapando da raiz. O limite de arquivo, tamanho e linhas é aplicado
antes de converter cada linha ao contrato canônico `historico.Observacao`.
A consulta exige fonte/variável/produto/região/unidade, e a visão temporal
respeita publicação e coleta. O hash do Parquet é verificado antes e depois
da consulta para diminuir risco de alteração durante leitura. **Esse código
não transforma arquivo desconhecido em fonte oficial**, não habilita coleta
remota nem redistribuição comercial.

## Gaps para habilitação operacional

1. Validar e registrar licenças de uso das séries reais, armazenamento,
   derivação, treinamento e eventual comercialização.
2. Integrar as fontes canônicas de soja, milho, boi, diesel, frete, hidrologia
   e clima com unidades, competência, referência, publicação e coleta.
3. Usar backtests históricos realmente reproduzíveis por safra, município e
   regime climático; exigir ganho fora de amostra frente a naive/StatsForecast.
4. Calibrar intervalos de incerteza e cenário de drift, não utilizar
   apenas MAE; testar sensibilidade a atrasos e correções das fontes.
5. Integração externa ao Hermes/Knowledge Factory para auditoria, retenção,
   rollback e aprovação de qualquer versão de modelo, sem escrita canônica
   direta por agente.
6. Executar testes reais dos extras e testes E2E em nuvem com quotas e recursos
   gratuitos comprovados. Manter notebook apenas terminal de supervisão.

**Do not claim:** biblioteca opcional instalada, IA conversacional ativa,
aprendizado de pesos LLM, previsão real, licença de dados autorizada,
backfill operacional, cobertura probabilística garantida ou produção.
