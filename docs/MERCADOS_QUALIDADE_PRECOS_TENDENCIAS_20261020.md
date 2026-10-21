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

Controle de identidade impede misturar futuro/físico, contratos, produtos,
unidades e fechamento/ajuste. Futuros exigem instrumento_id para separar
símbolos/espécies de contrato e vencimento. Físicos exigem
ponto_cotacao_id, qualidade_id, condicao_entrega_id,
condicao_pagamento_id e regime_tributario_id além do município IBGE;
**município não é ponto físico e não representa preço médio municipal**.
Esses campos são identificadores obrigatórios com reconciliação upstream:
strings declaradas NÃO certificam especificações oficiais ou qualidade real.
Séries com atributos divergentes falham, mesmo no mesmo município. A seleção de vintage ocorre por
(data_referencia, identidade e fonte). Conteúdos com mesmo hash só são
deduplicados quando preço, publicação e vínculo de revisão são compatíveis.
Revisões de preço sem cadeia declarada **falham em vez de serem arbitrariamente
substituídas**. O SHA é uma identidade declarada; conferir os bytes brutos no armazenamento do coletor é requisito externo. Não atribuir retroativamente conhecimento de edição: para
backtest histórico repetir a seleção sob cada as_of de origem.

O método tendencia_preco_auditada consome exclusivamente a série selecionada,
chama o Theil–Sen observado já existente e preserva publicavel=false. O limiar
de estabilidade é parametrizado em unidade/mercado, nunca universal.

### Calendário de sessões, lacunas e históricos extensos

O método agora exige `calendario_sessoes` para **classificar**; quando ausente,
retorna `CALENDARIO_AUSENTE / INDETERMINADA` sem falso sinal. O contrato
`nivon.calendario_sessoes_mercado.validar_cobertura_calendario` exige
mercado, fonte_id, edicao_sha256, publicacao_em, coleta_em e lista
cronologicamente crescente de sessões. Não permite sessões duplicadas,
observações fora da cobertura, coleta/publicação após as_of, nem lacunas
internas em uma janela descritiva. O código não consulta calendários oficiais.
A existência de SHA declarado e datas não prova que o calendário é genuíno:
**`calendario_oficial_comprovado=false`** em todas as saídas offline.

O armazenamento normaliza até 10.000 registros, enquanto a estimativa
Theil–Sen usa apenas as últimas `janela` observações após controle de
vintages e exige cobertura de todas as sessões dessa janela. O resultado
continua descritivo (não forecast). O contrato recusa decimais que seriam
zero ou infinito na ponte numérica float; o valor Decimal original segue
preservado separadamente, sem transformar preço histórico em negócio real.

**Limites atuais:** contratos permitidos de CME (soja, milho, trigo em USc/bu),
ICE (açúcar, algodão e café em USc/lb) e físicos nas unidades explicitadas
no código. A allowlist é mínima; não assumir que qualquer produto ICE usa a
mesma especificação ou que preço municipal representa negócio fechado.
Ingestão/validação independente de calendário oficial, timezone IANA da bolsa,
settlement corrigido, séries contínuas, verificações de holidays e metadata
de feriados ainda NÃO implementados. O offset
explícito não prova que o provedor publicou no fuso correto.

## 3. Avaliação probabilística (novo)

nivon.validacao_tendencias_mercado.avaliar_probabilidades_tendencia avalia
**previsões previamente emitidas**, não fabrica previsões. Para cada registro:

- mesma serie_id e modelo_versao, regra_rotulagem, horizonte_sessoes e
  banda_relativa para toda a amostra; calendário injetado obrigatório e
  contagem exata de sessões entre sessao_base e sessao_alvo;
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


## 7. Continuidade desta frente — 20/10/2026

**Correções novas:** comparabilidade físico por ponto/qualidade/entrega/
pagamento/regime fiscal; instrumento futuro explícito; calendário injetado
antes de classificar tendência; recusa de lacunas entre sessões declaradas;
janela robusta para históricos acima de 240 observações; proteção contra
float infinito/zero; regressões sintéticas dedicadas. Nenhuma dessas
alterações constitui conexão com mercado real ou licença.

**Concluído neste PR:** o backtest probabilístico só pontua previsões
com calendário declarado válido. Cada registro exige agora `sessao_base`
e `sessao_alvo`, conferidos com os instantes de referência no offset
fornecido, e `horizonte_sessoes` precisa ser exatamente a distância de
índices entre sessões do calendário. Sem calendário, o status passa a
`HORIZONTE_CALENDARIO_AUSENTE` (sem Brier/skill calculados), mantendo
`publicavel=false` e `probabilidades_calibradas=null`.

**Próxima ação P0:** ingerir vintages reais autorizados e firmar contrato de
integridade dos brutos, calendário oficial versionado e evidência imutável
de emissão de cada previsão; adicionar snapshot de previsão por origin time,
holdout temporal e auditoria de licença. Uma edição de calendário de revisão
posterior pode ser usada para verificação ex post de horizonte, mas NÃO pode
ser apresentada como feature conhecida na emissão de previsão histórica.
O calendário injetado é declarado, não validado contra fontes oficiais,
e nenhum Brier sintético comprova poder preditivo ou calibração comercial.


## 8. Continuação de 21/10/2026 — proveniência de previsões

Novo módulo `nivon.proveniencia_previsoes_mercado` (offline, sem dependências
externas) e `tests/test_proveniencia_previsoes_mercado.py`.

