# NIVON — Backup nativo PostgreSQL da PTAX (sem Google Cloud)

**Situação:** utilitário versionado, testes com arquivos sintéticos. **Não foi executado pg_dump contra o Neon real**, nem foi restaurado banco Postgres nesta etapa. Não existe comprovação de backup externo/criptografado. Esta operação não autoriza migrar/desligar o Neon ou ativar faturamento no Google Cloud.

## Por que um segundo método de backup?

O pacote JSONL permite conferir a estrutura e fazer replay local em SQLite, mas não comprova restauração PostgreSQL. Para recuperação real das tabelas operacionais, criamos `scripts/ptax_postgres_native_backup.py`: ele usa **um único `pg_dump` em formato custom**, que oferece snapshot consistente mesmo com o banco recebendo novas cotações, e inspeciona o inventário via `pg_restore --list`. Fonte técnica: https://www.postgresql.org/docs/17/app-pgdump.html

**Inclui exatamente as tabelas** `public.nivon_ptax_quotes`, `public.nivon_ptax_runs`, `public.nivon_ptax_checkpoints` e **as sequências** `public.nivon_ptax_quotes_id_seq` e `public.nivon_ptax_runs_id_seq` (seus nomes foram confirmados no Neon em consulta somente leitura). O verificador exige registros `TABLE`, `TABLE DATA` e `SEQUENCE SET` no inventário. Assim não apresenta um dump de schema sem dados ou sem sequência como completo.

## Execução privada, somente quando houver acesso autenticado à origem

Execute em máquina ou terminal privado com `pg_dump` e `pg_restore` compatíveis com PostgreSQL 17, um perfil `PGSERVICE` protegido para o **endpoint direto** do Neon `NIVON-PTAX-OPERACIONAL` e `.pgpass` local de permissão 0600. Não utilize pooler transacional nem associe esse perfil ao segundo projeto Neon vazio. Nunca forneça credenciais ao GitHub ou ao chat. A aplicação não imprime caminhos privados, preços ou mensagens do servidor.

**Construção (gera snapshot nativo local somente quando acionado pelo operador):**

```bash
export PGSERVICE=nivon-private
python3 scripts/ptax_postgres_native_backup.py \
  --build --destination /diretorio-privado/nivon-ptax-backup-01
```

O destino deve ser **novo**, estar fora do repositório e ter parent previamente criado. Falhas apagam somente o diretório novo criado pela ferramenta, nunca a origem. Não use nome já existente: a ferramenta recusa sobrescrita. A pasta recebe modo 0700 e os arquivos 0600. O utilitário não usa `PGPASSWORD`; configure PGSERVICE/`.pgpass` com autenticação segura. Pode haver consumo de rede, CPU ou cotas do banco Neon na execução real; verificar limites Free antes de iniciar.

**Verificação do inventário e checksum (não conecta ao Neon):**

```bash
python3 scripts/ptax_postgres_native_backup.py \
  --verify --destination /diretorio-privado/nivon-ptax-backup-01
```

O resultado `LOCAL_PGDUMP_ARCHIVE_TOC_VERIFIED` significa que o inventário do arquivo e seu checksum são consistentes. **Não equivale a restaurar dados em PostgreSQL.** O arquivo precisa ser copiado a outro armazenamento privado, com criptografia e retenção definidas; nenhuma dessas ações está automatizada.

## Critérios para liberar migração

- O manifesto registra `one_pg_dump_snapshot=true` somente quando a criação do arquivo retorna sucesso e o TOC é validado.
- Os campos `data_rows_verified`, `source_row_counts_reconciled`, `native_postgres_restore_verified`, `stored_offsite`, `encrypted_archive_verified`, `bigquery_cutover_approved` permanecem **false**; qualquer tentativa de marcá-los true torna o manifesto inválido.
- A próxima etapa é restaurar esse dump, separadamente, em um **PostgreSQL descartável e isolado** com as permissões adequadas. Não executar `pg_restore` contra o Neon operacional; evitar flags destrutivas como `--clean` ou `--create` no ambiente de produção.
- Após restauração, conciliar contagens, chaves, preços, timestamps e sequências de identidade com snapshot consistente; e executar os testes de replay e reconciliação já versionados na PR #84.
- Reconciliar a cobertura histórica, que ainda não abrange integralmente 2020–2026; ausência de erro de coleta não prova cobertura dos pregões.
- Google Cloud `nivon-data`: status de faturamento/permissões não chegou de forma verificável; não criar dataset/bucket nem copiar os arquivos até esse gate ser resolvido.

## Evidências de execução

Os testes de GitHub Actions usam exclusivamente `pg_dump` e `pg_restore` **simulados**: comprovam bloqueios de segurança e verificação de contrato, não fazem backup de banco real. A execução de validação de **pg_dump real** permanece pendente de um ambiente privado autorizado. Nunca colocar `*.pgcustom`, `*.dump`, `*.pgpass`, URLs internas ou segredos no repositório público.
