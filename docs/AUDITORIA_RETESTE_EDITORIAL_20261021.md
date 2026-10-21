# NIVON — Reteste independente da pré-homologação editorial

**Data:** 2026-10-21 (America/Cuiaba)  
**PR de implementação:** #26 — `feat/editorial-preflight-homologacao-20261020`  
**SHA da base efetivamente testada:** `15bd85044aa5492bd57dac46ff1fd5f615186698`  
**PR independente:** #45 — `audit/reteste-editorial-atual-20261021`  
**SHA de teste original:** `99d71c9065161204e4878fb6484282ff52885ed0`  
**Teste refinado:** `111e3299e36f4c954ea8cf94606835a409e12209`  
**CI:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39599276804

## Resultado do reteste

`Ran 1067 tests ... FAILED (failures=5)`.

| NC | Severidade | Resultado do teste no SHA congelado | Observação |
|---|---|---|---|
| NC-AUD-006 | P0 original | **GREEN no cenário sintético** | O caso de cotação de 90 dias foi rejeitado pelo preflight com bloqueio atribuído a `COTACAO_0` e indicação relacionada à sessão/atualidade/publicação; ainda **não** é prova de calendário externo real nem resolução completa do risco |
| NC-AUD-007 | P0 | **FAIL** | Anúncio de frete de 2024, com renderização e hash atualizados coerentemente, ainda é admitido como registro corrente |
| NC-AUD-008 | P1 | **FAIL** | Sessão com referência 19/10 às 23h30 UTC-03, publicada depois da referência, é rejeitada por data UTC/compensação temporal |
| NC-AUD-009 | P0 | **FAIL** | Volume `OBSERVADO` e `volume_realizado=True` são autodeclarados sem comprovante operacional separado e passam |
| NC-AUD-010 | P0 | **FAIL** | Cotação declarada publicada às 16h apesar de fechamento referenciado às 17h é admitida |
| NC-AUD-011 | P0 | **FAIL** | Frete declarado publicado às 10h com referência às 11h é admitido |

**Controle positivo:** pacote editorial coerente é considerado apto **somente à revisão offline** (passou). A versão nova usa linha comercial auditável por estabelecimento, `pickup_entity_id`, transportadora, produto e condições; os testes atualizam a linha canônica via `formatar_linha_frete`, recalculando SHA do texto. Logo as cinco falhas não são consequência do formato antigo do boletim.

Os cenários são 100% sintéticos, sem entrada/saída WhatsApp, contratação, rede ou autorização de publicação.

## Limites e critérios

- O cenário GREEN de NC-AUD-006 verifica somente a fixture, não atesta independência do calendário de bolsa, direitos de redistribuição, disponibilidade histórica da fonte nem fechamento verdadeiro. Para marcar o risco como corrigido é necessário testar prova externa (incluindo feriados, mudança de horário de verão, sessões omitidas e falha de dados).
- Preservar timestamps de **publicação original**, **referência**, **coleta** e **geração**; não considerar coleta recente como validação de preço antigo.
- Frete anunciado individual nunca deve ser tratado como cotação negociada ou viagem/volume realizado; jamais calcular média municipal de frete.
- Rejeitar causalidade impossível `publicado_em < referencia_em` para observação que se apresenta como fechamento realizado, exceto contrato de previsão explicitamente separado e rotulado.
- A PR #26 foi modificada após o SHA inicial, e a auditoria permanece isolada. É necessária repetição sobre o SHA de integração final, não somente CI verde na branch responsável.

**Parecer:** REPROVADO para promoção do gate editorial e envio automático. Cinco casos adversariais permanecem vermelhos; nenhum envio real foi executado.
