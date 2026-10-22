# NIVON — R09 | Recibos canônicos e webhook transacional

**Ciclo:** 09, 21/10/2026. **Estado:** implementação de teste em PR #110 DRAFT; nada em produção, sem deploy/POST real ou alterações em `main`.
**Base:** PR #95 @ `56ed88d6e83bbe5d893be9cf248094dfb7b3715b`.

## Lacuna encontrada na PR #95

A PR #95 unificou a **decisão de reservar** dia+destinatário e exigiu consentimento HMAC. Entretanto, o estado de entrega ainda era registrado em duas tabelas independentes (`briefing_outbox` e `nivon_envios`), com dois adaptadores assinados e WSGI atendendo apenas a outbox do briefing. Uma mensagem com ACK ou webhook poderia aparecer em uma tabela, sem recibo canônico e sem alcançar a outra rota.

## Alterações técnicas

1. **`src/nivon/outbox_recibos.py`:** novas tabelas `nivon_recibos_canonicos` e `nivon_eventos_recibo`; chave de reserva por dia e HMAC destinatário; **UNIQUE `provider_message_id`**; registro de aceite, envio, entrega, leitura e falha; eventos de mudança sem duplicata por provedor+estado; monotonicidade de estados e veto a `failed` após entrega ou leitura. Não contém texto, telefone, nem token. `ACEITO_PROVEDOR` não é `ENTREGUE`; `read` fora de ordem também não inventa timestamp de `delivered`.
2. **`src/nivon/outbox_briefing.py`:** o ACK e a promoção a entregue atualizam registro legado e canônico na **mesma transação `BEGIN IMMEDIATE`**. Colisões de provider ID são tratadas como erro de domínio, com rollback da transação, não erro SQLite exposto; recusas de duplicatas preservadas.
3. **`src/nivon/outbox_whatsapp.py`:** ACK do remetente sintético, conciliação manual após timeout e `sent`/`delivered`/`read`/`failed` de webhook assinado atualizam as duas tabelas na mesma transação. IDs desconhecidos são ignorados sem atribuição a destinatário; eventos fora de ordem não rebaixam estado.
4. **`src/nivon/webhook_recibos_unificados.py` + `webhook_wsgi.py`:** mesma rota WSGI do WhatsApp agora **verifica assinatura Meta**, valida todos os campos do lote antes de mudar estado e executa um único commit para ambos os canais. Eventos `delivered` do canal BRIEFING confirmam entrega somente após `ACCEPTED`; `sent`/`read` do briefing NÃO comprovam entrega. No canal WHATSAPP estados são distintos e monotônicos. Qualquer evento malformado cancela o lote inteiro.
5. As APIs legadas de consumo continuam para compatibilidade, mas o registro canônico passa a documentar explicitamente a semântica comum. Esta é uma etapa de migração: **não elimina** as tabelas legadas. Webhook WSGI ainda depende de configuração restrita de caminho, reverse proxy e autenticação independente do ambiente.

## Testes e evidência

- Primeiro CI após as implementações do ledger central: [GitHub Actions núcleo #39698658858](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698658858): **2.056 testes, 0 falhas, 3 skips**. Pipeline independente [#39698658747](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698658747): **2.056 testes, 0 falhas, 35 skips**.
- Foram acrescentados testes para duplicação de provider ID entre destinatários, adulteração/removal do registro canônico e revogação após ACK, além de múltiplos recibos em um lote WSGI e rollback total ante status Meta inválido.
- Um dos CIs intermediários detectou `sqlite3.IntegrityError` cru em provider ID duplicado. A proteção UNIQUE funcionava; agora o adaptador converte para erro de domínio e garante rollback.
- Resultado final **deverá ser confirmado no HEAD posterior a esta documentação**; não converter CI intermediário em certificação de implantação.

## Limites não resolvidos

- **Confiabilidade da autoridade externa:** o valor de `autenticado=True` em APIs legadas não substitui assinatura real Meta; a entrada WSGI assina os bytes brutos, mas outras chamadas Python ainda podem ser feitas por código autorizado. Restringir interface e implementar token/identidade de serviço na camada externa antes da produção.
- **Dois consumidores sobre o mesmo provedor:** não executar WSGI atual e consumer legado simultaneamente em bancos diferentes; a implantação exige **um banco durável físico e caminho único** (ou Postgres transacional), migração dos envios existentes sem duplicatas e reconciliação de backups.
- **Webhook de outro WABA/conta:** a assinatura Meta não identifica por si só um tenant interno; vincular WABA, phone number ID, app e opt-in a identidades confiáveis, impedindo colisão entre aplicações, antes de liberar qualquer evento real.
- **Resiliência a adversários:** testes incluíram assinaturas inválidas, lote parcialmente inválido, duplicação e IDs estranhos. Faltam rate limiting/proxy, proteção contra payload malicioso complexamente aninhado, temporização, deserialização e replay persistente entre réplicas.
- **Consentimento e privacidade:** autorização HMAC sintética nos testes, não prova de opt-in real; confirmar direitos e política LGPD/Meta, retenção e revogação nas integrações; reconciliar corrida opt-out↔POST e proibir retry após timeout.
- **Egress e governança:** nenhum transporte real foi habilitado. `main` avançou independentemente com PR #87 de fontes hidrometeorológicas; sua reconciliação de 13 arquivos ainda está pendente e deverá ocorrer em PR própria, sem atropelar a cadeia de integração existente.
- **Autonomia:** não enviar, fazer deploy, rodar cron, treinar modelos ou publicar dados automaticamente.

**Próxima frente recomendada:** migrar e verificar estados legados já existentes em banco compartilhado, com reporte de inconsistências e rotina de backup/recovery; manter o controle humano para ativar produção.
