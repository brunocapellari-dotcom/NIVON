# IVO — Rodada 4: incerteza verificável, geografia coerente e integração

**Data-base:** 20/10/2026. Implementação em PR de desenvolvimento; sem deploy e sem modelos homologados.

## O que o IVO deve aprender nesta rodada

Um assistente agro não deve apenas produzir um valor esperado. Deve explicar:
- qual era a informação publicada e efetivamente coletada no instante da emissão;
- a que cultura, safra, localidade, unidade, horizonte e versão de modelo se refere;
- quantas previsões anteriores do *mesmo escopo* já possuem resultados publicados;
- como foi construído o intervalo de incerteza, quantos erros reais o calibraram;
- se municípios são uma amostra incompleta, impedindo afirmar total de estado;
- quais relações são somente hipóteses, não causalidade demonstrada.

## Implementação

1. **`ivo_intervalos.py`**: intervalo experimental usando estatística de ordem de erros absolutos, calculada somente com *primeiras publicações* disponíveis antes da emissão de cada nova previsão. Faz corte por fonte, versão do modelo, indicador, localidade, unidade, horizonte, modo LIVE/BACKTEST. Exige histórico mínimo. O índice de quantil segue `ceil((n+1)*nivel_nominal)`. Se o quantil exigido não existir, não inventa faixa. A dependência temporal, revisões, drift e escolha retrospectiva dos modelos impedem garantia de cobertura em produção sem testes adicionais. Não supor que intervalo de 90% tenha cobertura real de 90%.
2. **`ivo_previsao_ledger.py`**: a saída de avaliação agora também carrega fonte da verdade, emissão e registro originais, publicação e registro da observação. Essas datas são necessárias para provar que o rótulo era conhecido antes de ser utilizado na calibração.
3. **`ivo_hierarquias.py`**: bottom-up de métricas *explicitamente aditivas*, com árvore sem ciclos, filhos duplicados ou múltiplos pais. Exige as mesmas unidades, modelo, produto, indicador e calendário. Rejeita somar preços, percentuais, rendimentos e produtividades. Preserva hash de evidência e bloqueia alegações de completude territorial — a lista de municípios é fornecida pelo caller e **não prova** que todos os municípios foram contemplados. Não soma intervalos de cidades, pois seria necessário modelar correlação/covariância entre erros.
4. **Testes**: `test_ivo_intervalos.py`, `test_ivo_hierarquias.py` e `test_ivo_calibracao_e2e.py`; incluindo vazamento temporal, revisões de fontes, quantis, dados insuficientes, dupla contagem e integração laboratório -> ledger -> calibração.

Os componentes são offline, sem rede, sem custo, sem instalar libs e sem autopromover previsões. Não substituem o treinamento de ML com dados históricos reais.

## Pesquisa GitHub complementar

- [HierarchicalForecast](https://github.com/Nixtla/hierarchicalforecast) (Apache-2.0): métodos BottomUp, TopDown, MiddleOut, MinTrace e reconciliação probabilística. Já catalogado no IVO. O módulo nativo testa o primeiro contrato de aditividade antes de adotar biblioteca mais sofisticada.
- [MAPIE](https://github.com/scikit-learn-contrib/MAPIE) (BSD-3-Clause): avaliação futura de métodos conformais e de cobertura, condicionada a backtests independentes e regimes temporais.
- [Conformal Prediction](https://github.com/aangelopoulos/conformal-prediction) (MIT): referência metodológica experimental e limitações de distribuição; não incorporado o código.
- [Frictionless](https://github.com/frictionlessdata/frictionless-py) (MIT): candidata para validação de schemas em dados tabulares oficiais quando superar verificações já existentes no Nivon.
- [pygeoapi](https://github.com/geopython/pygeoapi) (MIT): candidata para futura interface geoespacial com padrões abertos; hospedar API exige revisão de custo, segurança e direitos dos dados.

Bibliotecas com licenças permissivas **não garantem** que modelos, imagens, APIs e dados de terceiros possam ser usados comercialmente. Nenhuma foi instalada.

## O que permanece por executar

- Backfill efetivo com séries observadas, fonte primária e direitos de uso por operação.
- Estruturas territoriais canônicas e auditoria de cobertura geográfica; não inferir soma total de MT ou Brasil a partir de amostra incompleta.
- Benchmark por safra e série contra baseline sazonal/ingênuo, cobertura de intervalos por regime e outros indicadores além de MAE.
- Integração com Hermes/Knowledge Factory para proposição, auditoria e armazenamento de evidências; alterações canônicas somente por processo aprovado.
- Testes com dados reais, validação independente, recuperação e observabilidade cloud, limites de execução gratuitos.
- Interface conversacional do IVO e eventual voz, usando ferramentas estruturadas e proibição de execução não autorizada.

**Garantias não alegadas:** previsão futura certa, aprendizado autônomo de pesos do LLM, confirmação causal, cobertura conformal sob séries temporais dependentes, completude dos municípios e operação em produção.
