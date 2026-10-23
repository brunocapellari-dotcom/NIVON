# NIVON — R10: lote autônomo de integração, migração e recuperação

**Data de referência:** 22/10/2026 (Brasil). **Estado:** PR #126 DRAFT. Sem merge, deploy, coleta externa ou envio.

## Priorização e resultado

| Prioridade | Atividade concluída neste lote | Teste de aceitação |
|---|---|---|
| P0 | 13 arquivos de meteorologia e hidrologia da main importados por SHA | Diff de árvores sem sobrescrita, CI offline |
| P1 | Inventário histórico + quarentena idempotente sem promoção de estados | Ausência de opt-in, duplicações, adulterações, replay |
| P2 | Backup prévio e posterior; restore para SQLite novo | SHA físico, hash lógico, integrity_check, FK, no-overwrite |
| P3 | Orquestrador de todos os passos num único comando offline | Auditoria só leitura e staging+backup+restore E2E |
| P4 | Governança e evidências do lote na PR | CI no HEAD, bloqueios e documentação |

## P0 — main vs PR anterior

- Base imutável R09: PR #110 @ bea2a0b29b76873f38fd8352d491c3fec26a7910.
- main consultada: f968cf6b5af58a4a7fb4fb551c456fef4c729c12, com PR #87 hidromet e workflow CEPEA posterior.
- Integrados 13 arquivos de fontes e testes: INMET estações, CPTEC/BrasilAPI, NASA POWER, Open-Meteo, GloFAS, CEMADEN e diagnóstico de APIs públicas, documentação e um workflow que só usa workflow_dispatch.
- EXCLUÍDO o workflow cepea-neon-ingest.yml: já está na main e tem cron e POST externo real com OIDC/Neon. Não foi copiado, executado ou alterado. Sua existência no GitHub não prova execução, licenciamento ou completude.

## P1 — Migração conservadora

Novo módulo src/nivon/migracao_outbox_legada.py:
- Planeja sem modificações, inclusive em banco sem tabelas canônicas.
- Detecta duplicação por dia+destinatário, provider reaproveitado, consentimento ausente ou revogado, reserva divergente e histórico sem atestação.
- Estágio atômico em tabela de quarentena somente quando autorizado, gravando fingerprints e metadados opacos, NÃO os números/IDs originais de provedor.
- Repete o estágio sem criar duplicatas; alteração de registro após captura falha fechada e reverte transação.
- NÃO transforma DELIVERED legado em entrega canônica, não concede opt-in, não liga envio e não cria retry.

## P2 — Backup consistente e restore

Novo módulo src/nivon/backup_outbox.py:
- Usa backup nativo SQLite a partir de conexão sem transação aberta.
- Aplica SHA-256 físico, resumo lógico de tabelas/linhas, PRAGMA integrity_check e foreign_key_check.
- Recusa destino existente e path não absoluto. Arquivos novos criados com modo 0600 (onde suportado).
- Restaura para outro arquivo novo, verifica SHA do backup antes e compara o estado lógico posterior.
- Somente backup LOCAL: não habilita cloud, não garante criptografia, nem plano completo de DR. HMACs de destinatário estão no arquivo e requerem armazenamento privado e criptografado.

## P3 — Orquestração com um comando

Arquivo src/nivon/lote_recuperacao_outbox.py.

Auditoria read-only, padrão (não cria tabelas nem altera DB):

    PYTHONPATH=src python -m nivon.lote_recuperacao_outbox --banco /caminho/seguro/outbox.sqlite

Rodada LOCAL opcional, apenas em clone/base autorizada e pasta de backup privada nova:

    PYTHONPATH=src python -m nivon.lote_recuperacao_outbox --banco /caminho/seguro/outbox.sqlite --diretorio-backup /caminho/privado/backup-novo --executar-lote-local

Sequência num único processo: inventário → backup ANTES da quarentena → staging atômico → backup DEPOIS → restore de teste → validação de digest. Rejeita segunda execução que sobrescreveria backups existentes. Saída JSON contém só contagens e digests, sem HMAC de destinatários. Não rodar em banco real sem aprovar segurança, identidade e armazenamento.

## E2E executado no CI (dados exclusivamente sintéticos)

- Briefing: consentimento assinado artificial → reserva → aceite do provedor simulado → entrega confirmada → persistência.
- WhatsApp: mesmo ledger, reserva → ACK simulado → webhook HMAC sintético → entrega → persistência.
- Inventário 3 registros legados, quarentena de registro sem opt-in, idempotência, duplicação adversarial entre canais, alteração de estado legada após captura.
- Backup pré e pós, restore completo e comparação lógica, rejeição de arquivo adulterado, segunda gravação e execução sem flag.
- CLI numa execução de auditoria não mutável e outra de staging+backup+restore.
- USDA/ANA/INMET sem rede nos jobs isolados.

Evidência parcial após implementação P0/P1/P2:
- Núcleo: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890533072 (2.099 testes, 0 falhas, 3 ignorados).
- Acessos: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890533101 (2.099 testes, 0 falhas, 35 ignorados).

Evidência após orquestrador P3:
- Núcleo: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890748061 (2.101 testes, 0 falhas, 3 ignorados).
- Acessos: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890748067 (2.101 testes, 0 falhas, 35 ignorados).

Esta documentação gera outro HEAD: conferir novamente CI do HEAD final e registrar na PR.

## Bloqueios reais e próximos lotes

1. Migração real depende de selecionar banco operacional único, acesso autorizado, inventário de dados e janela de mudança; não foi realizada.
2. Consentimento real e opt-out exigem atestação independente do titular/operador e credenciais seguras. HMAC de teste não é evidência de opt-in.
3. Promoção de legacy DELIVERED exige recibo autenticado, prova WABA/tenant e verificação individual/por amostragem; não foi feita.
4. Restaurar em produção requer backup externo criptografado, KMS, política LGPD, testes DR/HA e plano de reversão.
5. PR #7 IVO avançou em ~20 paths após último sync; reconciliar num lote científico próprio, separado do ledger financeiro/de mensageria.
6. Cron CEPEA ativo no arquivo da main requer auditoria específica de execução, direitos, fonte, frescor e custos, sem disparos adicionais neste lote.

Sem autorização de publicação, merge, envio WhatsApp, treinamento, cron ou despesa.
