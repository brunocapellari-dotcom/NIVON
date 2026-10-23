# NIVON — R11 | Integração ANTT, consistência de outbox e recuperação independente

**Data:** 23/10/2026. **Estado:** PR #153 draft, sem merge/deploy/envio/coleta/custos nesta frente. Base: PR #126, commit `4c735bf4764e47edc47fdcbba5c85ca656b32780`.

## Prioridades executadas

| Prioridade | Código implementado | Validação |
|---|---|---|
| P0 | Importação de 9 arquivos ANTT MDF-e da main (módulos, scripts manuais, tests, docs) por blob SHA | Git diff sem conflito; CI da integração |
| P1 | `auditoria_outbox_integrada.py`: detecção read-only de divergências das duas filas | Registros órfãos, estados discordantes, ACK sem recibo, reuse de provider, consentimento ausente/revogado |
| P2 | `migracao_outbox_legada.py`: snapshot capturado sob `BEGIN IMMEDIATE` e digest de backup prévio conferido dentro da transação | Alteração entre backup e migração cancela staging; rollback inclusive do DDL de quarentena |
| P3 | `backup_outbox.py`: digest lógico V2 incorpora DDL de tabelas, índices, triggers e sequências | Mudança de schema vazio sem linhas invalida assinatura; restauração preserva digest |
| P4 | `lote_recuperacao_outbox.py`: inventário inclui auditoria estrutural; procedimento completo já utiliza snapshot esperado | Outro processo Python executa auditoria → backup → quarentena → novo backup → restore e compara provas |

## Origem dos novos componentes ANTT

A `main` foi inspecionada no SHA `f2552147f8732dcd2714faf85d0bc8fc82326e87`. Nove arquivos de implementação, documentação, CLI manual e testes de ANTT foram sincronizados SEM workflows agendados. Foram deliberadamente excluídos os cinco workflows novos/alterados da main, incluindo `antt-mdfe-catalogo.yml`, `cepea-neon-ingest.yml`, `conab-neon-ingest.yml`, `imea-neon-stage.yml`, `imea-publicacoes-monitor.yml`. Esses workflows já podem existir na main e seus agendamentos exigem revisão operacional própria; a presente PR não os alterou ou executou.

ANTT MDF-e representa **documentos fiscais de transporte e agregações com metodologia própria**, não frete negociado, nem todas as toneladas transportadas sem viés; os módulos não comprovam acesso real ou atualização. Nunca inferir volume transportado disponível apenas pela existência de metadados CKAN.

## Reconciliação de envios e governança de evidência

A nova função `auditar_integridade_envios` examina, em modo leitura, as relações entre `briefing_outbox`, `nivon_envios`, `nivon_consentimentos`, `nivon_reservas_canonicas` e `nivon_recibos_canonicos`. Classifica:

- Falta de tabela, reservas órfãs ou não correspondentes, intenções múltiplas dia/destinatário, ID de provider compartilhado entre registros, ACK que não aparece no ledger canônico.
- Divergências de `ENTREGUE` vs `ACEITO_PROVEDOR`, estado `LIDO` sem tempo autenticado de entrega (lacuna, não dado inventado), `PENDING` com reserva e inconsistência entre estado legado e canônico.
- Ausência de consentimento ou revogação persistente com registros/reservas ainda ativos, inclusive os legados que permanecem apenas preparados.

Retorna apenas contagens de anomalias. Zero anomalias **não** equivale a licença, autenticação da Meta, consentimento do titular, aceite externo ou autorização de publicação/envio.

## Garantia da captura no lote

O inventário de migração legado usado para o **staging** é obtido sob o mesmo `BEGIN IMMEDIATE` que grava a quarentena. A função `hash_snapshot_legado` obtém hash dos registros históricos antes do backup, e o estágio compara esse hash **depois de adquirir o lock**, falhando com rollback se outro processo alterar o histórico entre backup e captura. A criação da tabela `nivon_quarentena_legado` também fica dentro da transação; falhas não deixam registros nem novo schema como efeito colateral.

O digest de `estado_logico` foi reforçado para incorporar `sqlite_master` com SQL do DDL, índices e triggers, além de sequências SQLite e linhas. A documentação de R10 sobre checksum lógico deve ser interpretada conforme esta versão V2. Isso detecta alteração de schema mesmo em tabela vazia; não substitui criptografia/assinatura independente do backup nem IAM do armazenamento.

## Execução independente e testes

- Testes de integridade: linha legada adulterada após ACK, falta de opt-in, opt-out com reserva ativa, divergências de status e ausência de PII nos resumos.
- Testes entre processos: uso de `subprocess` para executar o CLI em outro interpretador, primeira leitura sem alterar base, segundo comando migra para quarentena e faz backup/restore, comando repetido não sobrescreve nem reenvia.
- Testes de restauração: dados de consentimento, reservas, recibos, filas legadas e staging são comparados antes/depois. Corrupção física e alterações de DDL geram assinaturas diferentes.

### Histórico de validação

- [CI inicial núcleo R11](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945370946): 2.119 testes, 0 falhas, 3 ignorados.
- [CI inicial de acessos R11](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945371269): 2.119 testes, 0 falhas, 35 ignorados.
- [CI após correção do digest lógico V2](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945804736): 2.120 testes, 0 falhas, 3 ignorados.
- [CI de acessos após correção V2](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945804587): 2.120 testes, 0 falhas, 35 ignorados.
- **Ressalva:** houve uma execução intermediária falha porque `sqlite3.Row` não é JSON serializável; normalização por `tuple(row)` corrigiu os seis erros decorrentes. O CI acima comprova a correção. O HEAD posterior à documentação precisa de nova validação.

## Bloqueios e próximos lotes

1. **R12 consolidação dos dados externos:** reconciliação do incremental IVO PAM, avaliação dos workflows CEPEA/IMEA/CONAB/ANTT existentes na main (frequência, credenciais, direitos, idempotência, cost cap, freshness) **sem disparar coleta real**.
2. **R12 migração para persistência:** avaliar PostgreSQL transacional com unique constraints, idempotência multi-instância, esquema migratório, teste de restore real e criptografia de backup por KMS; não configurar Cloud/Neon/Oracle com custo sem aprovação.
3. **R12 segurança de consentimento:** impedir contato após revogação recebida em outro processo durante POST, autenticar WABA/tenant e prova humana de opt-in. O HMAC sintético não homologou assinante externo.
4. **R12 performance/risco:** a auditoria atual limita leitura de cada tabela a 200 mil linhas; grandes bases exigem leitura paginada, índices, locks/isolamento de snapshot e streaming, sem copiar PII para logs.
5. **Divergências não autocorrigidas:** `auditar_integridade_envios` é somente leitura. Consertar `DELIVERED` legado, consentimento ou evidência demanda autorização e prova externa, nunca promoção inferida.
6. Nenhum dado do Drive histórico, painéis ANTT/IMEA ou fonte pública sem carimbo de competência/publicação/coleta deve ser tratado como série live nesta PR.

**Critério para produção:** testes CI sintéticos NÃO bastam. Exigem-se revisão independente, credenciais/autorização de fonte/WhatsApp, backup externo, hardening multi-processo, observabilidade, custos e decisão expressa de implantação.
