# NIVON — Integração da PR #21 de Mercados na PR #20 de Quant

**Data:** 21/10/2026. **Escopo:** desenvolvimento offline, sem merge em
`main`, deploy, coleta de dados, alteração de secrets ou liberação preditiva.

## Estado e reconciliação Git

- Repositório: `brunocapellari-dotcom/NIVON`.
- Branch Quant, PR #20 (draft):
  `feat/quantitativo-validacao-asof-probabilidades-20261020`.
- Origem Mercados, PR #21 (draft):
  `feat/mercados-confiabilidade-tendencias-20261020`.
- Base comum exata: `50fbf9f3072ec0a9bdd567e7ce6a8aac96490f17`,
  PR #12 já reconciliada antes com a PR #20.
- HEAD Quant antes do merge:
  `1e3a61c99bd87e0429cf6fb14775980347926b5e`.
- HEAD Mercados incorporado:
  `981331a446a99f7a1191f8c033b8548c03d21faf`.
- Merge commit de dois pais:
  `f0b31fcfb7ec31f4cdc381ae0775a368a3891536`.

Auditoria pré-merge: PR #21 acrescentava/modificava **31 caminhos** e continha
**63 commits** após a base comum. A comparação de SHA de blobs entre a base,
o HEAD Quant e o HEAD Mercados mostrou **zero conflitos de caminhos**, zero
exclusões no upstream. Cada blob de Mercados alterado foi transportado por
SHA inalterado; a PR #21 permanece aberta em sua própria branch.

Depois do merge, GitHub Compare PR #21 → PR #20 indicou
`ahead=37, behind=0`, com apenas os arquivos próprios de Quant na
diferença. Esse resultado demonstra composição da árvore, **não**
homologação conjunta com Fretes ou integração na main.

## Evidência de CI e teste E2E verdadeiro entre módulos

- [CI do merge, execução #39670833205](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39670833205):
  `validar-nucleo` SUCCESS; **1.479 testes executados, zero falhas,
  cinco skipped**. Inclui os testes já existentes de Mercados e Quant.
- `tests/test_mercados_quant_integracao_e2e.py` chama **de fato** o
  `validacao_tendencias_mercado.avaliar_probabilidades_tendencia` da
  PR #21, passa seu relatório para
  `integracao_contratos_quant.normalizar_relatorio_brier_mercados` da
  PR #20 e confere independentemente, com os mesmos dados **sintéticos**,
  o `quant_core.avaliar_previsoes_oos`.
- [CI com E2E, execução #39671185263](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671185263):
  `validar-nucleo` SUCCESS, **1.485 testes executados, zero falhas,
  cinco skipped**.

### Critérios de interoperabilidade efetivamente testados

1. A convenção multiclasse de Mercados utiliza a **soma de três erros
   quadráticos**: neste fixture Brier = `0.06`.
   Quant utiliza a **soma/3**, Brier = `0.02`. O bridge preserva ambos,
   distingue o benchmark expansivo e conserva `skill` consistente.
2. Mercados avaliou **44 previsões** após o aquecimento prequential;
   Quant avaliou **65 previsões** no exemplo. A igualdade numérica do Brier
   neste fixture decorre da perda idêntica por previsão e **NÃO significa
   que as janelas de avaliação são idênticas**.
3. As classes `ALTA/BAIXA/ESTABILIDADE` foram confrontadas contra
   preços e banda comercial. Calendário ausente, sessão omitida,
   rótulo contraditório, alteração indevida de skill e amostra insuficiente
   falham de modo fechado.
4. O resultado carrega a fonte, o SHA da edição **declarada** e a janela
   do calendário. Em hipótese alguma converte calendário sintético em
   sessão oficialmente verificada, nem `probabilidades_calibradas=None`
   em afirmação de calibração.
5. Todos os artefatos têm `publicavel=False`.

## Limitações e próximos gates

O fixture usa dias corridos marcados como sessões **sintéticas** (não representa
calendário CME real). O SHA é uma string de fixture, não evidência da captura
autêntica; os preços não são históricos reais licenciados. O comparador
prequential de Mercados e a auditoria de holdout temporal de Quant possuem
objetivos, amostras e hipóteses diferentes, e **não** devem ser convertidos
em um único indicador de habilidade sem pré-registro, corte e labels compatíveis.

Próximos P0/P1: integrar um RAW com direitos e parser auditado; verificar
calendário oficial e recibos externos, assegurar vintages e testes com
rótulos maturados; conciliar R01 da PR #30 com identidade comercial
completa (issue #25), preservar SHA/RAW na PR #18 e executar a suíte
integrada de todas as frentes. Não fechar automaticamente esses gates
por CI verde com fixtures.

## Reconciliação incremental — nova auditoria PTAX em Mercados

Após o primeiro merge, a PR #21 evoluiu de
`981331a446a99f7a1191f8c033b8548c03d21faf` para
`3aaba7780174ecf4f89d2c088fb10b901b3e662a` (dois commits). Seu
novo escopo acrescentou exclusivamente
`src/nivon/auditoria_migracao_ptax.py` e
`tests/test_auditoria_migracao_ptax.py`. O cotejo de SHA entre o HEAD
Mercados anterior, o novo HEAD e o Quant integrado confirmou **zero
conflitos**, sem deleções. Ambos foram transportados por blob SHA,
preservando a árvore e ambas as histórias no merge incremental
`fb80e10e5d8cf46419af113b7609c36adbd148ae`.

A PR #21 continua dona de seus coletores e contratos de migração PTAX.
Não há autorização de ingestão real, uso produtivo de PTAX, mudança
de infraestrutura, publicação, deploy ou merge na `main`.
Os testes integrados e a situação das branches devem ser conferidos
no SHA final da PR #20, sem reutilizar evidências de builds anteriores.
