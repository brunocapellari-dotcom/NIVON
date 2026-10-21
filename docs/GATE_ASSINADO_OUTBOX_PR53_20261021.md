# NIVON — Homologação preliminar da outbox (gate editorial assinado)

Data-base: 21/10/2026. PR #53 em draft. **NÃO É autorização de operação.**

## Auditoria do risco P0

O código anterior de `despachar_registrado` exigia apenas
`autorizar_envio=True`, `custos_aprovados=True` e um callback. Um chamador
poderia reservar uma tentativa e invocar um adaptador arbitrário sem
comprovante editorial, consentimento ou direitos vinculados à edição.

Este risco permanece distinto dos dois caminhos legados bloqueados em
`docs/AUDITORIA_GATE_ENTREGA_PR53_20261021.md`.

## Implementação

- `src/nivon/autorizacao_envio.py`: documento de aprovação com
  canonização JSON determinística, HMAC-SHA256 de chave independente
  injetada pelo ambiente, hashes da edição/payload/destinatário e IDs
  estruturados de evidência: revisão, publicação, consentimento, template,
  orçamento e aprovador. Os flags devem ser estritamente `true`, a
  autorização deve estar `revogado=false` e ser válida por no máximo
  24 horas. Documentos assinados não conferem direitos automaticamente.
- `src/nivon/outbox_whatsapp.py`: registro explícito de autorização após
  registro `PREPARADO`, validação do texto e do SHA do briefing, pacote
  de preflight com `apto_revisao=true` e `bloqueios=[]`, vínculo
  do documento assinado à edição, destinatário HMAC e hash do payload.
  Persistem somente hashes, metadados sem PII e prazo, não o conteúdo ou
  o número de telefone.
- O despacho faz uma nova checagem do documento e do registro de
  aprovação **dentro do mesmo `BEGIN IMMEDIATE` que reserva a primeira
  tentativa**. Não pode ser burlado apenas informando bools positivos.
- Revogação explícita marca a aprovação como revogada e registra o SHA
  da evidência do opt-out em tabela específica, atomicamente. Repetir a
  aprovação não restaura uma revogação. Uma revogação após a reserva não
  cancela POST eventualmente já aceito no provedor.
- A Cloud API direta segue incondicionalmente bloqueada. Os testes passam
  somente callbacks sintéticos, sem qualquer solicitação de rede.

## Provas de teste e limitações

Os testes da outbox verificam:
1. Autorização ausente, assinatura adulterada e outra edição.
2. SHA editorial, payload ou destinatário divergente, incluindo tentativa
   de reutilizar o consentimento ou aprovação anterior.
3. Consentimento falso, expiração, revogação e reinício com SQLite durável.
4. Reserva antes do callback, falha/timeout deixando
   `ENVIO_INDETERMINADO`, replay bloqueado, conciliação humana de ACK
   sem reenvio e webhook de status assinado.
5. Não persistência de dados pessoais, textos, tokens ou evidências em
   formato bruto na outbox; somente hashes de controle e estados.

**Limitação importante:** integridade criptográfica comprova que um
detentor da chave assinou os campos; não comprova que esse detentor
era um revisor independente ou que o consentimento/licença eram válidos.
São necessárias validações externas, segregação real de chaves,
auditoria independente, vinculação com o registro de consentimento
do serviço WhatsApp, orçamento autorizado, backups testados e
homologação com a fonte. `preflight_editorial` offline isolado não
constitui autorização de distribuição.

## Pendências antes de qualquer go-live

- Prova externa de opt-in, revogação entre aprovação e reserva,
  revisor e detentor da chave segregados de serviços executores.
- Teste de banco real em múltiplos processos, com queda e recuperação,
  backup/restore e conflito de duas tentativas simultâneas.
- Integração de transporte apenas por outbox sob auditoria, com
  reconciliação de timeout/ACK antes de qualquer retry e validação de
  custo, região e contrato real do provedor.
- Garantir que aprovação seja concedida apenas a *dados reais
  homologados* e não a fixtures. Despacho real e cron continuam
  desabilitados nesta branch.

Status: implementação local/offline preparada para revisão técnica;
não chamar de `OPERACIONAL` até evidências E2E independentes.

## Ensaio de transação em processos separados

`tests/test_outbox_multiprocesso_backup.py` testa a mesma base SQLite em disco
com dois processos POSIX competindo pela mesma edição e uma barreira
sincronizada. O teste exige **exatamente um callback** e uma única tentativa
gravada; a outra chamada deve ser bloqueada pela reserva transacional.

O teste de falha após a reserva simula timeout, copia a base através da API
`sqlite3.Connection.backup`, restaura a cópia em uma conexão independente
e verifica que o envio continua `ENVIO_INDETERMINADO` com
`tentativas=1`, sem executar um segundo callback.

A verificação de expiração da autorização é repetida sob
`BEGIN IMMEDIATE` após aquisição do lock, para não aproveitar uma
autorização que expirou enquanto a conexão aguardava.

Isso demonstra propriedades **offline em SQLite no ambiente CI**,
mas não substitui teste de recuperação por falha abrupta real do
sistema operacional, armazenamento persistente em produção, sistema
de backups corporativo, exclusão de PII ou auditoria do provedor.
