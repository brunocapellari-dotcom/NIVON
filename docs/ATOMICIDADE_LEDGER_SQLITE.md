# Atomicidade SQLite — coleta e conteúdo canônico

`transacoes_sqlite.savepoint_atomico` usa SAVEPOINTs aninhados com rollback e release em falha. `registro_snapshots.registrar_snapshot` não confirma mais transações abertas pelo chamador. `pipeline_api_dados` e `ingestao_mdic` registram snapshot, horário e observações/agregados dentro da **mesma transação**, para que um INSERT recusado nunca deixe vintage sem dados.

Os testes sintéticos criam triggers `RAISE(ABORT)` para simular falha de armazenamento e confirmam rollback de `nivon_snapshots` e `nivon_coletas`; há também testes de preservação de transação externa.

O pacote é offline, sem network, deploy, custo, permissões novas, publicação comercial ou migração destrutiva. Não resolve disponibilidade/instabilidade da fonte ou backup remoto; o ledger registra apenas metadados e as observações canônicas seguem separadas dos arquivos originais.
