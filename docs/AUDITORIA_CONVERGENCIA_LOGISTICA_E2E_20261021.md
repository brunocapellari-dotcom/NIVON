# NIVON — Auditoria E2E de convergência logística R01

**Data:** 2026-10-21 (America/Cuiaba)  
**PR sob avaliação:** [#42](https://github.com/brunocapellari-dotcom/NIVON/pull/42), base funcional fixada em `c4c0acede9c58554bb0bf6bbc97b278cd0f1fa61`.  
**PR de auditoria independente:** [#51](https://github.com/brunocapellari-dotcom/NIVON/pull/51), branch `audit/logistica-convergencia-e2e-20261021`.  
**Commit do teste:** `5ee7f41c6af238a7973cd1636bde0746cfd8387c`.  
**CI original:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604202104  
**Resultado:** `Ran 1415 tests in 3.288s`; `FAILED (failures=3, skipped=5)`. Dos cinco novos testes, dois controles verdes e três adversariais vermelhos.

## Objetivo e metodologia

Verificar se o sucesso dos testes próprios de #42 garante integridade da cadeia de ingestão, com **dois provedores** possuindo identificadores locais reutilizados. A suíte cria eventos sintéticos `FreightEvent`, calcula `hash_evento`, assina resoluções e permissões com **duas chaves HMAC de teste independentes** e executa o adaptador real `adaptar_evento_whatsapp`, seguido do `consolidar_ofertas` e do `preparar_painel_pr30`.

A assinatura HMAC sintética comprova coerência de contrato/teste; não comprova licença, consentimento, titularidade dos grupos, autenticidade externa do RAW ou envio. Não houve acesso a WhatsApp real, rede, banco, nuvem ou contas.

## Resultados reproduzidos

| ID | Severidade | Etapa | Observação direta | Critério de correção |
|---|---|---|---|---|
| NC-AUD-019 | **P0** | evento assinado de dois provedores → `consolidar_ofertas` | Dois anúncios distintos de fontes A e B com `event_id` local igual (mas `source_event_id` diferente) geram **1** registro consolidado onde são esperados **2**; `1 != 2` | Namespace canônico por `tenant_id/provider/event_id`, proibição de dedup cross-provider sem vínculo de RAW/resolução auditada |
| NC-AUD-020 | **P0** | pseudonimização no adaptador WhatsApp | `oferta_id`, `registro_id` e `publicacao_id` colidem entre provedores A/B quando os IDs locais também coincidem; a HMAC atual inclui tenant e identificador, mas **não** provider | Incluir provider no namespace de todos os três tipos, com teste de equivalência atestada e migração compatível dos IDs históricos |
| NC-AUD-021 | **P1** | consolidação determinística de republicações | `consolidar_ofertas([antiga,nova])["registros"] != consolidar_ofertas([nova,antiga])["registros"]`, embora a assinatura econômica e a lista de `publicacoes_origem` sejam idênticas. O registro representativo muda com a ordem do lote | Estabelecer critério estável (por timestamp e IDs com desempate total, conforme contrato editorial); preservar evento original e republicações sem seleção arbitrária |

Os resultados **NC-019 e NC-020** são reproduções E2E integradas das NC-AUD-012/013 da PR #43, e não novas classes conceituais de risco. **NC-021** é nova não conformidade relativa à invariância de ordem, de impacto mais baixo porém relevante à rastreabilidade e à regra de exibir informação vigente. Evitar inflar totais de riscos ao consolidar a matriz.

### Controles verdes

1. Evento sintético individual, com direitos e resolução atestados, gera uma oferta não contratada com proveniência preservada.
2. Ao fornecer os dois registros colididos diretamente ao `preparar_painel_pr30`, o painel recusa `registro_id` duplicado. Isso é comportamento seguro de **um elo posterior**, mas não recupera as observações indevidamente colapsadas por `consolidar_ofertas`.

### Limites / não inferir

- Não calcular média ou preço indicativo municipal de fretes anunciados; somente registros por estabelecimento e transportadora, com contagens distintas de pontos de embarque.
- Não transformar oferta observada em contrato, viagem, carga realizada nem disponibilidade de caminhões.
- Nenhuma publicação ou fonte real foi homologada. Os testes e SHA auditados valem só para a integração branch #42, não para `main`.
- SHA de CI verde da PR #42 não neutraliza o resultado adversarial porque a suíte própria da integração não cobria esses cenários.

## Plano de correção e aceite

1. Equipe de logística/WhatsApp: corrigir chaves HMAC com escopo de provedor, garantir compatibilidade e reidentificação/retrocompatibilidade dos registros existentes sem dupla contagem, atualizar resolução assinada.
2. Engenharia de dados: corrigir assinatura de republicação e controle de `fonte_id` e `oferta_id`, impedindo fusão sem equivalência global comprovada.
3. Definir seleção determinística de versão/publicação com critério de desempate total e trilha por evento.
4. Reexecutar os cinco testes independentes da PR #51; critérios exigem 5/5 verdes, mais suíte completa e zero erros regressivos.
5. Antes de merge, verificar direitos reais, RAW, qualidade da resolução de estabelecimentos, horários, segurança, dedup, integração editorial e CI num SHA único; não usar PRs empilhadas com estados de CI de SHAs divergentes para alegar aprovação.

**Veredito:** **REPROVADO PARA HOMOLOGAÇÃO E PUBLICAÇÃO** (P0). PR #51 permanece em rascunho e contém somente teste e relatório.
