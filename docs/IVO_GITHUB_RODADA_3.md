# IVO — Terceira rodada de pesquisa GitHub e treinamento histórico

**Data-base:** 20/10/2026. **Estado:** laboratório offline em revisão, não homologado para previsão operacional. **Sem deploy, assinaturas, rede, runners próprios ou contratação.**

## Achado técnico principal

A primeira necessidade do IVO não é trocar de LLM, mas possuir um **laboratório reprodutível de aprendizado temporal** que só use informação conhecida no instante da emissão e meça se o modelo proposto teria superado uma referência simples. O NIVON já mantinha `historico.Observacao`, `visao_na_data`, o registro de previsões e um monitor de erros. Esta rodada conectou essas peças.

### Código implementado

- `src/nivon/ivo_lab_temporal.py`: treina um **blend com peso estimado empiricamente** sobre observações mensais elegíveis. O alvo é determinado no início do mês seguinte, com características *as-of*: referência sazonal exatamente 12 meses antes e última observação conhecida em no máximo 3 meses. O peso é ajustado por mínimos quadrados regularizados e limitado a [0,1]. Os rótulos de treinamento só entram depois de publicados e coletados. Cada vetor histórico é reconstituído com as revisões que já eram conhecidas na data da previsão correspondente. O treino guarda checksum e primeiro/último período de amostra.
- `walkforward_asof`: repete esse procedimento por meses-alvo, sem misturar fatos futuros ao treinamento de cada fold. Marca previsão como `BACKTEST_OFFLINE_NAO_HOMOLOGADO`; compara erro médio absoluto da mistura com referência sazonal. Observações não publicadas até a data de avaliação não são convertidas em sucesso.
- `src/nivon/ivo_lab_ledger.py`: integra resultados de **fixtures sintéticas confirmadas** ao ledger histórico já existente, criando registros com modo `BACKTEST`. Exige duas confirmações explícitas (`autorizado=True` e `fixture_sintetica_confirmada=True`). Rejeita previsões duplicadas, alterações de evidência e data de coleta posterior à emissão. Não permite converter backtest em `LIVE`.
- `tests/test_ivo_lab_temporal.py` e `tests/test_ivo_lab_ledger.py`: provas sintéticas do pipeline, de não utilização de revisões futuras, recusa de dados coletados tarde, diferenças entre treino e teste, desempenho do baseline, integridade e idempotência.

**Limitações metodológicas importantes:**
1. O candidato é um modelo estatístico simples, **não uma rede neural ou foundation model retreinada**, e usa apenas uma variável. Não prediz automaticamente clima, produtividade ou preços.
2. Uma observação histórica cuja coleta real ocorreu depois do corte não vira observação disponível antes do corte apenas porque seu período se refere ao passado.
3. Os resultados do walk-forward não substituem testes com dados reais homologados, intervalos de confiança calibrados, incerteza e avaliação por sazonalidade/região/cultura. Amostras insuficientes bloqueiam a execução.
4. O modo `BACKTEST` é uma reconstrução; jamais alegar que o modelo antecipou o resultado na época sem evidência de emissão `LIVE` imutável.
5. O laboratório e a ponte não agendam treinamento, ingestão, envio, atualização de conhecimento canônico ou promoção automática de modelos.

## Nova pesquisa GitHub

Componentes adicionais inseridos em `config/ivo_ferramentas_github.v1.json`, com repositórios e licenças de código examinadas:
- [HierarchicalForecast](https://github.com/Nixtla/hierarchicalforecast), Apache-2.0 — **prioridade alta** para conciliar previsões por Brasil, estado e município, além de desdobramentos de culturas, desde que a hierarquia de agregação seja compatível. Não somar milho total novamente às suas três safras.
- [sktime](https://github.com/sktime/sktime), BSD-3-Clause — laboratório de séries temporais, requer comparação com StatsForecast.
- [GluonTS](https://github.com/awslabs/gluonts), Apache-2.0 — comparação de modelos probabilísticos sob controle de custo e versões.
- [Polars](https://github.com/pola-rs/polars), MIT — processamento eficiente de históricos locais e Parquet.
- [sqlite-vec](https://github.com/asg017/sqlite-vec), dupla licença MIT/Apache-2.0 — pesquisa semântica local sem servidor vetorial dedicado; auditar extensão nativa, binaries, embeddings e custos.
- [eo-learn](https://github.com/sentinel-hub/eo-learn), MIT — séries temporais de vegetação e sensoriamento remoto. **A ferramenta não fornece imagens/licenças gratuitas por si só.**
- [PyETo](https://github.com/woodcrafty/PyETo), licença permissiva tipo BSD — referenciais de evapotranspiração FAO-56; requer meteorologia e calibração agronômica.
- [causal-learn](https://github.com/py-why/causal-learn), MIT — gerar hipóteses de relações causais, nunca confirmar causalidade automaticamente.
- [XGBoost](https://github.com/dmlc/xgboost), Apache-2.0 — regressão tabular para análise de rendimento, custos e fluxos; só adotar com baselines, split temporal, custo e qualidade comprovados.

**Não instalados.** Direitos de código não equivalem a direitos de dados, pesos, imagens, APIs ou comercialização. No nível de custo zero, priorizar bibliotecas sem exigência de servidor, GPU ou serviço pago.

## Próximo gate operacional

1. Adquirir histórico verdadeiro com licenças e datas de publicação/coleta preservadas.
2. Testar baseline e pesos em conjuntos por cultura, variável, safra/calendário, região e horizonte; nunca usar projeção como variável observada.
3. Adicionar avaliação estatística mais forte (intervalos e calibração probabilística, cobertura por regime, número de folds, perdas assimétricas e incerteza).
4. Implementar treinamento supervisionado de ML opcional por adaptadores versionados e *feature store* as-of, com reproduzibilidade, sandbox, benchmark e auditoria independente via Hermes.
5. Conectar Knowledge Factory/Segundo Cérebro e interface IVO para citar os fundamentos teóricos e rastrear eventos comparáveis do passado, sem confundir mecanismo econômico hipotético e causalidade demonstrada.
6. Homologar persistência, recuperação/backup, limite de custos e periodicidade em nuvem antes de qualquer operação autônoma.

Código versionado continua numa branch de PR e precisa passar os testes no SHA atualizado, após conciliação com a base principal em desenvolvimento paralelo.
