# NIVON — Drill local Restic cifrado / recuperação SQLite

**Escopo 20/10/2026:** somente fixture inteiramente sintética e repositório Restic local efêmero. **NÃO é backup remoto nem homologação de produção.**

## Componentes implementados

- `src/nivon/infra_restic_drill.py`: CLI com comportamento padrão inerte; somente `--synthetic-drill` cria pasta temporária 0700, credencial aleatória 0600 e repositório LOCAL cifrado.
- `nivon.pacote_recuperacao`: reutiliza o backup consistente SQLite existente e manifesto com SHA-256, contagem de tabelas e teste de restauração local.
- Restic: `init`, `backup`, `check`, `snapshots --json`, `restore` sem shell e sem repo remoto; comprova exatamente um snapshot da fixture.
- Restore: exige exatamente um manifesto e SQLite na mesma pasta, sem symlinks; confere hash, integridade e tabelas. Nada é restaurado em pasta operacional.
- `tests/test_infra_restic_drill.py`: opt-in, modos bloqueados, isolamento de credenciais, comandos proibidos, logs redigidos e teste E2E quando houver binário real.
- `.github/workflows/infra_restic_drill.yml`: runner público efêmero, Restic instalado via pacote Ubuntu, testes e duas chamadas CLI. Sem job agendado, credencial cloud, upload de artefatos ou deploy.

## Controles

- Estado padrão `OFF_BY_DEFAULT`, não inicia contêiner/backup.
- Flags `NIVON_RUNTIME_ENABLED`, `NIVON_BACKUP_ENABLED`, `NIVON_COLLECTORS_ENABLED` e `NIVON_PUBLICATION_ENABLED` diferentes de `false` bloqueiam o CLI.
- Subprocesso só recebe `PATH`, `HOME`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE`, `RESTIC_CACHE_DIR`; não herda variáveis/token cloud.
- A senha fica somente em diretório privado efêmero, não é impressa nem versionada.
- Repositório Restic é criado do zero em diretório separado da fonte e removido após o ensaio. Não há token de Cloud nem URL externa.
- Saída/erros brutos do Restic não são ecoados pela ferramenta em falhas.
- Não há `forget`, `prune`, `unlock`, automação periódica ou opção para fornecer caminho externo via CLI.

## Reprodução de homologação local (não produção)

Requer Python >= 3.11 e Restic instalado de pacote confiável. Consultar a versão no repositório do sistema operacional.

```sh
PYTHONPATH=src python -m nivon.infra_restic_drill
PYTHONPATH=src python -m unittest discover -s tests -p test_infra_restic_drill.py -v
PYTHONPATH=src python -m nivon.infra_restic_drill --synthetic-drill
```

Resultado esperado com Restic disponível:
`RESTIC_LOCAL_ENCRYPTED_SYNTHETIC_RESTORE_OK`, 1 snapshot, 1 tabela verificada e `remote_backup_verified=false`. Em máquina sem Restic, o ensaio explícito falha com status bloqueado; o modo padrão continua sem mutações.

**Atenção:** o CI usa rede apenas para obter código e instalar Restic no runner. As operações de backup/restauração do módulo apontam exclusivamente para o filesystem local. O ensaio não valida isolamento de rede do host.

## O que falta para backup de verdade

1. Comprovar storage independente e permitido na conta OCI, quotas restantes, faturamento, saída de dados e alternativa separada da tenancy; nunca assumir que bucket no mesmo provedor atende ao requisito de independência.
2. Projetar diretórios operacionais segregados e identidade IAM mínima; segredo de backup sob mecanismo autenticado com rotação e plano de recuperação da chave.
3. Exercitar em **ambiente de homologação aprovado** backup remoto cifrado de um conjunto autorizado, restauração em outro host, retenção, RPO/RTO, auditoria e resposta a falha/quota.
4. Só então integrar timers/alertas (backup ausente/defasado, erro, indisponibilidade, dados não restauráveis, espaço em disco) e promover gate de durabilidade após revisão independente.
5. A prova local não libera `BACKUP_RESTORE` ou `ZERO_COST_PROOF` no `inventory.v1.json`.

Nenhum dado real, servidor, cron, serviço pago ou configuração de destino remoto é criado nesta etapa.
