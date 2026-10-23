# NIVON — R12 | Governança operacional de fontes e preparação transacional da outbox

**Data:** 23/10/2026. **PR:** #192 draft. **Base:** PR #153 @ a1832a5fce210bb07ac5bd4f5b26cf84bfb55445.

## Entregas implementadas e verificadas

1. **Auditoria operacional automatizável:** `src/nivon/auditoria_workflows_operacionais.py` percorre fontes YAML existentes *somente como texto*. Identifica agendas, workflow_dispatch, push, OIDC de escrita, domínio referenciado, possível escrita HTTP/GCP e indicação textual de gate de custos. Em hipótese alguma aciona workflow, coleta, API ou banco. O retorno não representa confirmação de execução, licenciamento, idempotência de fonte, direitos ou frescor.
2. **Snapshot GitHub verificável:** foram importados via blobs Git originais oito YAMLs de `main` no SHA `f68239f0dafe9029725f6f3b91bf363275d45fe0`, em `tests/fixtures/r12_workflows_main/`. Não estão em `.github/workflows/`: são fixtures inertes, não novas automações. Git blob SHAs: CEPEA `48ae512380fd2115b02101a147e79b8e8a311ae7`, CONAB `d8c97783a92ea411c3fb7ef678b2463a339bedea`, IMEA `dc96e9fa389742adb7d381240c7fb7285a2a5eca`, ANTT MDF-e `51722843111e2967ef3ee8588b1f27d305288f10`, coleta GCP `decb11e390a6aca74734f058fa452e5d3b0effff`, monitor P0 `4c9697cfea0f63a262e62a43509563498f31158e`, ANTT anuário RGI `6b1148bfe1fdbe0f1e3fca431ec876bd1893c4c8`, IBGE-WDI E2E `fbc793b340d16602268f5d722858fb3e82538609`.
3. **Contrato PostgreSQL compartilhado:** `sql/postgres/020_outbox_canonica.sql` contém tabelas de consentimentos, reservas, recibos, tentativas de POST e quarentena; uma reserva por `dia_local + destinatario_hmac`, vínculo canônico de provedor e bloqueio de tentativas repetidas. Usa funções e triggers PostgreSQL para revogação terminal e estados monotônicos e `FOR UPDATE` para serializar reserva/opt-out. **Não executado em PostgreSQL real** e não substitui autenticação externa, garantia de entrega nem integração do gateway.
4. **Plano de transição read-only:** `plano_transicao_outbox_postgres.py` audita bancos SQLite locais sem mutação, usa hash lógico e do esquema, aponta anomalias entre legados e recibos, e exige etapas de backup criptografado, restauração, prova de consentimento, teste PostgreSQL real, reconciliação e cutover com aprovação expressa. Não extrai, copia ou promove dados de clientes.
5. **Execução consolidada:** `scripts/auditar_workflows_outbox_r12.py` pode rodar as duas auditorias em um único comando. Fixture com dados sintéticos prova que nenhum telefone, HMAC de destinatário ou ID do provedor aparece no JSON e que divergências bloqueiam o plano.

## Achados estáticos em workflows reais da main (fotografia do SHA indicado)

| Workflow | Cron identificado | OIDC write | Escrita externa potencial | Gate de custo detectado textualmente |
|---|---|---|---|---|
| CEPEA para Neon | 0 23 e 45 23, seg-sex (UTC) | sim | sim | não |
| CONAB para Neon | 0 17 seg-sex (UTC) | sim | sim | não |
| IMEA estágio para Neon | 0 14,23 seg-sex (UTC) | sim | sim | não |
| ANTT MDF-e catálogo | 20 11 todos os dias (UTC) | não | não no sinal textual | não |
| Coleta recorrente GCP | 20 11 seg-sex (UTC) | sim | sim | sim (por variável) |
| Monitor P0 | 15 12 seg-sex (UTC) | não | não no sinal textual | não |
| ANTT anuário RGI | nenhum na fotografia | não | não no sinal textual | não |
| IBGE/WDI E2E | nenhum na fotografia | não | não no sinal textual | não |

**Criticidade:** 6 dos 8 workflows têm agenda. 4 declaram permissão `id-token: write`; 4 apresentam indicadores de mutação externa na varredura textual, sendo 3 escrituras Neon sem gate de despesa detectado pela regra estática e 1 via GCP com gate de variável textual. Isso NÃO prova ausência de orçamento real do Neon nem garante que gates da GCP funcionem; a auditoria não lê secrets, IAM, billing, logs, histórico de runs ou banco remoto. Cron é sempre apresentado em UTC; execução e conclusão não foram observadas nesta PR.

Os endpoints de produção existentes nos YAMLs são tratados como contexto para auditoria: não disparar novos POST, não usar informações históricas como atuais, exigir timestamps de competência/publicação/coleta, licença/fonte primária e validação de persistência real antes de publicar preço ou volume.

## Uso offline

Auditar os oito workflows sem rede:

`PYTHONPATH=src python scripts/auditar_workflows_outbox_r12.py --workflows-dir tests/fixtures/r12_workflows_main`

Auditar também SQLite existente (somente em clone local autorizado):

`PYTHONPATH=src python scripts/auditar_workflows_outbox_r12.py --workflows-dir tests/fixtures/r12_workflows_main --banco /path/privado/outbox.sqlite --ddl-postgres sql/postgres/020_outbox_canonica.sql`

Não realizar `psql -f` em banco de produção. O SQL exige revisão de segurança, performance, transações, backups, licenças e custos, além de testes **reais** em Postgres descartável autorizado, ainda não efetuados.

## Evidências de testes

CI após implementação (antes desta nota):
- [Núcleo #39984181224](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984181224): **2.127 testes, 0 falhas, 3 ignorados**.
- [Acessos isolados #39984181291](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984181291): **2.127 testes, 0 falhas, 35 ignorados**; USDA/ANA/INMET `REDE_DESATIVADA`.

**Limites importantes:** a validação SQL atual é lexical e testes executados são somente SQLite/workflows offline. Não há Postgres instalado no runner, não se demonstrou locking real de triggers, migração em nuvem, política de opt-in humana nem custos. Nenhum novo job ativo, merge, deploy, uso de credencial ou cobrança foi autorizado.

## Próximas prioridades materiais

- **Primeira:** testar SQL em PostgreSQL descartável e migração dos estados em clone autorizado com prova de restauração. Avaliar constraints e deadlocks usando 2+ conexões reais e rollback, jamais promover delivered sem prova externa.
- **Segunda:** correlação de fonte e resultados observados; investigar status reais de workflows CEPEA/IMEA/CONAB/ANTT/IBGE em seus jobs e destinos, sem inferir atualidade do código; controles de custos e direitos, com intervenção se necessário.
- **Terceira:** sincronização do IVO PAM pelo incremental de PR #7, em PR independente, sem permitir que arquivos operacionais de GCS ou workflows live sejam disparados. Validar lineage/provenance e semântica SINTETICO vs observado.
- **Quarta:** reconciliar incremento rápido da `main` de forma seletiva (bibliotecas/pipelines vs operações e custos); evitar importar scripts que ativem BigQuery/Neon por conveniência.
