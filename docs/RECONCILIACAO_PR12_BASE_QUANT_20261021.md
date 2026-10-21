# NIVON — Reconciliação técnica PR #12 → PR #20 (21/10/2026)

## Objetivo e proveniência
Sincronizar o motor quantitativo com a base de tendências transversal, sem
perder commits de nenhuma frente nem publicar/ativar novos modelos.

- Repositório: `brunocapellari-dotcom/NIVON`.
- Branch destino, exclusiva Quant: `feat/quantitativo-validacao-asof-probabilidades-20261020`, PR #20 (draft).
- Base compartilhada de origem PR #12: `feat/motor-tendencias-transversal-20261020`.
- Ancestral comum: `3191528d172a142c0208c1de4f33374fbd5cce28`.
- Base incorporada: `50fbf9f3072ec0a9bdd567e7ce6a8aac96490f17`.
- HEAD Quant anterior: `abfc661a1db8461d14dffc0db9d503e25d3dd3ee`.
- Commit de dois pais resultante: `b76bfaa09bf7e9a9e10040906a91181628a2cda2`.

## Auditoria de conflitos
As diferenças a partir do ancestral comum foram recuperadas por GitHub Compare
e inspecionadas por SHA dos blobs nas três árvores.

- A base PR #12 acrescentava/modificava **24 arquivos** em 20 commits.
- A PR #20 continha **13 arquivos exclusivos** da frente quantitativa, em 34 commits.
- **Interseção de caminhos alterados: zero**.
- **Arquivos apagados da base: zero**.
- Cada caminho atualizado na base foi confirmado intocado na PR #20 em relação
  ao ancestral; nenhum blob foi reescrito, editado manualmente ou sobrescrito.
- O novo tree preserva os 13 arquivos Quant e incorpora as 24 alterações upstream
  por seus SHA originais; merge commit com pais [Quant, base].
- Após a reconciliação, GitHub Compare entre PR #12 e PR #20 retornou
  `ahead_by=35`, `behind_by=0`, `status=ahead`, 13 arquivos próprios.

## Escopo upstream efetivamente absorvido

- Registro e contratos de motores e rotas: `config/*`.
- Agricultura PAM/IBGE e composição SIDRA.
- Dinâmica de tendências transversal.
- Ensemble hidrológico por bacia e governança.
- MDIC fertilizantes as-of e modelos de séries MDIC.
- Adapter Hermes, inventário e manuais metodológicos.
- Regressões associadas nos módulos `tests/test_*.py`.

**Não equivale a integração automática de PRs #18, #21, #30, nem correção
de seus bloqueios de frete, autenticidade, fontes reais ou licenciamento.**

## Evidência de execução

- [GitHub Actions do commit de reconciliação #39663768335](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39663768335):
  `validar-nucleo` SUCCESS, comando
  `python -m unittest discover -s tests -v` com `PYTHONPATH=src`,
  **1.289 testes executados, zero falhas, cinco skipped**.
- Os logs confirmam execução dos testes adicionados pela PR #12
  (`test_composicao_pam_sidra`, `test_dinamica_tendencias` e outros),
  além de `test_auditoria_holdout_quant` da PR #20.
- Demais seis jobs de integração opcional/dados externos permaneceram
  SKIPPED. Sem testes reais de ANP/ANTT/CONAB, API live ou direito de uso.

## Gates pendentes
1. O motor R01 da PR #30 ainda tem pareamento sem `descarga_entity_id` e
   `regime`; preservar contrato comercial estrito da PR #18 (issue #25).
2. A PR #18 não propaga um SHA de edição RAW autenticada até o contrato de
   vintages quantitativos; hash textual isolado não comprova origem.
3. Integrar PR #21 depois de reconciliar o domínio, mantendo convenções
   distintas do Brier multiclasse (soma versus soma/3), prova de calendário
   e avaliação prequential sem contaminação de holdout.
4. Fontes licenciadas, vintages independentes, isolamento de treino,
   execução OOS realmente arquivada e homologação seguem em aberto.
5. Ao receber novos commits na base, repetir comparação de ancestrais,
   auditoria por SHA de blob, CI de árvore combinada e revisão de conflitos.

**Estado:** reconciliação técnica dentro da branch Quant, testes offline
aprovados; PR #20 continua draft. Nenhum merge de PR em main, deploy, coleta,
secret ou despesa autorizada nesta atividade.
