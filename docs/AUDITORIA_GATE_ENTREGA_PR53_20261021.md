# NIVON — Auditoria adversarial da fronteira de envio direto

**Data:** 21/10/2026
**Escopo:** PR #53 / branch de integração das PRs #8, #13 e #26.
**Estado de homologação:** offline; revisão por CI com fixtures. Nenhuma
integração Meta/Cloud API real, agendamento ou envio foi autorizado.

## P0 — envio de edição por função legada sem outbox

Arquivo: \`src/nivon/briefing_composto.py\`.

**Comportamento anterior:** \`solicitar_entrega(briefing, DireitoEntrega(...),
remetente=...)\` chamava diretamente o remetente com quatro flags positivas;
não conferia que o conteúdo do texto ainda correspondia ao SHA registrado.
\`CoordenadorNivon(auditor=lambda b: True)\` podia propagar essa chamada
com auditor booleano que não prova revisão independente.

**Evidência de reprodução:** testes adicionados em
\`tests/test_bloqueio_envio_direto_integrado.py\`; CI
[39654013720](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39654013720)
registrou três falhas antes da correção (envio com flags, auditor
simulado, texto adulterado).

**Correção:** \`solicitar_entrega\` agora devolve
\`BLOQUEADO_ENVIO_DIRETO_SEM_OUTBOX\` mesmo quando todas as flags
são positivas. Com direitos positivos, a rotina verifica ainda
\`PREPARADO_SEM_ENVIO\` e o SHA-256 do texto e rejeita divergências
antes de qualquer tentativa. O parâmetro \`remetente\` foi preservado
por compatibilidade, mas nunca é chamado.

**Evidência inicial da correção:** CI
[39654140079](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39654140079)
concluiu com sucesso os testes adversariais e a suíte existente.

## P0 — Cloud API de baixo nível liberável só por booleano

Arquivo: \`src/nivon/entrega_whatsapp.py\`.

**Comportamento anterior:** \`enviar_cloud_api\` aceitava
\`permitir_cobranca_e_envio=True\` e, quando um token/ID existiam,
podia realizar POST com \`urlopen\`, sem exigir reserva
\`ENVIO_INDETERMINADO\` previamente persistida em \`outbox_whatsapp\`.
Um timeout não impede cobrança/aceitação remota e um retry poderia
duplicar a edição.

**Evidência de reprodução:** teste adicional em
\`tests/test_entrega_whatsapp.py\` injeta somente token e provedor
fictícios, sem uso de rede externa; CI
[39654369448](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39654369448)
registrou uma falha antes da correção.

**Correção:** a função pública de despacho direto foi desativada,
inclusive se a flag positiva for fornecida; **não existe chamada HTTP
nessa função**. \`preparar_template\` permanece offline e conserva
verificações de opt-in/template; a outbox durável já existente segue
responsável pela reserva de intenção antes de *qualquer futuro POST*.

## Limites e próximas medidas

- Testes com funções simuladas verificam ausência de **chamadas**
  remotas. Não demonstram execução real do provedor, nem segurança
  completa de todos os demais caminhos de transporte.
- A outbox \`outbox_whatsapp.despachar_registrado\` aceita um callback
  injetado pelo chamador; sua governança ainda precisa ser integrada
  a uma revisão editorial e de direitos externa, por SHA da edição,
  autorização explícita da operação, opt-out e orçamento, com
  prova persistida antes da transição de estado.
- Não reabilitar a Cloud API direta apenas por uma flag booleana.
  Futuro transporte deverá depender da outbox durável e do gate de
  revisão independente.
- **Definição de concluído da segurança operacional:** testes E2E
  sem rede com interrupção antes/depois da reserva, replay, duplicação,
  mudança de conteúdo, falha de resposta, recuperação e evidência de
  autorização por edição; auditoria independente; direitos e consentimento
  documentados. Até lá, nada de deploy ou mensagens reais.

**Não confundir suíte verde com liberação do WhatsApp.**
