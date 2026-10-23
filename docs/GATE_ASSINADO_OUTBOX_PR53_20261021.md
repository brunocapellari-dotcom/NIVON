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

## Opt-out global e integridade da identidade HMAC — 21/10/2026

A outbox agora distingue duas operações **sem equivalência implícita**:

- `revogar_autorizacao` cancela **somente uma edição** já aprovada.
  Isso pode ocorrer por correção editorial e não constitui automaticamente
  desistência do recebimento futuro de mensagens.
- `revogar_destinatario` registra um **opt-out de destinatário**, mesmo
  que não exista edição anterior. O identificador HMAC do telefone e o SHA
  da evidência ficam gravados na tabela
  `nivon_optouts_destinatario`, sem persistir o número ou a evidência bruta.
  A operação é idempotente, persiste após reinício e só afeta aquele
  destinatário pseudonimizado. Não existe reativação automática.

O opt-out é testado dentro do `BEGIN IMMEDIATE` nas três fronteiras:
registro de nova edição, registro da autorização assinada e reserva da
tentativa de envio. Assim, uma edição já preparada e aprovada antes do
opt-out também é bloqueada caso ainda não tenha sido reservada. Não
existe garantia de cancelamento remoto depois que o POST tenha sido
reservado/aceito.

**Rotação de chave**: o HMAC do destinatário depende de uma chave
secreta estável. Trocar essa chave silenciosamente mudaria todos os IDs e
poderia ocultar opt-outs existentes. A tabela `nivon_identidade_hmac`
ancora apenas um fingerprint SHA-256 da chave (não a chave). Uma chave
diferente é rejeitada na transação de cadastro/opt-out; uma base legada
com registros ou opt-outs, mas sem fingerprint, também é bloqueada até
uma migração manual auditada. Não implementar re-hash de telefone sem
fonte original autorizada: os dados antigos foram pseudonimizados e
não permitem recuperar o número.

Os testes `tests/test_optout_global_outbox.py` cobrem:
- revogação anterior à primeira edição e posterior ao cadastro;
- autorização antiga sem efeito depois do opt-out;
- persistência após reinício, segregação de destinatários e idempotência;
- troca de chave e tentativa de novo cadastro/opt-out com outra chave;
- impossibilidade de assumir automaticamente a identidade de base legada;
- revogação **somente editorial** permitindo preparar nova edição, ainda
  sujeita a uma nova autorização de envio.

### Limites ainda abertos

Documentos de consentimento são representados por IDs/flags declarados
em fixtures. O projeto ainda NÃO acessou nem verificou independentemente
o registro canônico de consentimentos, as licenças ou a autoridade real
do aprovador; HMAC válido comprova integridade, não veracidade. É
necessário definir a identidade/segregação do serviço emissor das
evidências, a chave estável em cofre de segredos, o protocolo documentado
de eventual novo opt-in e migração de chave, e a governança de opt-out
entre outros sistemas/canais. Nenhum callback de teste autoriza
publicação ou mensagem real.

Status: implementação **offline e não comercial** sob PR em draft;
sem deploy, agendamento ou conexão com o provedor Meta.

## Cinco comprovantes de origem externa — 21/10/2026

O gate da PR #53 foi ampliado em
`src/nivon/provas_externas_envio.py` para não promover uma lista
autodeclarada de IDs ao estado de aprovação auditada.

Para cada edição, o chamador apresenta cinco comprovantes estruturados,
assinados via HMAC-SHA256, correspondentes a:

1. `REVISAO_EDITORIAL`: ID de revisão e SHA-256 do boletim.
2. `DIREITOS_PUBLICACAO`: ID da autorização de uso/publicação.
3. `CONSENTIMENTO`: ID do consentimento e destinatário pseudonimizado.
4. `TEMPLATE`: identificação da aprovação do template.
5. `ORCAMENTO`: identificação do orçamento aprovado.

A verificação exige um **emissor ativo diferente para cada natureza**,
chaves distintas entre os cinco emissores e diferentes da chave do
documento geral de aprovação. O registro de confiança
`emissores` é fornecido separadamente da mensagem e deve ser
administrado **fora do canal de produção do briefing**. Cada prova inclui
ID de evidência, tipo, ID de emissor, data da edição, chave de
idempotência, SHA editorial, destinatário HMAC, SHA do payload,
assinatura, estado aprovado e prazo de validade.

**A prova tem de estar válida no momento da reserva, e não apenas no
momento do cadastro.** O gate compara novamente todo o conjunto sob
`BEGIN IMMEDIATE`; um emissor desativado, prova expirada, assinatura
alterada, comprovante de outro destinatário ou edição, pacote duplicado
ou conjunto diferente do previamente registrado impede o callback.
A tabela `nivon_provas_externas` persiste somente o SHA canônico do
conjunto, vinculado à idempotência da edição, sem guardar comprovação
bruta, chave, número, URL de consentimento ou conteúdo editorial.
Registros legados sem esse SHA não podem ser enviados.

`tests/suporte_provas_outbox.py` produz credenciais e comprovantes
**estritamente sintéticos**, separados por emissor, que mantêm os
testes de timeout, webhook, revogação e multiprocesso. Os novos testes
`tests/test_provas_externas_outbox.py` verificam o bloqueio de prova
faltante/duplicada, emissor desconhecido/desativado, tipo e chave
incompatíveis, troca de destinatário, edição diferente, prova futura,
expirada ou revogada, substituição pós-registro, ausência de digest
legado e não persistência de evidências brutas.

### Limitação fundamental: verificação criptográfica não é fato independente

O registro de emissores **não foi provisionado com sistemas reais**:
não existe integração com cadastro oficial de consentimentos, revisão
humana, orçamento, Meta ou administração de contratos/licenças.
A função valida assinaturas contra chaves que recebeu como
configuração; ela **não descobre se um emissor é realmente confiável**,
se sua chave foi comprometida ou se sua autorização tinha base jurídica.
Os IDs das fixtures não são provas reais. Para homologação, o controle
de chaves e emissores deve ocorrer fora da execução que compõe o
briefing, com segregação de responsabilidades, política de rotação,
revogação atualizável e rastreabilidade independente de aprovações.

A PR permanece em draft. Não alterar o bloqueio dos despachos diretos,
não habilitar callback real, cron, deploy ou publicação automática
com base na aprovação da suíte sintética.
