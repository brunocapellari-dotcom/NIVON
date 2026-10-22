# NIVON — Auditoria independente R08 de consentimento temporal

**Data:** 21/10/2026 (America/Cuiaba).  
**Implementação auditada:** [PR #95](https://github.com/brunocapellari-dotcom/NIVON/pull/95), SHA funcional `56ed88d6e83bbe5d893be9cf248094dfb7b3715b`.  
**Auditoria:** [PR #112](https://github.com/brunocapellari-dotcom/NIVON/pull/112), branch `audit/r08-consentimento-temporal-20261021`.  
**Teste:** `tests/test_auditoria_independente_consentimento_temporal_r08.py`, SHA `949e4851199623d51621ed0968511946558d4c4a`.  
**Evidência automatizada:** [run GitHub Actions 39698710033](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698710033); **2.051 testes; 2 falhas, 3 ignorados**. Quatro novos testes: dois controles passaram e dois adversariais falharam.
**Reteste do relatório:** [run 39698879625](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698879625), commit de documentação `7b9f5554b21b2b196d08a736af7dab936262412e`: **2.051 testes, 2 falhas e 3 skips**, os mesmos quatro testes auditados com dois controles verdes, duas reprovações e nenhuma falha incidental nova.

## NC-AUD-026 — P0: autorização não vigente aceita na reserva da outbox

`src/nivon/outbox_unificada.py` verifica assinatura HMAC do evento e ordem das decisões para **o mesmo destinatário**, mas registra `CONCEDIDO` sem exigir que a decisão já tenha ocorrido na linha de tempo relevante. Em `_consentimento_atual`, verifica-se apenas `estado == CONCEDIDO`; `reservar_na_transacao` recebe o instante `agora` mas **não confere `decisao_utc <= agora`**.

Com isso, mesmo um registro assinado por autoridade fictícia, com data **2099**, pode ser persistido como autorização vigente e usado em uma reserva sintética de 2026. Analogamente, uma concessão às **09h** valida reserva retrospectiva às **08h**. O HMAC está matematicamente correto; a falha é da **vigência temporal**, independente da criptografia.

### Resultados independentes

| Teste | Resultado |
|---|---|
| Concessão assinada às 07h, reserva às 08h, checagem pre/post | **PASS**: reserva permitida |
| Concessão 07h, revogação 07h30, tentativa de reserva às 08h | **PASS**: reserva bloqueada, nenhum registro |
| Concessão assinada para 20/10/2099, tentativa de reserva em 20/10/2026 | **FAIL**: sistema não bloqueou |
| Concessão assinada às 09h, reserva com `agora=08h` do mesmo dia | **FAIL**: sistema não bloqueou |

São **duas reproduções de um único defeito de cronologia**, não duas falhas independentes. O teste usa `sqlite3 :memory:`, dados sintéticos, HMAC exclusivamente de teste e nenhum destino/telefone real. Não faz POST, não aciona Meta nem algum ambiente de produção.

### Riscos e limites

- Testa integridade da autorização **antes da reserva**. Não comprova envio indevido efetivamente ocorrido em qualquer implantação.
- A aplicação declara corretamente `comprovacao_externa_homologada=false` e `envio_autorizado=false` na resposta de registro; isso é uma proteção parcial, mas `reservar_na_transacao` ainda aceita estado com timestamp futuro.
- Assinatura por chave de teste só comprova autenticidade em ambiente de teste. Consentimento real exige prova de titularidade, finalidade e adequação à legislação/termos da Meta.
- Corrigir a data no banco não resolve sozinho o risco de *race* entre revogação e POST externo; a própria implementação já registra essa limitação.

### Aceite técnico

1. Rejeitar decisão `CONCEDER` futura em relação ao relógio confiável do servidor e/ou mantê-la como não vigente. Evitar validação baseada somente na data do cliente que submeteu o evento.
2. No ato de reservar (`reservar_na_transacao`) e antes do POST (`verificar_consentimento_pre_post`), assegurar que a decisão comprovada de consentimento **precede o corte atual** e está vigente; proteger contra look-ahead mesmo em reprocessamento histórico.
3. Preservar a regra terminal de revogação e os bloqueios por canal/dia/destinatário. Testar simultaneidade de concessão, revogação e reserva em conexões SQLite concorrentes.
4. Não aceitar opt-in para outra finalidade/canal sem prova explícita de escopo conforme política real. A assinatura atual não incorpora finalidade, canal ou versão de aviso; exigirá análise de política antes de envio real.
5. Reexecutar os quatro testes independentes, suíte completa e relatório sobre SHA corrigido. Não promover para produção até evidência de consentimento real, ambiente protegido, revisão operacional e controle de custos.

**Veredito:** **REPROVADO para homologação de qualquer envio real (P0)**. A PR de auditoria contém somente testes e relatório; não houve merge, deploy, credenciais, consulta a contatos, envio WhatsApp ou dispêndio.
