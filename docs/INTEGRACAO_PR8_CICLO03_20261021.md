# NIVON — Ciclo 03: PR #8 sobre integração #30

**Data de auditoria:** 2026-10-21. **Estado:** candidato de integração *draft*, offline; não é release nem autorização de coleta/envio.

## Proveniência e dependência
- PR #30 `53544dc65317535e8c0ba6fdf238fd8539d468ac` foi a base fixada desta rodada.
- PR #8 `79423add99a5b92186839d969f52d1eadf2f7501` foi a fonte; delta contra o ancestral `69edc2b6e0569ebd955a8f06a146e3f6fe4ecdfe`.
- Os 59 arquivos acrescentados à PR #8 foram incorporados por SHA de blob, sem reescrever conteúdos.
- Sete arquivos compartilhados: `.github/workflows/testes.yml`, os três contratos `config/fontes_nivon_master.v1.json`, `config/rotas_coleta.v1.json`, `config/lineup_escopo_nacional.v1.json`, e `src/nivon/briefing_diario.py`, `src/nivon/coleta_web.py`, `src/nivon/rotas_coleta.py`.
- Os três contratos JSON foram reconciliados por ID + campo usando o ancestral. Nenhum conflito de campo alterado pelos dois ramos foi encontrado. Resultado: **101 fontes, 139 datasets, 139 rotas e 45 portos cadastrados**, sem coleta habilitada.
- Código HTTP: MIME RSS/Atom/XML limitado, sem redirects, bloqueado por padrão; DNS/SSRF e inspeção de payloads reais continuam sem homologação.
- O validador de rotas mantém hosts oficiais adicionados pela camada científica (NOAA) e limita arquivos a 256 KB.
- O briefing mantém a marca editorial `RESUMO ESTRATÉGICO DO AGRONEGÓCIO` e omite seção de impactos. Preserva `fonte_id` na observação para proveniência.
- CI combina extras opcionais existentes e instala `openpyxl==3.1.5` para os testes dos parsers XLSX, sem ativar coleta de fontes.

## Gates de operação e duplicidade de outbox
O candidato contém **dois mecanismos SQLite distintos**:
1. `src/nivon/outbox_briefing.py` — registro/agenda do briefing por dia e destinatário, com estados e recibo.
2. `src/nivon/outbox_whatsapp.py` — registro do template/edição por destinatário HMAC, despacho reservado e reconciliação de estados via webhook.

**Decisão para este ciclo:** nenhum é despachante operacional. Não configurar ambos como caminhos paralelos de envio. Antes de ativar, a Direção Técnica deve definir **um único ledger de saída, um único caminho de chamada ao provedor e migração/adaptação documentada do outro**, com chave idempotente transversal por edição+destinatário+template. Não há integração E2E demonstrada entre os dois ledgers. Confirmar consentimento vigente imediatamente antes de eventual envio, opt-out e revogação, template aprovado, direitos de uso, idempotência ante timeout, autenticação de webhook e retenção mínima de PII. A presença de dois arquivos não constitui um sistema de entrega consolidado.

## Direitos, datas e semântica
- Catálogo com `collection_authorized=false`, `enabled=false`, `commercial_redistribution_authorized=false`. Rotas `runtime_enabled=false` e `scheduled_enabled=false`.
- Candidatos de páginas oficiais de porto não são feeds de line-up verificados: `endpoint_verified=false`, `parser_homologated=false`, `live_enabled=false`.
- Dados históricos ANTAQ não equivalem a fila atual. Publicação semanal ANP não equivale a download validado nem última cotação operacional. Fonte e hora da página não substituem data de referência do valor.
- Radar exige publicação original nas últimas 24h; cotação usa fechamento de mercado, janela própria e direitos. Não reutilizar notícias antigas como atuais.
- Nos fretes: divulgação de transportadora ≠ operação; preservar pontos e transportadoras individualmente; **nenhuma média municipal**.

## Testes e evidência
- Arquivo: `tests/test_integracao_regressao_pr8.py` valida quatro datasets históricos, 139 rotas, 45 portos, todas as políticas OFF, título e formato editorial e negação de fonte XML.
- GitHub Actions [39593775454](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39593775454), no HEAD `819be95b29822b53844c908511da0e4e944fc912`: **1.528 testes, 0 falhas, `OK`** (inclui testes offline e dependência Excel).
- A evidência acima precede esta nota documental; novo HEAD exige checagem própria.
- Não há nesta entrega prova de dataset real continuamente atualizado, licença comercial de redistribuição, AIS ao vivo, idempotência entre os dois ledgers, entrega WhatsApp, backtest empírico ou backup remoto.

## Próximos gates em ordem
1. Manter PR #40 draft e exigir revisão independente de direitos, SSRF/ZIP/XML/XLSX/PDF e fluxo editorial.
2. Consolidar contratualmente as outboxes em apenas um caminho de envio, sem serviço ativo e com ensaio de revogação/duplicidade.
3. Auditar PR #6 (Maritime), sobreposições com portos/line-up da PR #8 e contratos de AIS autorizados; integrar isoladamente e rodar CI.
4. Auditar PR #7 (IVO) e reconciliar sem promover previsões ou aprendizado automaticamente.
5. Testar E2E com histórico real autorizado, backups/restauração, custo e autorização formal antes de qualquer release.
