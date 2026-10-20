# NIVON — Complemento da PR #8: WhatsApp e Radar editorial

Referência: 20/10/2026. Código em PR de revisão, sem deploy e sem envios reais.

## 1. Outbox WhatsApp (SQLite, mínimo de PII)

Módulo: `src/nivon/outbox_whatsapp.py` e testes:
`tests/test_outbox_whatsapp.py`.

- `registrar_edicao`: edição+destinatário (HMAC com chave externa)+template é único.
- O corpo e o número de telefone não ficam salvos em claro na tabela.
- `despachar_registrado` grava `ENVIO_INDETERMINADO` em transação SQLite
  **antes** de chamar o provedor, e não repete POST depois de timeout.
- `aplicar_status_assinado` confirma HMAC SHA-256 do `X-Hub-Signature-256`
  antes de aceitar statuses `sent`, `delivered`, `read`, `failed`.
- `vincular_ack_verificado` permite conciliar resultado incerto apenas com
  referência de evidência externa. Não é retry.
- Consentimento, conta Meta, template aprovado e autorização de custos continuam
  bloqueadores externos; resultado aceito pelo provedor não é entregue ao usuário.
- O módulo não é serviço HTTP/TLS implantado, nem scheduler, nem prova de backup.
  O SQLite precisa de armazenamento persistente e backup testado.

Documentação de webhook da Meta:
https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference
Página de referência da verificação da assinatura:
https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/

## 2. CDP: Belém e Vila do Conde

`lineup_cdp_santarem.py` foi estendido com `interpretar_cdp` para três portos:
Santarém, Belém, Vila do Conde. Fontes oficiais candidatas:

- https://www.cdp.com.br/programacao-de-navios-do-porto-de-santarem/
- https://www.cdp.com.br/programacao-de-navios-porto-de-belem/
- https://www.cdp.com.br/programacao-de-navio-do-porto-de-vila-do-conde/

O parser elimina placeholders vazios, distingue cada produto por linha, registra
a unidade presente no cabeçalho e recusa períodos antigos como line-up atual.
**WDT_ID não equivale a DUV.** Sem escala e data de publicação reais não deve
compor a contagem final de navios da edição diária.

## 3. Notícias: RSS e Atom, origem temporal e memória

Módulos `src/nivon/rss_radar.py`, `src/nivon/historico_noticias.py`.
Testes `tests/test_rss_radar.py`, `tests/test_historico_noticias.py`.

- Aquisição XML pela `FonteWeb` ocorre somente com direitos de coleta
  explicitamente aprovados; não há fontes RSS pré-ativadas.
- Parser offline de RSS/Atom rejeita DTD/entidades, documento inesperado,
  host de artigo fora da lista aprovada e notícia sem `published` original
  com hora e fuso. `updated` e hora da coleta não contam como publicação.
- Memória SQLite de GUID e URL canônica preserva a menor data de publicação
  observada, impedindo que republicação com `pubDate` renovado vire notícia nova.
- Somente hash/IDs temporais são persistidos, não o texto integral.
- O RSS é **candidato não classificado e não autorizado à publicação**.
  Um editor com fontes licenciadas ainda deve classificar, selecionar, auditar
  e gerar texto resumido para `briefing_diario`.
- A menor publicação observada no sistema não comprova a data original externa,
  especialmente antes da implantação do histórico.

## 4. Verificações e limites

Comandos locais, todos sem rede:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.diagnostico_portos
```

A suíte do núcleo passou com **730 testes, 5 ignorados** no SHA
`09442b892463ee8507e3c222f367e8a6862f506e`, antes de parte das novas
alterações CDP e Radar. **Não usar essa aprovação como evidência de que o
HEAD atual passou**.

A base da PR #1 recebeu novas alterações simultâneas (incluindo motores
científicos e controles de CI), causando divergências transitórias na PR #8.
Foi corrigido nesta branch o disparo indevido de inspeções com rede em PRs:
inspeções externas ficam restritas a `workflow_dispatch`, testes sintéticos
continuam executáveis em PR. É necessária uma sincronização completa das branches
e CI verde no HEAD final antes de qualquer merge/homologação.

Nenhum serviço pago, token, lote de WhatsApp, captura restrita, merge em main
ou deploy foi realizado neste trabalho.
