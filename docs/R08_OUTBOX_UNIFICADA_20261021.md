# NIVON — R08 | Controle unificado briefing e WhatsApp

**Data:** 21/10/2026. **Estado:** branch draft, offline, sem credenciais de produção, sem deploy, envio, merge em main ou custos.
**Base:** PR #74 @ e71ae2adec44f732c324340f9c86d66a8114e7b7.

## Problema comprovado antes da mudança
- \`outbox_briefing.py\` mantinha SQLite \`briefing_outbox\` e restringia duplicatas por \`(dia_local,destinatario_hmac)\`.
- \`outbox_whatsapp.py\` mantinha \`nivon_envios\`, idempotência por \`(edicao,destinatario_hmac,template)\` e uma chave própria da preparação; ela permitia outro template na mesma edição.
- Os dois registradores não coordenavam slots de envio mesmo no mesmo arquivo. Uma chamada de \`enviar_cloud_api\` também poderia ser invocada diretamente, contornando a reserva comum. O campo \`opt_in_registrado=True\` na preparação do template não é prova verificável de consentimento.
- Metas operacionais: nenhuma duplicação entre canais, nenhum envio após revogação conhecida no instante de checagem, nenhuma retomada automática após timeout, nenhum texto/telefone/segredo armazenado na outbox.

## Implementações presentes
1. **Novo \`src/nivon/outbox_unificada.py\`:** tabelas \`nivon_consentimentos\` e \`nivon_reservas_canonicas\` em SQLite. A chave UNIQUE/PRIMARY KEY para reserva é \`(dia_local,destinatario_hmac)\`, independentemente do canal ou template. Armazena apenas hash opaco do destinatário, identificador da prova de consentimento, datas e estado. Não armazena telefone, mensagem, URL ou segredo. Revogação marcada \`REVOGADO\` é terminal por padrão e bloqueia reservas existentes \`RESERVADA\` (mantém registro para impedir duplicação).
2. **HMAC de concessão ou revogação:** \`registrar_decisao_consentimento\` exige prova HMAC-SHA256 que vincula ação, destinatário HMAC, evidência e instante UTC com chave externa de 32+ bytes. Rejeita replay conflitante, retrocesso temporal, renovação silenciosa e reativação após revogação. Uma assinatura não comprova que o titular da linha consentiu; serviço de consentimento, IAM, proteção da chave, auditoria e retenção ainda são requisitos externos. Nenhuma chave real foi usada.
3. **\`outbox_briefing.reservar_para_entrega\`:** lê o pedido legada, reserva \`BRIEFING\` no ledger comum e atualiza \`briefing_outbox\` na MESMA transação \`BEGIN IMMEDIATE\`. Sem consentimento, bloqueia e faz rollback. Nenhum envio é realizado por essa função.
4. **\`outbox_whatsapp.despachar_registrado\`:** valida o preparado/edição, reserva \`WHATSAPP\` na MESMA transação que altera o estado local para \`ENVIO_INDETERMINADO\`. Falha em caso de outro canal, template, consentimento ausente ou revogado. Sem retry automático de estado incerto; checagem adicional pré-POST. \`ACEITO_PROVEDOR\` não comprova entrega.
5. **\`entrega_whatsapp.enviar_cloud_api\`:** remove acesso direto sem ledger. Mesmo que \`permitir_cobranca_e_envio=True\`, exige conexão a arquivo SQLite durável cujo caminho corresponda a \`NIVON_OUTBOX_PATH\`, chave do destinatário injetada, edição/reserva/consentimento coerentes, estado \`ENVIO_INDETERMINADO\` com exatamente uma tentativa, e \`abridor\` explícito. Registra em \`nivon_api_dispatch\` um slot UNIQUE antes do POST. Não repete em timeout ou resultado indefinido. Não foi aberto HTTP real: teste executado com \`abridor\` sintético.
6. **Webhooks existentes:** as suítes de \`webhook_wsgi\` e \`whatsapp_webhook\` continuam passando. ACK de aceite e recibos de entrega mantêm semânticas distintas. Múltiplas tabelas legadas ainda existem, embora a decisão de **poder tentar transmitir** tenha um único ledger canônico. Isso é migração gradual, não eliminação física de todos os estados legados.

## Evidências de validação
- GitHub Actions [núcleo #39672290708](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39672290708): **2.044 testes, OK, 3 ignorados** no estágio de unificação do ledger.
- GitHub Actions [acessos #39672290732](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39672290732): **2.044 testes, OK, 35 ignorados**.
- GitHub Actions [núcleo #39672571492](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39672571492): **2.047 testes, OK, 3 ignorados** após gate da Cloud API.
- GitHub Actions [acessos #39672571410](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39672571410): **2.047 testes, OK, 35 ignorados** após gate da Cloud API.
- Regressões \`tests/test_integracao_outbox_unificada.py\`: ausência de consentimento, prioridade nos dois sentidos, template alternativo, revogação, assinatura falsa, persistência/reabertura, concorrência de duas conexões SQLite, Cloud API mock um POST apenas e bloqueio de banco diferente.
- Regressões existentes de briefing, WhatsApp e webhook foram adaptadas **somente** para provas HMAC de consentimento de fixtures de teste.

## Bloqueios antes de operação
- **Consentimento real e governança:** confirmação independente do opt-in e opt-out por usuário/identidade, comprovação assinada por serviço autorizado, validação de templates, rotação/revogação de chaves, política LGPD e requisitos da Meta. HMAC sintético é só prova de funcionamento criptográfico.
- **Persistência única:** ambas as filas têm de usar o **mesmo banco físico**, sob controle de transação, backup/restauração, chave HMAC estável para recipient e retenção. SQLite em múltiplos pods/volumes independentes não fornece a propriedade global; em nuvem considerar Postgres com UNIQUE transacional e locking, com migração validada. O gate de Cloud API nega path divergente.
- **Corrida de revogação:** a checagem pré-POST é local e **não é garantia instantânea** caso o opt-out chegue no intervalo antes/durante a comunicação com provedor. Antes de autorização real: implementar fila serializada por destinatário, supressão junto ao gateway e análise de atraso/reconciliação do provedor.
- **Transportes e credenciais:** validar controle de egress/DNS/TLS/proibição de redirecionamentos e autorização do aplicativo Meta. O \`abridor\` é injetado mas ainda não existe prova de sua conformidade; não enviar HTTP de produção.
- **Caminhos alternativos:** qualquer novo remetente deverá obrigatoriamente passar pelo ledger e não invocar diretamente adapters externos. O \`remetente\` de \`despachar_registrado\` é um callback controlado pelo chamador; suas ações externas ainda precisam de uma camada de permissão imutável/centralizada.
- **Webhook único:** reconciliar os dois adaptadores de eventos, assinatura Meta, IDs distintos e atualização do mesmo estado canônico; não tratar \`sent\` ou \`read\` como confirmação de \`DELIVERED\` no legado.
- **Replays e migração:** migrar historicamente reservas abertas nos dois bancos, eliminar duplicatas e garantir que nenhuma edição já enviada receba novo slot.
- **Gates transversais:** R06 egress, IVO/Segundo Cérebro, fontes reais e backtests mantêm suas pendências independentes.

**Política:** PR R08 permanece draft. Não habilitar Cloud API, enviar mensagem ou fazer merge/deploy sem auditoria e autorização específica.