### Contrato de emissão e integridade relativa

`criar_registro_previsao` registra de forma canônica (JSON ordenado, SHA-256):
ID de previsão, ID de série **declarado**, versão do modelo,
identidade econômica integral (12 campos), `emitido_em`,
`registrado_em`, `treinado_ate`, sessões base/alvo e horizonte,
preço-base Decimal textual e SHA de sua edição, regra e banda de
rotulagem, tripla de probabilidades (ALTA/BAIXA/ESTABILIDADE) e
referência/hash da evidência de registro fornecida pelo sistema externo.
É obrigatório que `treinado_ate <= emitido_em <= registrado_em` e
que o registro seja anterior à data da sessão alvo.

Cada registro inclui `anterior_sha256` e `registro_sha256`,
permitindo uma **cadeia hash tamper-evident**. O verificador exige a cabeça
SHA esperada, que deve vir de uma âncora externa independente.
Verificação da cadeia detecta alteração de payload, troca de ordem,
truncamento de sufixo (diante de uma cabeça conhecida), duplicação
de IDs e anomalias temporais. Os registros de chamada são objetos comuns
de memória e **NÃO constituem armazenamento append-only, timestamp
confiável, assinatura digital ou imutabilidade verdadeira**.
A implementação retorna `ancora_externa_autenticada=false`;
uma string fornecida à função não autentica origem por si só.

### Reconciliação as-of

`reconciliar_previsao` verifica a cadeia e:
1. Seleciona apenas vintages cujo instante de publicação **e** coleta
   estavam disponíveis no momento da emissão;
2. Confere preço-base, SHA de edição, instrumento e especificação
   contra o registro encadeado, bloqueando revisões retroativas;
3. Obtém o preço-alvo com as edições conhecidas até o corte de avaliação;
4. Exige distância exata entre sessões declaradas no calendário injetado;
5. Recalcula a classe efetiva pelo retorno Decimal e banda originalmente
   comprometida, sem usar previsões de resultado posterior;
6. Produz `item_backtest` no contrato do motor
   `validacao_tendencias_mercado.avaliar_probabilidades_tendencia`.

O identificador interno de série do `item_backtest` deriva do SHA-256
da **identidade econômica completa**; um apelido igual não permite
agregar instrumento ou praça diferentes. O rótulo original permanece
como `serie_rotulo_declarado` para rastreabilidade.

As saídas mantêm `publicavel=false`, `probabilidades_calibradas=null`,
`previsao_historica_independente_comprovada=false` e o SHA da edição
alvo. A validação só prova coerência **relativa aos inputs recebidos**.
Não valida autenticidade da fonte, precisão do raw, evidência externa de
emissão, licenças, calendário oficial, escopo comercial nem existência
histórica independente da previsão. SHA declarado é insuficiente para
certificar o snapshot original.

### Próxima prioridade executável

Criar persistência de eventos append-only com controle de duplicidade,
constraint de ordem e exportação da âncora para armazenamento remoto
independente; a homologação desse armazenamento requer revisão de
segurança, prova de restore, IAM e autorização de custo, quando aplicável.
Em paralelo, preparar ingestão autorizada de cotações históricas PTAX/ANP
com raw verificável e vintages, e homologar calendário por exchange,
especificação de contrato e licenças. Depois: E2E de múltiplas previsões,
walk-forward com dados reais, benchmarks e auditoria de calibração.
Nenhum processo em produção foi habilitado.


## 9. Ledger SQLite de emissão — continuidade 21/10/2026

Foi incorporado `nivon.ledger_previsoes_mercado` e sua suíte de
regressões isoladas, com dependência exclusiva da biblioteca padrão Python.

- `inicializar_ledger(con)`: tabela local com chave de previsão única,
  sequência autoincremental, registro serializado canonicamente, hash da
  versão e hash anterior. Triggers locais impedem UPDATE e DELETE via SQL.
- `anexar_previsao(con, previsao, cabeca_atual_esperada_sha256=...)`:
  `BEGIN IMMEDIATE`, leitura e validação de toda a cadeia contra a
  **cabeça anterior declarada de fonte externa**, validação temporal,
  INSERT único e COMMIT. Falha provoca ROLLBACK, inclusive no caso de
  IDs duplicados ou cabeça defasada.
- `consultar_ledger(con, cabeca_esperada_sha256=...)`:
  reabre registros, confere colunas com JSON, ordem, conteúdo SHA,
  vínculos da cadeia e âncora fornecida pelo operador.

**Segurança real ainda não comprovada:** SQLite não é armazenamento WORM;
um administrador pode remover trigger/tabela, alterar diretamente o arquivo,
substituir timestamps e reescrever a cadeia. Sem âncora de SHA emitida e
armazenada independentemente do SQLite, sem timestamps assinados e sem
snapshot bruto verificável, não existe prova de emissão histórica.
Uma âncora obtida do próprio banco não vale como evidência independente.
O ledger não liga serviços nem provisiona cloud, só opera na conexão
SQLite explicitamente fornecida.

**Gate operacional seguinte:** atribuir ao subsistema Infraestrutura/
Segurança o desenho de exportação de cabeças para armazenamento WORM/
assinatura e relógio confiável com replay/restore ensaiado. Integrar
o ledger ao gerador real de previsões apenas após contrato e coleta
licenciados, idempotência de entrega/retry e testes de múltiplos processos
com falhas de energia e condições de corrida. Não afirmar `COMPLETED`
operacional nem `calibrado` com testes sintéticos.
