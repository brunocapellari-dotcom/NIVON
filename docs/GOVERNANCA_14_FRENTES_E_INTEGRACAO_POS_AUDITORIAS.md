# NIVON — Governança das 14 frentes e integração pós-auditorias

**Data-base:** 2026-10-20  
**Status:** plano de execução; esta branch é isolada de `main`, sem deploy, ativação de dados, agendamento, redistribuição, envio WhatsApp ou novos custos.  
**Objetivo:** preservar integralmente as 14 frentes de trabalho enquanto todo o desenvolvimento converge para um **único SHA de release**, uma matriz canônica de dados e testes integrados.  
**Auditorias recebidas:** Claude (incluindo reproduções locais R01–R06, dependentes de reexecução), Gemini e Grok. Um parecer de auditoria é evidência a verificar, não autorização para operar.

## 1. Responsáveis lógicos e entregas

| Frente | Nome canônico | Entrega e fronteira |
|---|---|---|
| 01 | Direção Técnica e Integração | Integração de branches, dependências, contratos, decisão de release; nenhum merge em main sem revisão e autorização |
| 02 | Coletores e Engenharia de Dados | Fonte → direitos → RAW/hash → parser → schema → normalização → vintage → ledger → quality gates |
| 03 | Commodities e Inteligência Financeira | CBOT/ICE/B3, físico, basis, spreads, paridades, câmbio, preço por contrato/vencimento e direitos |
| 04 | Inteligência Agrícola | Soja, milho, algodão, trigo, sorgo, cana, gergelim e demais culturas; área, produtividade, progresso de safra, balanços |
| 05 | Inteligência Pecuária | Bovinos, bezerros, frango, suíno, abate, ração, exportação, sanidade e balanços biológicos |
| 06 | Meteorologia e Hidrologia | Estações, satélite, reanálise, modelos, FAO-56, hidrologia, previsão e verificação físico-temporal |
| 07 | Estatística e Motores Quantitativos | Tendências, invariantes, backtests point-in-time, modelos preditivos, probabilidades e drift |
| 08 | Logística Terrestre e Combustíveis | Fretes anunciados por estabelecimento e corredor; pedágio, diesel, ferrovia, hidrovia e relações intermodais |
| 09 | Inteligência Marítima | Line-up por porto/terminal/produto; AIS autorizado, geofences, port calls, filas, ETA, ANTAQ |
| 10 | IVO e Inteligência Geral | Planejamento, consulta, interpretação com evidências, conhecimento governado, aprendizado sem autopromoção |
| 11 | Inteligência Editorial e Briefings | Radar 24h, deduplicação, frescor de indicadores, quadro de cotações, corredores, envio somente via interface autorizada |
| 12 | Infraestrutura e Segurança | Persistência, concorrência, quotas, autenticação, backups, restore, supply chain, SSRF, segredos, observabilidade |
| 13 | Pesquisa, Ferramentas e Inovação | Reuso verificado AgroLog/GitHub e avaliação ADOPT/REPLACE/BENCHMARK/RESERVE/REJECT sem dependências redundantes |
| 14 | Auditoria, Testes e Qualidade | Reproduzir R01–R06, CI integrada, fixtures reais autorizadas, avaliação adversarial, gates e homologação independente |

**Regra:** cada frente pode trabalhar em paralelo quando há isolamento por contrato; toda alteração em IDs, schema, catálogo, motor compartilhado ou interface cross-domain deve ser reconciliada pela frente 01 e testada pela 14. O número 14 refere-se a frentes organizacionais, não a repositórios nem a serviços novos.

## 2. Freeze inicial de PRs para conciliação

| PR | SHA do HEAD auditado | Dependência indicada | Estado no levantamento |
|---|---|---|---|
| #1 | `662dbd5cdb685346ceba20d49953e8bf2508cb0e` | main | draft, base de integração |
| #3 | `fd9ac562223c1f144724cdd9c9d17babe7afd492` | #1 | draft |
| #6 | `016981641839d433a450c375df8cc46e1b416799` | #1 | draft |
| #7 | `a435b667b270dcc441fb564a1e3b9819be2449a7` | #1 | draft |
| #8 | `8f3ff5013e9dc25ce4c8bbbc680e145529de37e8` | #1 | draft |
| #9 | `e76e892d44407b0eca746ccc6ee215e5732b79d0` | #3 | draft |
| #10 | `b1a6ad1301cfc02c43728ba07e66d0a4f273b4d6` | #1 | draft |
| #11 | `62954bd8b18a34519032ff30998e88f642caa2a1` | #1, desatualizado | draft |
| #12 | `3191528d172a142c0208c1de4f33374fbd5cce28` | #9, mas não contém HEAD atual | draft |

PRs #2/#4/#5 estão fechadas sem merge; preservar o histórico e confirmar absorção de cada correção antes de aposentar módulos. Nenhum SHA acima autoriza operação real. A branch atual nasceu da PR #1; **não afirmar que as 9 PRs já foram integradas**.

## 3. Ordem técnica de execução

