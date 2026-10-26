# Checkpoint #290 — smoke e rollback sem alterações

Branch `codex/290-operation-smoke`, empilhada sobre #287 (`bfc703f`). Base de PR
sugerida: `codex/287-single-private-interface`. Issue #290 consultada aberta.

Entrega: /readyz separado do health e da API, reutilizando leitor/cache; smoke
CLI com gates de leitura/custo, rejeição anônima das três rotas, token em memória,
validação de revisão pronta, tráfego, commit e IAM do serviço. Redirect não é
seguido. Relatório sanitizado. Plano rollback exige revisão anterior Ready e
nunca executa alteração, mesmo com gates aprovados. Documentação de operação.

Validação: 8 testes novos do smoke, 2 testes readiness incluindo SOURCE_LAG real
em HTTP local; suíte completa 772 testes, sem falhas, 2 skips Parquet. Plano no
ambiente atual: BLOCKED, URL/commit/gates ausentes, zero chamadas externas e
zero alterações. Nenhum token foi solicitado para smoke LIVE.

Não é autenticação GCP comprovada, CI remoto ou rollback realizado. Gates de
custo/leitura e endpoint conhecido continuam externos; não foram alterados.
Revisão do IAM herdado depende também do pré-voo #288. Build Docker da #287
continua não validado por trust de CA do proxy. API GitHub Forbidden ainda impede
PR/comentários; este checkpoint é o corpo de retomada. Próximo bloco: #291,
issue aberta consultada, radar puro de metadados, sem novas queries ou cron.
