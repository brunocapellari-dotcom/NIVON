# NIVON — Mercados: confiabilidade de preços e avaliação de tendências

**Data de corte:** 2026-10-20  
**Escopo:** extensão incremental do PR #12 (não substitui o motor central).  
**Estado:** código offline, fixtures sintéticas; **sem fonte live, licença homologada,
dataset real, probabilidade certificada, deploy ou envio WhatsApp**.

## 1. Auditoria de cobertura existente

| Frente | Código inspecionado | Capacidade | Lacuna operacional |
|---|---|---|---|
| CME/CBOT | cotacoes_externas, tendencias_mercados, unidades_mercado | ajuste/fechamento por vencimento, conversão exata de grãos, tendência descritiva | contratação/entitlement de dados e calendário por contrato; séries longas |
| ICE | cotacoes_externas, unidades_mercado | conversão física indicativa de açúcar/algodão | contrato/grade, settlement, rolagem e autorização |
| Mercado físico | tendencias_mercados, cotacoes_briefing | comparação por município, unidade e natureza | praça real, qualidade, imposto, Incoterm, especificação e direitos |
| BCB/PTAX | ptax_plano, indicador_ptax | URL OData offline e seleção de boletim | ingestão durável de edições reais, data de publicação e calendário |
| Energia/diesel | anp_ppi, motores_agro_estrategicos | PPI e cenários de custo | harmonização ANP (S10/S500, produtor/revenda), EIA e unidades |
| Estatística | motor_tendencias, tendencias_mercados | Theil–Sen descritivo; consenso de cenários não calibrado | holdout temporal, séries point-in-time, skill e calibração |

Nenhum dos módulos citados representa um feed live ou resultado preditivo homologado.

## 2. Contrato canônico de preços (novo)

Entradas para nivon.qualidade_mercados.preparar_serie_precos:

- **Identidade:** mercado, produto, tipo, unidade; contrato AAAA-MM somente para
  futuro; localidade_ibge somente para físico; fonte_id e fonte_url HTTPS;
- **Valor:** preco como string decimal **positiva**, sem float como fonte;
- **Quatro datas:** competencia (AAAA-MM), data_referencia (AAAA-MM-DD),
  publicacao_em e coleta_em (ISO 8601 com offset); adicionalmente
  referencia_em (instante econômico com offset);
- **Proveniência:** edicao_sha256 em lowercase; revisão explícita opcional
  revisao_de_sha256 apontando para edição anterior visível, com publicação e
  coleta posteriores;
- **Corte:** as_of ISO 8601 com offset, depois da coleta da edição selecionada.

Controle de identidade impede misturar futuro/físico, contratos, produtos, praças,
unidades e fechamento/ajuste. A seleção de vintage ocorre por
(data_referencia, identidade e fonte). Conteúdos com mesmo hash só são
deduplicados quando preço, publicação e vínculo de revisão são compatíveis.
Revisões de preço sem cadeia declarada **falham em vez de serem arbitrariamente
substituídas**. O SHA é uma identidade declarada; conferir os bytes brutos no armazenamento do coletor é requisito externo. Não atribuir retroativamente conhecimento de edição: para
backtest histórico repetir a seleção sob cada as_of de origem.

O método tendencia_preco_auditada consome exclusivamente a série selecionada,
chama o Theil–Sen observado já existente e preserva publicavel=false. O limiar
de estabilidade é parametrizado em unidade/mercado, nunca universal.

**Limites atuais:** contratos permitidos de CME (soja, milho, trigo em USc/bu),
ICE (açúcar, algodão e café em USc/lb) e físicos nas unidades explicitadas
no código. A allowlist é mínima; não assumir que qualquer produto ICE usa a
mesma especificação ou que preço municipal representa negócio fechado.
Calendário oficial de pregão, timezone IANA da bolsa, settlement corrigido,
séries contínuas e metadata de feriados ainda NÃO implementados. O offset
explícito não prova que o provedor publicou no fuso correto.

## 3. Avaliação probabilística (novo)

nivon.validacao_tendencias_mercado.avaliar_probabilidades_tendencia avalia
**previsões previamente emitidas**, não fabrica previsões. Para cada registro:

- mesma serie_id e modelo_versao, regra_rotulagem, horizonte_sessoes e
  banda_relativa para toda a amostra;
- emitido_em posterior à disponibilidade do preço-base e anterior ao preço
  futuro, treinado_ate não posterior à emissão;
- valor_base e valor_alvo decimais positivos; classe_realizada recalculada
  por retorno (alvo/base - 1) e banda relativa declarada;
- alvo_disponivel_em e SHA da edição realizada verificáveis até as_of;
- probabilidades das três classes ALTA, BAIXA, ESTABILIDADE somam 1.

