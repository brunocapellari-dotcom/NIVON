# NIVON — Reteste independente da logística (21/10/2026)

**PR de implementação:** #18 (`feat/logistica-fretes-diesel-corredores-20261020`)  
**SHA funcional congelado:** `d78e5618e81b28b4f1d17a5815775bea20b167bd`  
**PR independente:** #43 (`audit/reteste-fretes-atual-20261021`)  
**Commit do teste:** `33609b6b400545bd8e6d040118952f3eb2fd72b5`  
**Evidência CI:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39598605955

## Resultado

`Ran 1266 tests in 1.353s — FAILED (failures=2, errors=1, skipped=5)`.

Os seis testes da auditoria #33 foram portados para o SHA atualizado da PR #18. A única adaptação funcional da fixture foi acrescentar os campos **atestado de atualidade comercial no conteúdo original** e **data de referência comercial** (2026-10-20) à resolução sintética, cobrindo-os pela assinatura HMAC independente. Nenhuma expectativa de teste foi enfraquecida.

| Não conformidade | Nível | Resultado no SHA de 21/10 |
|---|---|---|
| NC-AUD-012 | P0 | **FAIL**: deduplicação cross-source sem evidência de identidade global comprovada retorna 1 registro em vez de 2 |
| NC-AUD-013 | P0 | **FAIL**: `oferta_id` colide entre `PROVEDOR-A` e `PROVEDOR-B` com `event_id` idêntico no mesmo tenant; origem do provider ainda não participa do namespace HMAC |
| NC-AUD-014 | P1 | **ERROR**: evento de 19/10 às 22h UTC-12 = 20/10 às 10h UTC e 06h em Cuiabá; validado inicialmente com fuso correto, mas `OfertaFrete.__post_init__` recusa como `referência futura à publicação` pela comparação de dias em zonas diferentes |

**Controles positivos GREEN:** republicação da mesma oferta/fonte deduplicada; separação entre tenants; valores individualizados por estabelecimento (sem média municipal). O suite não acessa WhatsApp real, banco produtivo, serviços ou segredos.

## Correções necessárias

1. Definir contrato de identidade global de ofertas: `tenant/provider/event_id` ou ID externo reconciliado com prova assinada; não assumir que `event_id` é global entre provedores.
2. `consolidar_ofertas` não deve fundir fontes diferentes sob o mesmo `oferta_id` sem vínculo explícito e evidência auditável. Manter as contagens de comunicações, registros divulgados e embarques distintos.
3. Normalizar datas comerciais por `America/Cuiaba` antes de comparar com a data da publicação, preservando instantâneo UTC e `data_publicacao` original para auditoria.
4. Validar a alteração com todos os seis testes, além da integração WhatsApp AI → atestação dupla → oferta → deduplicação → painel individual. Provar permissões reais antes de uso vivo.
5. A PR #18 tem alterações em andamento; exigir SHA final único e CI red-to-green na PR de auditoria antes de declarar NC sanadas.

**Decisão:** REPROVADO para integração / go-live. Esta PR altera somente teste e documentação independente.
