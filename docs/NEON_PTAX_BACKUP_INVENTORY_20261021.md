# NIVON — Inventário de proteção do Neon (21/10/2026)

**Escopo:** leituras autenticadas do projeto Neon `divine-lab-03469752`, banco `nivon`, branch operacional `main` (`br-twilight-cell-b77ukd6x`). Nenhuma alteração em banco, branch, backup ou scheduler nesta auditoria.

## Evidência operacional da PTAX

- `public.nivon_ptax_quotes`: 1.066 cotações (EUR 888 em 178 datas; USD 178 em 178 datas), de 2020-01-02 a 2026-10-21 por datas extremas.
- `public.nivon_ptax_runs`: 18 execuções `SUCCESS`, nenhuma outra situação retornada no `GROUP BY status`.
- O banco permanece coletando/backfill; valores acima são fotografia da consulta e não série histórica completa.

## Inventário real de recuperação

- API `list_branches`: **somente uma branch** encontrada (`main`, branch primária/default). Isto não estabelece independência de backup.
- API `list_snapshots`: resposta `[]` (nenhum snapshot registrado no inventário visível).
- API `get_snapshot_schedule` para `main`: `{ "schedule": [] }` (nenhum agendamento configurado no inventário visível).
- Não existe evidência de backup externo criptografado e restaurável **controlado pelo NIVON**.
- Estes inventários não provam inexistência de retenção interna automática ou point-in-time recovery do provedor. Não atribuir a um recurso interno do Neon os mesmos requisitos de backup externo independente.

## Mitigações ainda pendentes

1. Produzir um dump nativo **real** com `scripts/ptax_postgres_native_backup.py` em computador/terminal privado usando `PGSERVICE`/`.pgpass` protegido e `pg_dump` compatível; não executar diretamente no GitHub público nem imprimir credenciais.
2. Armazenar cópia criptografada e privada em local independente, testar recuperação em PostgreSQL isolado e reconciliar linhas e sequências.
3. Validar frequência, retenção, custo e permissões de eventuais snapshots gerenciados; **não habilitar planos pagos, agendamentos ou snapshots por conta própria**.
4. Repetir contagens, execução, checkpoint e cobertura da PTAX após a cópia; não interpretar `SUCCESS` do coletor como cobertura histórica completa.
5. Manter Neon operacional e migração BigQuery bloqueada até haver backup restaurável, avaliação de licença e verificação do billing/IAM do projeto GCP `nivon-data`.

## Prova de restauração sintética

O [ensaio real PostgreSQL 17 em CI](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39700936468) restaurou três tabelas e duas sequências com dados inventados em container descartável sem rede. Confirma capacidade técnica de ensaio, **não** recovery do Neon real. A PR #84 mantém todos os gates de produção bloqueados.

**Decisão:** no estado verificado, risco de recuperação operacional permanece aberto, `native_postgres_restore_verified=false` e `bigquery_cutover_approved=false`. Não realizar limpeza nem corte irreversível.
