# CONAB — Progresso Semanal, safras e vintages

`conab_agrobr.normalizar_progresso` continua responsável pela estrutura informativa (fonte, cultura, safra, operação, UF, semana, percentuais). O novo `progresso_conab_historico.py` consome seus dados normalizados e registra em SQLite local a versão do arquivo, as coletas repetidas e revisões históricas. O SHA, tamanho e MIME **são informados pelo chamador**, e ainda devem ser conferidos com bytes efetivamente obtidos de fonte autorizada para qualquer uso real. O módulo não extrai, acessa ou baixa dados da CONAB.

O filtro por UF distingue 27 UFs e `MEDIA_ESTADOS`. A média simples dos estados **nunca é produção/percentual brasileiro ponderado por área**. Percentuais são frações 0..1; o valor corrente não pode ser nulo; variações históricas não são corrigidas automaticamente. As consultas por corte tratam datas de coleta como conhecimento adquirido, não como publicação oficial: não habilitam backtest por data publicada quando não comprovada.

Proteções: catálogo + direitos de coleta e armazenamento para qualquer uso real, transações SQLite com savepoint, validação de duplicatas, rejeição de edição divergente sob mesmo SHA, revisão por vintage, rollback de falhas simuladas, sintéticos ocultos por padrão. Nenhum coletor foi ativado, não há persistência remota, deploy, merge, custo ou publicação.

**Separação fonte versus coleta:** o campo `coleta` é metadata de captura e fica no ledger `nivon_coletas`, não no JSON de observação da edição. Capturar os mesmos bytes em outro horário não cria outra versão. A consulta as-of devolve o carimbo de coleta do ledger, preservando o eixo temporal sem reescrever o conteúdo original.

### Integridade dos bytes de origem (20/10/2026)

O parâmetro `arquivo_origem` (bytes) passou a ser **obrigatório para registros REAL_AUTORIZADO**. É verificado antes da inserção: SHA-256, tamanho informado e assinatura básica do MIME (XLS OLE, XLSX ZIP, PDF, JSON e textos). Essa conferência não armazena os bytes, não comprova direitos nem prova que o parser extraiu fielmente os números do arquivo; os demais gates permanecem bloqueados. Modo sintético aceita ausência de payload para testes legados, mas identifica `hash_conferido_com_bytes=False`.
