# NIVON — Auditoria independente de backup SQLite/WAL

**Data:** 2026-10-21 (America/Cuiaba)  
**Código-base:** PR #13, SHA `9f1a5e0ded09ac2246cc83b764ddb60f44436986`.  
**PR de auditoria:** #39, branch `audit/backup-wal-recovery-20261021`.  
**Prova de CI:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39593655399 (SHA `a581a7f022627cde8b22214ceba3b50c22f1ff54`).  
**Resultado:** 886 testes, uma falha adversarial, cinco skipped. Nenhuma conexão a serviços reais.

## Dois testes processuais reproduzíveis

### Cenário positivo — backup WAL de leitor distinto enquanto outro escritor aguarda commit

1. Arquivo SQLite temporário com `journal_mode=WAL`, uma linha já confirmada.
2. Processo escritor usa outra conexão, `BEGIN IMMEDIATE`, insere segunda linha, sinaliza início da transação e aguarda liberação para commit.
3. A conexão leitora distinta invoca `criar_backup`; depois invocamos `restaurar_backup` com o SHA-256 emitido.
4. O banco restaurado contém **somente a linha confirmada** (não contém transação não confirmada do escritor), com `integrity_check=ok`.
5. Após liberação, o banco de origem contém as duas linhas. **Teste passou em CI.**

Isso comprova o cenário local testado, **não** valida backup remoto, criptografia, restauração por perda de host, operação comercial ou cópia consistente sob todas as cargas.

### NC-AUD-018 — P0: backup chamado na própria conexão com INSERT ainda não confirmado trava

1. Processo separado abre SQLite temporário, executa `BEGIN IMMEDIATE` e `INSERT` sem commit.
2. Chama `criar_backup(conn, destino)` usando essa **mesma conexão de escrita**.
3. O teste exige que a operação falhe rapidamente de forma explícita em vez de travar silenciosamente.
4. Após **4 segundos**, o processo continuava vivo. O harness o encerrou; asserção falhou com:
   `AssertionError: True is not false : P0: criar_backup chamou sqlite3.Connection.backup a partir de uma conexão com INSERT não confirmado e não retornou dentro de 4s`.

**Hipótese técnica:** `sqlite3.Connection.backup` chamada da conexão com transação de escrita pendente pode bloquear aguardando uma condição que seu próprio chamador não libera. O experimento confirma o travamento observado; não comprova comportamento igual em todos os sistemas operacionais e versões SQLite.

## Critérios de correção e aceite

- Em `criar_backup`, detectar prontamente `conn.in_transaction` e recusar conexão incompatível com a semântica exigida, ou aceitar somente conexão leitora dedicada e comprovar separação de transações.
- Preservar cópia atômica sem sobrescrita, SHA-256, foreign key check e verificação de integridade.
- Retestar ambos os cenários; novo teste com transação aberta deve **retornar com exceção controlada e rápida**, sem processo órfão.
- Ampliar depois para backup/restore em WAL sob 16 escritores e 48 operações (R03) quando o write path for corrigido; não confundir esse teste de leitor/escritor com a concorrência R03 de múltiplos escritores.
- Homologação produtiva requer política de checkpoint/WAL, armazenamento durável externo, criptografia, segregação de acesso, restore drill real e RPO/RTO verificados.

**Decisão:** bloqueio de fluxos automáticos de backup que possam reutilizar conexão com transação pendente. Nenhum dado real, serviço remoto, deploy ou cobrança foi utilizado. A auditoria não corrigiu nem alterou o código de produção.