1. **Integração:** inventariar e reconciliar #3 → #9 → #12; #11, #7, #10, #6 e #8, respeitando dependências reais com `merge-base` e comparações de conteúdo. Não usar concatenação ingênua de JSON; consolidar por `dataset_id` e validar referências. Importar diferenças da branch `review/nivon-ciencia-base-20261019` apenas após diff/revisão.
2. **Frete — P0:** correção do efeito-composição da mediana por lotes; preservar `pickup_entity_id`, transportadora, produto, veículo, pedágio, destino, preço, datas e origem dos registros. **Proibido calcular/armazenar/exibir média municipal de frete**, mesmo no índice. Cenários com preços estáveis em cada fazenda não podem gerar ALTA FORTE apenas por mudança da amostra.
3. **Briefing — P0 de publicação:** rejeitar cotação vencida por indicador/mercado e calendário; notícias exigem publicação original nas últimas 24 horas. Recuperar Sorriso–Dom Aquino; corredor nacional e ponto de embarque não se confundem. Valor ausente ou bloqueado aparece como indisponível, jamais preenchido.
4. **Infra de dados:** um mecanismo canônico de tempo/UTC, unidades, direitos, HTTP seguro, contratos, transação SQLite com `BEGIN IMMEDIATE` quando pertinente, backup e restore independentes. Se Neon/Postgres for escolhido, manter adapter explícito em vez de persistências concorrentes.
5. **Coletas reais:** priorizar dados oficiais autorizados (BCB/PTAX, CONAB, IBGE, ANP, MDIC, ANA, INMET), preservar quatro datas, disponibilidade point-in-time, RAW com SHA e licença por operação. Nenhum endpoint de referência é automaticamente autorizado.
6. **Modelos:** balanços de conservação, baselines, separação de tendência descritiva e previsão; validação walk-forward com edições realmente disponíveis em cada data, incerteza/intervalos calibrados e rollback.
7. **Produto:** IVO, terminal, marítimo, radar e WhatsApp são consumidores de contratos homologados; publicação, redistribuição e envio exigem gates separados.

## 4. Defeitos reportados pelas auditorias — regressões obrigatórias

| ID | Achado e teste de aceite | Responsável |
|---|---|---|
| R01 | Mudança de composição das fazendas sem mudança de preço em cada uma não pode produzir alta artificial; não misturar municípios nem substituir lote por município | 07 + 08 + 14 |
| R02 | Cotação CBOT de 90 dias é rejeitada; Sorriso–Dom Aquino é aceito quando fonte/registro são válidos; dados velhos de notícias e preços seguem políticas temporais diferentes | 03 + 11 + 14 |
| R03 | Estresse de 16 processos e 48 escritas sem falha silenciosa; transações duráveis, comportamento de retries e isolamento documentados | 12 + 14 |
| R04/R05 | FAO-56, NSE/KGE, CRPS, fatores e unidades são verificados contra referências independentes; resolver duplicidade de implementação | 06 + 07 + 14 |
| R06 | XML, ZIP, HTML, XLSX, PDF e cliente HTTP testados com payloads hostis e limites; evitar seguir redirects/SSRF e nunca executar macros | 02 + 12 + 14 |

Outras lacunas: opt-out e revogação WhatsApp; duplicação de outboxes; ETA com escore heurístico ≠ confiança calibrada; múltiplos clientes HTTP; reuso e licença de código; versões de NCM por vigência; paridade diesel A/B; vulnerabilidades npm do cockpit.

## 5. Regras de controle

- Fontes: `observado`, `informado`, `estimado`, `inferido`, `projetado` e `simulado` não são sinônimos.
- Histórico: registrar `competencia`, `referencia`, `publicacao`, `coleta` + tempo verificável de disponibilização quando necessário; dado atual não simula vintage passado.
- Catálogo: `config/fontes_nivon_master.v1.json` e `config/rotas_coleta.v1.json` são bases de metadados; contagens devem ser derivadas do SHA, nunca fixadas em READMEs.
- Segredos/dados pessoais e séries restritas não entram no repositório público, logs nem fixtures.
- Nenhuma frente ativa agendamento, integra credenciais produtivas, habilita fontes restritas, cria custo, envia WhatsApp ou faz deploy sem os gates aplicáveis.
- Não confundir `CI_SUCCESS` com coleta real, `publicavel` com data freshness, `preparado` com `enviado` ou `enviado` com `entregue`.
- A auditoria é independente da execução. Um teste existente deve falhar antes da correção do defeito que pretende prevenir.
- Nenhum merge em `main` até testes integrados, auditoria técnica independente e autorização de release.

## 6. Definition of Done comum

Para declarar uma funcionalidade **OPERACIONAL** são exigidos: fonte/uso autorizados; pelo menos amostra real conferida onde aplicável; processamento e histórico reproduzíveis; schema/unidades/temporalidade/proveniência; controle de segurança; métricas e alertas; teste E2E; backup/restore quando persistente; custo dentro da autorização; logs e evidência da versão publicada. Para **PREDITIVA HOMOLOGADA** acrescentar validação fora da amostra e baseline por horizonte/regime.

**Status na criação deste documento:** apenas a branch isolada de integração e este plano foram criados. Conciliação de código, regressões, CI conjunta, migração de dados, deploy e operação permanecem pendentes.
