# NIVON — Auditoria independente de identidade e proveniência de fretes
**Data da rodada:** 2026-10-21 (America/Cuiaba)  
**Escopo:** PR #18 (`feat/logistica-fretes-diesel-corredores-20261020`), derivada inicialmente do SHA `70485d4acc4109596454291c093c611bb97b0f31`; o contrato de atestação evoluiu durante a análise.  
**PR auditor independente:** #33 (`audit/fretes-identity-provenance-20261021`).  
**SHA do reteste independente:** `8d0a77ff1c3aa6fe046c4d9385d8b097470efa2a`.  
**CI evidência:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39591236588  
**Resultado:** 1208 testes, 2 falhas de asserção, 1 erro controlado, 5 skipped. Os três controles independentes passaram.  
**Estado:** REPROVADO para incorporação ao fluxo comercial / uso real. Nenhum teste usa WhatsApp real, rede, credencial ou dados privados.

## Falhas reproduzidas

| ID | Severidade | Evidência reproduzida | Requisito de correção |
|---|---|---|---|
| NC-AUD-012 | P0 | `consolidar_ofertas` devolve **1** registro deduplicado para duas fontes diferentes com mesmo `oferta_id`, identidade comercial e preço, mas sem atestado de identidade global entre fontes (`1 != 2`) | Não deduplicar fontes distintas sem comprovante canônico de equivalência entre ofertas; incluir escopo da fonte no identificador comercial, ou rejeitar colisão enquanto não houver vínculo verificado |
| NC-AUD-013 | P0 | Dois provedores distintos no mesmo tenant podem emitir o mesmo `event_id`; `adaptar_evento_whatsapp` gera a **mesma** `oferta_id` e `registro_id` pseudonimizados, pois a função HMAC não incorpora `provider` nesses IDs | Incorporar namespace de provedor autorizado aos IDs pseudonimizados ou exigir IDs globalmente únicos comprovados; manter segregação de fonte e tenant |
| NC-AUD-014 | P1 | Evento de 19/10 às 22:00 UTC-12 equivale a 20/10 às 06:00 America/Cuiaba, mas `OfertaFrete.__post_init__` compara `data_referencia` Cuiabá com `data_publicacao.date()` no fuso original e recusa `referência futura à publicação` | Comparar data civil sob o mesmo fuso canônico ou validar instantes em UTC e manter referência local explícita |

Os testes exigem que a origem comercial permaneça por estabelecimento, transportadora, descarga, produto, veículo e regime. **Médias de frete por município continuam expressamente proibidas**. Valores anunciados não viram preços negociados ou cargas realizadas.

## Controles positivos e delimitações

- Republicação comprovadamente da mesma `oferta_id` e da mesma fonte permanece deduplicada.
- Dois tenants distintos preservam chaves de oferta diferentes.
- Preços e estabelecimentos diferentes no mesmo município continuam individuais; contagem de pontos permanece correta.
- Assinaturas sintéticas das atestações `DIREITOS` e `RESOLUCAO` são recalculadas nos testes, com emissores e chaves diferentes. Hash/HMAC sintético prova somente lógica de integridade interna, nunca direitos reais de uso nem consentimento.
- A primeira execução de #33 sobre branch-base em alteração encontrou 41 errors por introdução das novas entradas obrigatórias `chaves_atestacao`/`emissores_atestacao` enquanto os testes existentes ainda estavam no contrato anterior. Após atualizar os testes **independentes** para o novo contrato, o reteste isolou os três achados acima; não atribuir as 41 falhas anteriores a defeitos funcionais de WhatsApp.
- A PR #18 continuou avançando, incluindo atualização posterior de testes de atestação. A promoção deve ser julgada em um único SHA consolidado; o sucesso de uma suíte em SHA diferente não reclassifica estes achados.

## Recomendações e sequência

1. **Logística/WhatsApp AI:** corrigir namespace de IDs HMAC e deduplicação cross-provider/cross-source; definir prova de identidade canônica entre fontes e regra fail-closed para alias/colisão.
2. **Engenharia de dados:** padronizar temporalidade de mensagens e `data_referencia` America/Cuiaba sem comparar calendários de timezones diferentes.
3. **Auditoria independente:** manter sem alterações as expectativas dos seis testes em `tests/test_auditoria_independente_fretes_identidade.py` e verificar RED antes da correção / GREEN após ajuste em SHA atualizado.
4. **Direção técnica:** reconciliar PR #18 com PRs #13, #26 e #33 sem apagar identidade individual de fonte/transportadora/estabelecimento.
5. **Homologação operacional:** exigir evidência real licenciada/consentida e E2E da cadeia de raw autorizada a indicador/briefing com backup, segurança e critérios de revogação. Sem isso o componente permanece offline e não homologado.

**Decisão atual:** P0 abertos, merge e go-live não aprovados. A auditoria não altera a produção; as correções devem ser feitas pela frente responsável.
