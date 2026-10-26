# Checkpoint #291 — radar puro de source health

Branch independente `codex/291-source-health`, base main `97f032d`.
Issue pública aberta e busca de PRs abertas por #291 conferidas; nenhum candidato
específico encontrado. Código existente de ANTAQ, agro, ANTT e saúde marítima
inspecionado. Reutiliza assess_source_health para transporte, sem novo coletor.

Entrega: função pura e CLI JSON para ANTT/CEPEA/IMEA/CONAB, com estados fresh,
lagged, unavailable e quarantined. Referência/publicação/coleta/competência são
separadas; janela é política explícita, não SLA inventado. Idempotência de eventos,
revisões, referência antiga e falha/recuperação. Nenhuma promoção automática.

Validação: 10 testes novos com relógio congelado; suíte completa da branch 764
sem falhas, 2 skips Parquet. CLI JSON exercitada com fixture sintética IMEA em
quarentena. Nenhum dado real foi lido, homologado ou apresentado como observação.
`git diff --check` aprovado. CI offline adicionado; CI remoto não confirmado.

A saída JSON está disponível para consumo do painel. Não há integração LIVE,
polling, cron, query BQ ou fonte restrita ativada. API GitHub Forbidden bloqueia
abertura da PR; este arquivo registra a entrega para retomada. Próximo passo:
validar branches juntas e avançar #296, verificando primeiro seu estado atual.
