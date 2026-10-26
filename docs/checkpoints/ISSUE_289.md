# Checkpoint #289 — ANTT/SIADE verificável

Branch independente `codex/289-antt-reader-contract`, baseada na main `97f032d`.
PRs #276 e #283 inspecionadas: nenhuma altera `terminal_web.py`; não foi criado
outro leitor ou servidor. Issue #289 consultada aberta na página pública.

Entrega: API anual inclui SHA-256, referência mensal e coleta UTC separadas.
A query continua SELECT parametrizado com teto de 250 MB; COUNTIF impede que
campos nulos sejam silenciosamente descartados pela agregação. Zero observado
com registros é preservado; ausência, SHA inválido e referência incoerente bloqueiam.

Freshness usa idade da competência, não idade da coleta. Alerta operacional
SOURCE_LAG acima de 3 meses, explicitamente não SLA oficial da ANTT. Interface
exibe SHA por ano e alerta de fonte defasada, preservando competência. Atualizar
não duplica linhas e falha posterior esconde valores antigos. Cache expirado não
é servido se a nova consulta falhar; concorrência não multiplica queries.

Validação local: 18 testes Python do terminal aprovados (7 novos), 3 testes Node
executando o JS da UI com DOM/fetch simulados aprovados. Suíte completa da branch:
761 testes sem falhas, 2 ignorados Parquet opcionais. `git diff --check` aprovado.
Os 10 testes da branch #288 não estão nesta branch independente.

Sem consulta LIVE, deploy, IAM ou gastos. Autenticação real depende do Cloud Run;
HTTP local não implementa IAM. Testes de política privada/deploy existentes estão
incluídos na suíte; isso não prova autorização de produção. CI remoto não foi
confirmado. API GitHub retorna Forbidden; corpo/estado da PR deve ser registrado
quando esse acesso estiver disponível. Próximo bloco elegível: #287, aberta,
reaproveitando assets da #276 no servidor existente sem importar outro servidor.
