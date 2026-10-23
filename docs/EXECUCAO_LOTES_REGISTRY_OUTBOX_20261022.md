# NIVON — Execução por lotes: governança editorial e outbox

Data-base: 22/10/2026 (local). PR #53: integração editorial + fontes + segurança.
**Status: desenvolvimento offline / draft, não homologado para publicação.**

## Ordem de execução e critérios objetivos

| Ordem | Implementação | Validação integrada | Estado |
| --- | --- | --- | --- |
| P0-A | Registry durável, raiz administrativa, cinco emissores independentes | manifesto assinado, identidade única, sem guardar chaves | IMPLEMENTADO OFFLINE |
| P0-B | Revogação assinada de emissor e consulta atômica pela outbox | aprovação antiga perde efeito e callback não é invocado | IMPLEMENTADO OFFLINE |
| P0-C | Integração consentimento/opt-out, provas, edição e reserva única | testes de escopo, SHA, expiração e opt-out entre fases | IMPLEMENTADO COM FIXTURES |
| P1-A | Testes E2E: SQLite em dois processos, interrupção, backup e replay | uma só reserva/callback, indeterminado sem retry | TESTADO OFFLINE |
| P1-B | Diagnóstico de bloqueios e CLIs locais de operação | snapshot redigido em SQLite read-only, simulação não mutável | IMPLEMENTADO |
| P1-C | CI final com toda a suíte, comparação de SHA e relatório na PR | 0 falhas no commit final, jobs externos identificados | EXECUTAR NO HEAD FINAL |
| P2-A | Identidade real de emissores, cofre, consentimento, licenças | homologação de provas de terceiros e segregação real | BLOQUEADO POR INTEGRAÇÃO |
| P2-B | Recuperação produtiva, backup/restore infra e transporte | testes de provedor e auditoria humana | NÃO ATIVADO |

O fluxo implementado é:
preparar template -> registrar edição ->
validar preflight, consentimento, direitos e as cinco provas ->
consultar registry de emissores provisionado administrativamente ->
registrar autorização -> verificar novamente registry e opt-out
sob lock SQLite -> reservar tentativa única ->
callback offline / reconciliação de status.

**Nenhum controlador desta etapa efetua POST à Meta.**
Os caminhos legados de envio direto permanecem bloqueados.

## Registro persistente de confiança

Módulo: src/nivon/registry_emissores.py

- Provisionamento inicial por manifesto de cinco emissores e assinatura
  HMAC da raiz administrativa. IDs, papéis e fingerprints das chaves
  são armazenados em SQLite; os segredos NÃO são armazenados.
- A raiz é fornecida externamente, não pelo texto do briefing. Um banco
  já provisionado não aceita nova instalação; revogação de emissor é
  assinada pela mesma raiz e irrevogável pela API disponível.
- Outbox descarta uma lista de chaves apresentada pelo remetente se ela
  divergir dos fingerprints de confiança. A consulta ocorre no
  BEGIN IMMEDIATE do registro de aprovação e no da reserva de envio.
- Após revogação, autorizações anteriormente assinadas são bloqueadas
  mesmo com os mesmos comprovantes, e o bloqueio persiste após reabrir
  SQLite. Não existe desbloqueio automático ou reenvio.

**Limitação estrutural:** o provisionamento inicial é um bootstrap TOFU
por chave raiz fornecida pelo operador. A validade externa dessa chave
e o controle de quem a possui não foram comprovados; em ambiente real,
uma raiz previamente estabelecida deve ser pinada/segregada com
governança de segredos. SQLite com administrador host comprometido não
é um cofre de confiança. HMAC não demonstra legitimidade dos fatos.

## Diagnóstico sem dados pessoais

Módulo: src/nivon/diagnostico_outbox.py

Entrega JSON redigido com quantidade de autorizações e bloqueios por
edição: opt-out, revisão/revogado, evidências ausentes, emissor revogado,
aprovação vencida, reserva já executada e envio indeterminado que exige
conciliação manual. Não contém telefone, corpo, payload, tokens ou
comprovantes brutos. NÃO oferece comando para habilitar envio.

CLI somente-leitura:

    PYTHONPATH=src python scripts/nivon_outbox_diagnostico.py --banco ./outbox.sqlite --somente-resumo

CLI administrativa offline:

    PYTHONPATH=src python scripts/nivon_registry_admin.py --acao resumo --banco ./outbox.sqlite
    PYTHONPATH=src python scripts/nivon_registry_admin.py --acao provisionar --banco ./outbox.sqlite --arquivo ./comando_assinado.json
    PYTHONPATH=src python scripts/nivon_registry_admin.py --acao revogar --banco ./outbox.sqlite --arquivo ./comando_assinado.json

Os dois últimos comandos são simulações SEM mutação por padrão.
Somente em ambiente offline administrativo autorizado: fornecer a raiz
em NIVON_REGISTRY_ROOT_HEX e acrescentar --aplicar para efetivar
a operação administrativa no banco indicado. O arquivo contém
{"manifesto":{...},"assinatura":"sha256=<64hex>"}.
Não colocar chaves em CLI, Git, logs, documentos ou conversas.

## Ensaios integrados

- tests/test_registry_e2e_offline.py: registro assinado, assinatura
  falsa, revisão de autorizações, revogação, key mismatch, reinício,
  diagnóstico sem PII, um callback SINTÉTICO e bloqueio de replay.
- tests/test_outbox_multiprocesso_backup.py: corrida entre dois
  processos POSIX sobre a mesma base com barreira, no máximo um
  callback, backup/restore de indeterminado e ausência de retry.
- tests/test_optout_global_outbox.py: opt-out antes/depois de edição,
  revogação permanente do destinatário, isolamento, persistência,
  proteção contra troca de chave HMAC e banco legado bloqueado.
- tests/test_provas_externas_outbox.py: cinco comprovações,
  independência dos emissores, correspondência ao SHA e bloqueio
  de provas revogadas, vencidas, falsas ou alteradas após registro.
- CLI exercitada por subprocess offline, sem HTTP nem escrita no modo
  de diagnóstico / simulação.

## O que ainda NÃO foi comprovado

- Nenhum emissor institucional real foi provisionado nesta etapa.
- Não há conexão com API Meta nem verificação de opt-in humano real.
- Nenhum documento de direitos de publicação foi homologado.
- O estágio "EVIDENCIAS_ESTRUTURAIS_COMPLETAS_OFFLINE" é APENAS
  integridade sintética e jamais implica autorização de envio.
- Não houve processo real de rotação/migração de chaves ou cofre
  de segredos na infraestrutura; o modo SQL com fingerprints não
  substitui gestão de identidade.
- Cinco jobs de inspeção de fontes reais em Actions normalmente são
  skipped; CI unitária/integrada não comprova os dados das fontes.
- Nenhum merge em main, cron, deploy, gasto ou envio foi executado.

## Próxima fase sem intervenção intermediária

Direção Técnica pode analisar este SHA e consolidar seu
contrato com a camada central de identidades. Para homologação real,
devem ser ligados validadores independentes de consentimento,
direitos e orçamento com controle efetivo de identidade, segredos,
permissões e trilha externa, exigindo autorização humana apenas
onde houver credencial, gasto, lançamento ou decisão irreversível.
