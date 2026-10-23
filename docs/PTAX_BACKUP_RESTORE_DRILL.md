# NIVON — Backup portátil PTAX: três tabelas e replay local

**Situação em 21/10/2026:** código preparado e testado com fixtures sintéticas. **Não existe backup externo real comprovado**, não foi realizado dump das tabelas Neon nesta implementação, nem restauração nativa em PostgreSQL. Nenhum recurso Google Cloud foi criado.

## Proteção exigida antes de copiar a PTAX ao BigQuery

Preservar **as três tabelas**, não apenas as cotações: `nivon_ptax_quotes`, `nivon_ptax_runs`, `nivon_ptax_checkpoints`. Essas tabelas têm histórico, operação e posição do backfill. O SQL canônico do Neon está na PR #58 em `database/neon_ptax_schema.sql`.

O utilitário `scripts/ptax_private_backup_drill.py` recebe arquivos JSONL exportados por um canal autenticado e privado, gera um pacote em diretório novo com permissões restritas, verifica SHA-256 de cada arquivo e a estrutura de todas as linhas e faz replay em um banco **SQLite em memória**. Impede duplicidade de chave, cotações inválidas, janelas invertidas e checksum divergente.

Isso comprova somente que **um arquivo JSONL pode ser reconstruído em memória sem divergências**. Não comprova restauração real do banco PostgreSQL, persistência externa, snapshot transacional original ou migração para BigQuery. Todos esses gates permanecem falsos.

## Exportar em snapshot consistente — execução posterior, em ambiente autenticado

**Pré-requisito:** computador ou terminal privado com cliente `psql` autenticado no Neon por mecanismo seguro existente (`PGSERVICE`/arquivo `pgpass` com permissões adequadas). Não adicionar connection string, login ou senha ao repositório, chat ou logs. Evitar que um arquivo local com preços e detalhes operacionais fique acessível a terceiros.

Os três arquivos precisam sair da **mesma transação PostgreSQL REPEATABLE READ READ ONLY**. Com `umask 077` e diretório privado previamente criado, executar no terminal conectado ao Neon o roteiro abaixo, substituindo `/caminho/privado/ptax` pelo diretório absoluto **fora do GitHub**:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
\copy (SELECT row_to_json(t) FROM (SELECT * FROM public.nivon_ptax_quotes ORDER BY id) t) TO '/caminho/privado/ptax/nivon_ptax_quotes.jsonl'
\copy (SELECT row_to_json(t) FROM (SELECT * FROM public.nivon_ptax_runs ORDER BY id) t) TO '/caminho/privado/ptax/nivon_ptax_runs.jsonl'
\copy (SELECT row_to_json(t) FROM (SELECT * FROM public.nivon_ptax_checkpoints ORDER BY currency,window_start,window_end) t) TO '/caminho/privado/ptax/nivon_ptax_checkpoints.jsonl'
COMMIT;
```

**Importante:** `\copy` é uma instrução especial do **psql** (não é SQL puro do editor web do Neon ou do BigQuery). Se alguma instrução falhar, interromper e descartar todos os arquivos daquela tentativa. Confirmar o nome dos arquivos e permissões após exportar. A transação consistente não é automaticamente atestada pelo verificador local; deve ser comprovada pelo registro da sessão e contagens lidas no mesmo snapshot.

Se o cliente usado não suporta REPEATABLE READ nas três extrações, não apresentar seus arquivos como snapshot consistente. Para uma cópia nativa PostgreSQL também é possível usar `pg_dump` com formato customizado, seguido de **ensaio de restauração em instância isolada**; tal ensaio ainda está pendente e não é implementado por este utilitário.

## Construir pacote privado

```sh
python3 scripts/ptax_private_backup_drill.py --build \
  --source /caminho/privado/ptax \
  --bundle /caminho/privado/ptax-backup-20261021
```

Validação posterior, com os mesmos arquivos:

```sh
python3 scripts/ptax_private_backup_drill.py --verify \
  --bundle /caminho/privado/ptax-backup-20261021
```

**Atenção:** o pacote é composto de JSONL não criptografado com permissões de arquivo 0600 e pasta 0700. O armazenamento externo seguro, a criptografia em repouso, o controle de acesso e a retenção precisam ser resolvidos **antes** de usá-lo como backup operacional. Ele não deve ser enviado para um repositório público.

## Critérios auditáveis

- Cada arquivo exige schema estrito, tipos válidos e hashes reproduzíveis; versões de compra/venda distintas não são colapsadas.
- O manifesto não pode afirmar backup independente, restauração PostgreSQL, migração ou autorização de corte.
- Zero cotações, registros duplicados, arquivos corrompidos, dados fora do repositório insuficientemente protegidos ou arquivo novo inesperado bloqueiam o pacote.
- A validação usa replay local SQLite em memória sem alterar o banco real ou ativar GCP.
- O verificador **não confirma completude da série 2020–2026**. A auditoria agregada (`database/neon_ptax_readonly_audit.sql`) continua obrigatória.
- O backfill Neon pode seguir enquanto exportamos, mas a posição no snapshot e a contagem final exigem reconciliação posterior. Nunca parar nem apagar a coleta por conclusão de um ensaio local.

## Próxima condição de implantação

Confirmar o resultado da auditoria do Google Cloud `nivon-data` (billing e IAM), validar custos e backups; então executar uma cópia de teste isolada e a reconciliação. Enquanto isso, a PR #84 permanece sem deploy e o Neon segue como banco operacional.
