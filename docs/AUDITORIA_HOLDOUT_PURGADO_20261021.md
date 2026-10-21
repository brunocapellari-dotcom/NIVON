# NIVON — Auditoria do holdout temporal purgado (21/10/2026)

## Problema
MAE/RMSE e Brier calculados em folds OOS não garantem independência. Num horizonte de cinco sessões, previsões emitidas em dias consecutivos compartilham a maior parte do período previsto; comparações ingênuas podem superestimar amostra e confiança. Além disso, um holdout escolhido depois de treinar/escolher parâmetros pode estar contaminado, mesmo que suas métricas pareçam boas.

## Entrega `auditoria_holdout_quant.py`

`avaliar_holdout_temporal_purgado` recebe as mesmas séries homogêneas e metadados as-of de `quant_core.avaliar_previsoes_oos`. Primeiro reusa o validador estrito de horário/fonte, série, baseline, unidade, horizonte, verdade maturada e edições SHA; depois:

1. Ordena por origem do calendário e exige ordem crescente de emissão para evitar registros backfill incoerentes.
2. Reserva os últimos `n_holdout` forecasts emitidos como holdout retrospectivo.
3. Exclui do conjunto histórico de treino/calibração **qualquer** previsão cujo resultado não estava coletado antes da *primeira emissão holdout*. Exige adicionalmente embargo de no mínimo uma sessão entre o alvo do histórico e a primeira origem holdout.
4. Usa o índice de origem módulo horizonte para formar **fases de previsões com janelas-alvo sem sobreposição no calendário declarado**. Mede MAE/RMSE versus o mesmo baseline em *cada* fase e exige mínimo amostral por fase.
5. Só retorna `SINAL_DESCRITIVO_HOLDOUT_NAO_HOMOLOGADO` quando todas as fases observadas têm ganhos positivos em MAE e RMSE. Caso contrário: `SEM_SUPERIORIDADE_ROBUSTA_AO_BASELINE` ou status explícito de amostra insuficiente. Nunca retorna `publicavel=True` ou habilita produção.

## Interpretação
A auditoria **não treina nem calibra** modelos; exige que a separação de desenvolvimento/seleção de hiperparâmetros e holdout tenha sido respeitada fora do código. Também não estima significância nem intervalos iid, não corrige automaticamente deriva/regimes e não comprova disponibilidade histórica real ou direito de publicação. A técnica de *fases* controla sobreposição mecânica de horizontes, **não garante independência estatística** entre preços autocorrelacionados.

Sem série real autorizada, vintages brutos/hashes independentes e calendário oficial, os resultados continuam experimentais e não representam previsibilidade de CBOT, preço físico ou fretes.

## Regressões
`tests/test_auditoria_holdout_quant.py` contém testes sintéticos de purga/embargo, histórico imaturo, fases de horizonte 1 e 5, um regime de fracasso em uma fase, baseline superior, input conflitante, emissões retroativas e bloqueios de amostra. Rodar:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_auditoria_holdout_quant.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

**Prioridade de integração:** comparar este resultado com o prequential da PR #21 mantendo a convenção Brier e proveniência de calendário; contratar dados point-in-time e registrar seleção prévia de modelo/holdout sem contaminar o teste. Não incorporar automaticamente ao relatório público.