Avaliação **prequential**: o benchmark de frequência de classes com
suavização de Laplace em cada origem só utiliza desfechos já disponíveis
naquele instante. Métricas: Brier multiclasses, Brier baseline expansivo,
Brier Skill Score (positivo = melhor que benchmark), log loss, bins de
confiabilidade e ECE. Registros cuja evidência esteja além de as_of falham
fechado. Retorna publicavel=false e probabilidades_calibradas=null.

**Isso não demonstra por si só calibração ou edge.** Gate científico futuro:
dados reais e licenças; edições point-in-time conferidas com snapshots
independentes; split walk-forward e holdout final intocado; intervalos de
confiança por block bootstrap; comparação com random walk e benchmark
sazonal; ECE/Brier/Logloss por commodity, regime, horizonte, praça e contrato;
estabilidade de sinal, drift e revisão crítica. Não usar dados corrigidos
depois da decisão para reconstruir features retrospectivas.

## 4. Fontes, termos e priorização

| Fonte | Uso pretendido | Situação de direito |
|---|---|---|
| CME Group | CBOT soja, milho, trigo, vencimentos/ajustes | EXIGE avaliação contratual para acesso, uso não-display, IA/derivados e distribuição. https://www.cmegroup.com/market-data/license-data.html |
| ICE Data | açúcar, algodão, café e outros mercados ICE | EXIGE autorização para redistribuição inclusive cotações atrasadas e derivados. https://www.ice.com/fixed-income-data-services/data-and-analytics/quote-data-distribution |
| B3 | futuros agro, câmbio e derivativos brasileiros | REVER política válida em cada data; há distinção entre EOD D-1 e feed em tempo real. https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/distribuidores/politica-comercial-e-contratos/ |
| BCB PTAX/OData | compra/venda, boletins e fechamento | catálogo oficial público; registrar datas de publicação, latência e acesso. https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios |
| ANP dados abertos | diesel S10/S500, produtor/revenda e histórico | série pública oficial; preservar natureza de pesquisa, semana, produto e praça. https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis |
| EIA Open Data | petróleo, derivados, inventários e mercado energético | termos oficiais de API permitem análise e exibição sob condições e atribuição. https://www.eia.gov/opendata/terms-of-service.php |
| CEPEA | indicadores físicos agropecuários | site sinaliza CC BY-NC 4.0; **uso comercial do NIVON não está autorizado automaticamente**. https://cepea.org.br/indicadores/ |
| IMEA | preços e mercado MT | direitos/contrato específicos PENDENTES de comprovação; não inferir autorização por acesso ao site |

**Termos não são homologados automaticamente por este documento.**
Registrar evidence_id, titular, escopo de uso interno, persistência, criação
de derivados/treinamento IA, saída para WhatsApp e prazo de validade numa
matriz assinada pela governança. Todos os feeds continuam desativados.

## 5. Backlog aceito por esta frente

P0 — Normalização e deduplicação de vintages; testes de causalidade,
instrumento e precisão; avaliação temporal de Brier (neste PR).

P0 — Coletores aprovados para BCB/PTAX e ANP com bruto, snapshots, edição,
backfill e calendário; prova de publicação histórica; executar E2E autorizado.

P0 — Verificar contratos CME/ICE/B3/CEPEA/IMEA antes de ingestão comercial ou
briefing. Sem direitos, não publicar números dessas fontes.

P1 — Calendários de negociação e first notice/last trade, curvas forward
e rolagem ajustada; validação de especificações/currency/unit/tick de cada
mercadoria. Base/FOB/CIF/inland não intercambiáveis.

P1 — Modelos probabilísticos por commodity e horizonte (5/10/20 sessões e
semanal físico), walk-forward calibrado com referência de random walk,
métricas de estabilidade e decisão INDETERMINADA em baixa confiança.

P1 — Basis físico versus futuro em **mesmo produto/qualidade, referência,
moeda, unidade, data de mercado** e custos de localização explícitos.
Paridade de exportação com portos, prêmio, câmbio, frete, tributos
e custos (nunca equiparar conversão USc/bu a preço produtor).

P2 — Cross-commodity, coprodutos, volatilidade, skew e regimes,
cointegração com breaks estruturais, transm. de preço e elasticidades
com intervalos de incerteza e validação fora da amostra.

## 6. Limites de integração e testes

- CI: python -m compileall -q src tests
- CI: PYTHONPATH=src python -m unittest discover -s tests -v
- Novas regressões: tests/test_qualidade_mercados.py e
  tests/test_validacao_tendencias_mercado.py
- Sem novas dependências, rede, ambientes, secrets, scheduler, DB, envio,
  merge, deploy ou custo incremental.
- Integração de produção exige aceite das frentes Coletores, Estatística,
  IVO, Editorial, Governança e do PR central de integração.
