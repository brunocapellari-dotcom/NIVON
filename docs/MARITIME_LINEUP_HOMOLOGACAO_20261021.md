# NIVON — Gate de homologação de line-up portuário (21/10/2026)

**Estado atual:** implementação offline testada com fixtures; **nenhum documento real, autorização de direitos ou homologação de fonte comprovados nesta PR**. `RELEASE_BLOCKED` e sem merges ou deploy. Não usar saídas em briefing, WhatsApp, API pública ou análise de carga realizada.

## Por que existe

Uma página de line-up **declara programação**, não comprova atracação, carregamento efetivo, volume realizado, comprador, rota AIS ou frete. O SHA-256 comprova correspondência entre bytes fornecidos e registro de conteúdo — **não** autentica sozinho a autoridade, o momento de publicação nem direitos de reprodução. Para evitar look-ahead em backtest, exigir competência, data de referência, publicação e coleta independentes.

Cadeia incremental: PR #1 → #6 → #15 → #29 → #31 → #38 → #44.

## Portos e contrato de extração

| Porto canônico | Autoridade/domínio permitido no código | Contrato existente | Observação |
| --- | --- | --- | --- |
| SANTOS | `www.portodesantos.com.br` | `HTML_SANTOS_SCHEDULE` | Exigir DUV, ETA com hora real e comparação do HTML original |
| PARANAGUA | `www.portosdoparana.pr.gov.br`, `portosdoparana.pr.gov.br` | `PDF_PARANAGUA` | Série obrigatória: EXPORT_OESTE, EXPORT_LESTE ou IMPORT_SOLIDOS; auditar cada série usada |
| ITAQUI | `www.portodoitaqui.com`, `portodoitaqui.com` | `PDF_ITAQUI` | Distinguir linhas ESPERADO/PROGRAMADO de FUNDEADO/ATRACADO; fonte PDF não comprova operação pela mera menção |
| SANTAREM | `www.cdp.com.br` | `HTML_CDP_BERTH_TABLE` | Verificar identidade oficial da escala no HTML e filtro de terminal |
| BARCARENA_VILA_DO_CONDE | `www.cdp.com.br` | `HTML_CDP_BERTH_TABLE` | Mesmo domínio institucional, porto canônico distinto; não misturar escalas |

Esses domínios são **configuração existente do código**, não declaração de que endereço específico, acesso, direitos ou edição documental estejam homologados. O `PilotSource.registered_url` deve apontar para o endpoint HTML exato ou para a pasta HTTPS de PDFs identificada e aprovada; um host autorizado **isoladamente é insuficiente**.

## Dossiê obrigatório de cada edição

Cada edição precisa de registros independentes dos seguintes campos:

- **Origem:** `port_id`, `source_id`, URL exata do documento, `parser_mode`, `series` (quando Paranaguá), MIME, tamanho dos bytes originais, SHA-256 computado sobre o arquivo original, identificador da aquisição autorizada.
- **Temporalidade:** `competencia` (YYYY-MM), `data_referencia` (YYYY-MM-DD), `data_publicacao` com timezone e **evidência externa**, `data_coleta` com timezone. Não imputar publicação pela coleta.
- **Extração:** linhas elegíveis para programação, linhas extraídas e rejeitadas, `parser_review_id` da comparação com o documento e `identity_review_id` comprovando DUV/ID oficial, ETA, porto, terminal e duplicatas.
- **Direitos:** evidência específica para COLETA, ARMAZENAMENTO e ANÁLISE INTERNA, status revisado, identidade de revisor, verificação e validade. Publicação, redistribuição, backup remoto e AIS possuem direitos próprios e **não** são liberados por este dossiê.
- **Revisões:** pelo menos **3 edições autônomas e diferentes por fonte/série**, com hash e coleta próprios. Revisões não devem ser sobrescritas. Desaparecimento de DUV não comprova saída, nem mudança de volume previsto comprova carregamento.
- **Qualidade:** confrontar contagem de escalas por `call_id`, preservar IMO como identidade do navio e **não** identificador único de visita; proibir mistura de portos e fontes; reconciliar mudanças de layout.

## Procedimento operacional sem rede

1. Obter legalmente os **documentos originais**, guardando proveniência e condições de uso fora do repositório de código. Não anexar material licenciado/PII ao GitHub sem permissão.
2. Executar o parser **existente** `processar_documento_porto` e, em HTML compatível, `bridge_official_html_document`. Para PDF, concluir validação de linhas, datas e DUV/IDs contra arquivo original; o gate não é parser de PDF.
3. Formar `LineupVintage` com os identificadores e quatro datas; exigir que todos os `LineupCall` pertençam ao mesmo porto, fonte e momento da edição.
4. Montar `EditionEvidence` com bytes originais, endereço cadastrado, provas de aquisição/revisão e registro de linhas elegíveis. Um documento incompleto não pode ser contado como edição aprovada.
5. Fazer auditoria separada das `OperationRights`. Um status `VERIFIED` só pode ser preenchido com verificação jurídica/autorização comprovada **externa ao próprio código**.
6. Rodar `audit_source` para cada contrato e `audit_pilot_portfolio` para a carteira dos cinco portos. Investigar códigos em `blockers`; não preencher IDs de evidência fictícios.
7. Se aparecer `READY_FOR_INDEPENDENT_REVIEW`, submeter arquivos, licença, parser, hash e resultados a revisão independente; **não** equivale a fonte HOMOLOGATED, liberação operacional, concessão de direitos ou permissão de divulgar.
8. Após revisão independente e autorização de infraestrutura, avaliar persistência no `LineupVintageLedger`, reconciliação AIS sob licença própria, backtest OOS e sete dias de ensaio operacional antes de discutir release.

## Estado objetivo nesta rodada

- [x] Gate determinístico offline implementado, com bloqueio de formatos, domínios, URLs fora do registro, hash divergente, direitos ausentes/expirados, data futura, fontes incompletas e menos de três edições independentes.
- [x] Cinco portos explicitamente definidos; série obrigatória para Paranaguá.
- [x] Testes com fixtures sintéticas, sem acessar a rede e sem reivindicar resultados com arquivos oficiais.
- [ ] **0/5 portos com três edições reais verificadas no escopo desta PR.**
- [ ] Ausentes evidências jurídicas verificáveis para cada operação/fonte e revisão externa.
- [ ] Ausentes validação real dos PDFs de Paranaguá/Itaqui e reconciliação entre arquivos de layout distinto.
- [ ] Sem integração à produção, liberação para publicação, ingestão AIS comercial ou serviço de backup remoto.

> Segurança: `EditionEvidence.evidence_kind="OFFICIAL_CANDIDATE"` e `OperationRights.status="VERIFIED"` são **declarações de entrada**, e não certificados emitidos pelo NIVON. A saída máxima permanece `READY_FOR_INDEPENDENT_REVIEW` e `release_allowed=false`.
