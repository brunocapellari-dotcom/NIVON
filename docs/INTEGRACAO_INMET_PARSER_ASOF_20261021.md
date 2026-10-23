# NIVON — piloto de compatibilidade INMET horário → verificação de chuva
Data: 21/10/2026 · integração offline, sem dados reais.

## Decisão de integração

A branch `integration/meteo-hidro-inmet-intervalos-20261021` nasce do commit
`a99508dd5447fc55e14bd7bac7664c846858c63b` da PR #19.
Foram trazidos **exatamente os mesmos blobs de Git** da PR #9,
`src/nivon/inmet_horario_qc.py` (blob `64badd163aecd919720ea772e9caf7a278b970f3`)
e `tests/test_inmet_horario_qc.py`
(blob `cd6e0fdc9459bd8a990debc0e66a7a77ba9f519a`).
Isso representa integração de origem, não uma nova implementação paralela.
A PR #9 continua em draft e a integração não deve ser aplicada duas vezes
quando a integração central trouxer aquela frente.

## Ensaio de contrato ponta a ponta

`tests/test_integracao_parser_inmet_chuva_asof.py` alimenta a sequência real de código:

1. `extrair_horarios_inmet(csv_bytes=..., estacao_esperada="A904", ano_esperado=2025)`: 720 medições de 30 dias **inteiramente sintéticas** geradas no teste, sem HTTP. O parser exige cabeçalho INMET e metadado WMO compatível.
2. `agregar_dias_inmet(..., convencao_intervalo_chuva_confirmada=True, referencia_convencao="CONVENCAO_HORARIA_SINTETICA_NAO_OFICIAL")`: 30 acumulados, cada um com 24 horas. Isto é evidência **sintética declarada**, nunca uma confirmação de convenção de estação real.
3. `converter_dia_inmet_para_snapshot`: relatório QC sintético JSON por dia, dependente de `raw_csv_sha256`, convenção `FIM_INTERVALO` e data de validação/publicação/coleta. O acumulado rotulado `D` cobre `D-1 23:00 UTC → D 23:00 UTC`, não `D 00:00 → D+1 00:00 UTC`.
4. `montar_e_verificar_pares_chuva`: 30 previsões NWP ensemble sintéticas para os mesmos intervalos, capturadas antes do início do acumulado, com baseline existente na emissão. Confere SHAs dos pacotes, vigência, QC declarado e identidade de estação/produto.
5. `verificar_chuva_ensemble_asof`: calcula CRPS, Brier, MAE, RMSE e viés em 30 pares. **Ensemble perfeito sintético** dá erros zero, sem comprovar desempenho preditivo real.

Regressões adicionais: chuva horária ausente, hora ausente, falta de convenção, diferença física INÍCIO/FIM e previsão com fuso ausente.

## Gates e dependências

- Todos os coletores, datasets, publicação de previsões e homologação continuam OFF.
- Este teste **não comprova** que relatório QC autodeclarado seja genuíno, que snapshots de forecast tenham existido historicamente nem que os direitos de uso permitam operações. O valor `APROVADO` em fixture não confere autorização instrumental real.
- Coletar e preservar RAW da estação e da previsão real somente com permissão específica de coleta, armazenamento e pesquisa, e evidências externas de publicação/disponibilidade.
- A PR #11 contém o módulo MJO/RMM e permanece isolada; não transformar índice RMM histórico em previsão de chuva local sem modelagem e validação OOS.
- A integração da PR #9 na branch central exigirá reconciliação com esta PR: as árvores carregam exatamente os blobs originais, mas a estratégia final de merge deve impedir regressão ou duplicação de origem.

## Aceitação

GitHub Actions da nova PR contra PR #19, com suíte de regressão sintética,
deve retornar sucesso para o **SHA final** antes de qualquer merge.
Testes ignorados para inspeções externas não são aprovação da ingestão real.
