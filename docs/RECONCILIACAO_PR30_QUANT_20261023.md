# NIVON — Reconciliação auditada PR #30 → PR #20

**Corte:** 23/10/2026. Somente código e testes offline, sem merge na main, deploy, coleta real ou custos.

## Ancestrais e resolução de conflitos

- Ancestral comum: `7284eeb91aef439437477011328fca703f7a2518`.
- HEAD de PR #30 integrado: `8b351202e9ead030dd862dd45e8e6afd86ecc378`.
- HEAD Quant de origem: `3dab63464759a7d97c56bd9e5b016f764c9b35be`.
- Merge real de dois pais: `c04ff66f48e03bfbc6890630b51bfc8aab60e84d`.
- **140 caminhos** alterados na PR #30: **87 blobs já idênticos**, **39 arquivos seguros incorporados pelos SHA originais**, **14 conflitos explicitamente revisados**. GitHub Compare PR #30→Quant: **behind=0**.
- O merge preservou as versões modernas de Quant para regras C81 de cultura, números ambíguos SIDRA, teste de PAM, avaliações quantitativas, configuração de indicadores e documentação. A versão de registro de módulos, matriz de indicadores e arquivo de motores foi estendida posteriormente para incluir o motor de chuva areal nas frentes METEOROLOGIA, HIDROLOGIA e CLIMA_HIDRO, com a respectiva allowlist de importação.
- `src/nivon/briefing_composto.py` ganhou a regra de frescor por seção da PR #30, mantendo o gate de direitos, a validação de fretes anunciados e a não entrega automática.
- `.github/workflows/testes.yml` manteve os ensaios sintéticos PTAX e agregou um novo ensaio Fretes, ambos somente na etapa central; nenhum job de coleta externa foi ativado.
- O conflito `src/nivon/tendencias_mercados.py` não foi resolvido por sobrescrita: a API pública R01 foi reconciliada com o contrato de painel multi-par da PR #30 e o modo antigo do mesmo estabelecimento foi isolado.

### Lista dos 14 conflitos

1. `.github/workflows/testes.yml` — preservar PTAX E2E e acrescentar Fretes E2E.
2. `config/matriz_produtos_indicadores.v1.json` — preservar Quant, acrescer quatro indicadores areais da PR #30.
3. `config/motores_inteligencia.v1.json` — preservar Quant, incluir motor areal em três frentes.
4. `src/nivon/briefing_composto.py` — combinar frescor por seção, corredor e direitos existentes.
5. `src/nivon/registro_motores.py` — adicionar `chuva_areal_ensemble` à allowlist.
6. `config/catalogo_tecnico_historico.v1.json` — manter alerta de código C81 incorreto e bloqueio de dados sem verificação real.
7. `docs/BASE_CIENTIFICA_E_HISTORICA_20261019.md` — manter documentação Quant estendida.
8. `docs/MOTOR_CENTRAL_TENDENCIAS.md` — manter documentação Quant estendida.
9. `src/nivon/agregacao_pam_ibge.py` — conservar guarda C81 de cultura.
10. `src/nivon/composicao_pam_sidra.py` — conservar guarda C81 e bloqueio de precisão ambígua.
11. `src/nivon/tendencias_mercados.py` — API unificada R01 com motor estatístico pareado.
12. `tests/test_agregacao_pam_ibge.py` — manter testes Quant ampliados.
13. `tests/test_composicao_pam_sidra.py` — manter testes Quant ampliados.
14. `tests/test_tendencias_mercados.py` — manter regressões Quant; adicionar `test_r01_reconciliacao_pr30_quant.py` para o contrato da PR #30.

## Interfaces conciliadas

`tendencias_mercados.tendencia_frete_anunciado` usa **PAINEL_PAREADO_ESTABELECIMENTO_TRANSPORTADORA** quando não há IDs individuais de um só par, delegando o cálculo ao motor `fretes_tendencia_pareada.tendencia_frete_pareado`. Se ambos `pickup_entity_id` e `transportadora_id` estão informados, preserva o contrato legado **LEGADO_LOTES_INTRAPAR_ISOLADO**, sem interpretação como tendência municipal. Informar só um deles falha.

A ponte `fretes_integracao_r01.tendencia_ofertas_pareadas` e o lote `pipeline_fretes_quant.executar_lote_fretes_quant` agora usam essa API única. Todos os modos exigem comparabilidade comercial, separação PF/PJ e de descarga, nunca média municipal, sem estimar frete contratado/realizado.

## CI e evidência verificável

- [Actions #39945812319](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945812319): **SUCCESS**, 1.778 testes, 0 falhas, 5 skipped. Corrigido antes o gate de registro de chuva areal detectado por CI.
- [Actions #39946033578](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946033578): **SUCCESS**, 1.778 testes, 0 falhas, 5 skipped, mais **10 etapas PTAX E2E** (RAW/backup/restauração/visão reversa) e **10 etapas Fretes E2E** (28 divulgações de teste, 4 séries econômicas por par, 2 painéis R01, 28 recibos HMAC, bloqueio por RAW adulterado).
- Todas as séries são sintéticas; ambos os scripts registram `publicavel=false`.

## Gates restantes

**P0:** revisão do integrador antes de eventual merge em `main`; PR #20 e PR #30 continuam `draft`, e issue #25 aberta enquanto não há aceitação na base definitiva. **P1:** prova semântica independente do conteúdo RAW, direitos/licenças, calendário oficial, vintages históricos e validação prequential/holdout com dados reais. **P1:** eventual deploy/observabilidade da infraestrutura integrada, sujeito a credenciais, orçamento e autorização. Nenhuma dessas ações foi feita neste ciclo.
