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


## 10. Integridade de âncoras e artefatos — continuidade 21/10/2026

### Recibo HMAC offline — `ancora_previsoes_mercado.py`

`verificar_recibo_ancora` verifica um recibo `NIVON_LEDGER_ANCHOR_V1`
com identificação de ledger/emissor, localização externa **declarada**,
sequência, cabeça SHA-256, instante com timezone, nonce hexadecimal de
128 bits e MAC HMAC-SHA256 contra chave de verificação de 32+ bytes
fornecida pelo operador. Envelopes com campos extras, reutilização em
outro ledger, MAC alterado, chave errada ou corte temporal inválido são
recusados. `auditar_ledger_com_recibo` compara MAC, cabeça, comprimento
do ledger e cronologia do último evento.

**Controle de fronteiras:** o emissor da assinatura não é implementado
neste módulo. O produtor do recibo e o detentor da chave **devem** ser
separados da instância SQLite; testes geram um MAC fictício.
HMAC usa segredo compartilhado (não equivale a assinatura assimétrica).
A função NÃO verifica existência/retentividade do objeto remoto, data
certificada, fonte de relógio independente, política WORM, IAM, rotação
de chave ou prova de autoridade do signer. Status de teste:
`MAC_RECIBO_VALIDADO_OFFLINE`, **não** `ÂNCORA_WORM_COMPROVADA`.

### Prova de bytes — `evidencia_bruta_mercados.py`

`preparar_precos_com_artefatos` recebe:
1. bytes originais `arquivo_original`;
2. bytes do `snapshot_jsonl` de **observações normalizadas**;
3. manifesto com os dois SHA-256, fonte, parser, versão, instante de
   captura e status `NAO_HOMOLOGADO`;
4. corte temporal as-of.

Confere ambos os SHA-256 calculados dos bytes recebidos; rejeita dados
após a captura, JSONL malformado, duplicação de chaves, valores não finitos,
fonte divergente, sobrecarga e preços float. Passa **somente as linhas
verificadas** ao contrato original `preparar_serie_precos`.
Não há download, integração de terceiros, autenticação do fornecedor ou
autorização de redistribuição.

**Limite metodológico decisivo:** o vínculo semântico entre os bytes
originais e sua conversão pelo parser NÃO é auditado por hashes dos dois
arquivos. Um parser que invente dados ainda consegue produzir um JSONL
com hash íntegro. Por isso, mantém
`fidelidade_parser_independente_verificada=false`,
`origem_remota_autenticada=false` e
`direitos_publicacao_verificados=false`.

### Auditoria E2E offline — `auditoria_e2e_mercados.py`

`auditar_previsao_ponta_a_ponta` confere, na mesma chamada:
- ledger SQLite íntegro com recibo HMAC e cabeça/quantidade correspondentes;
- previsão existente no ledger, originalmente encadeada;
- arquivo original e JSONL do **preço-base** capturados até
  `emitido_em`; do **alvo** capturados até `as_of`;
- identidade econômica integral, preço-base, SHA da edição, distância
  entre sessões e preço-alvo; cálculo do rótulo `ALTA/BAIXA/ESTABILIDADE`.

Produz um `item_backtest` como candidato a insumo do avaliador
probabilístico, nunca uma previsão nova nem calibração certificada.
Responde com `publicavel=false`, sem garantias fictícias de WORM,
licença, autenticação do mercado ou fidelidade do parser.
As regressões simulam adulteração do raw, do JSONL, do recibo HMAC,
troca de preço-base e capturas fora do tempo.

### Próximo gate de maior impacto

**P0:** autenticar origem real permitida e implementar a verificação do
parser contra amostras independentes de material de fonte autorizado,
incluindo catálogo de instrumentos/grades CME e ICE, e linhas RAW
rastreáveis com SHA/arquivo/posição por observação. Conectar assinatura
assimétrica/âncora WORM e recibos de timestamp independente em ambiente
separado, após validação do arquiteto de segurança. Em seguida,
executar E2E com vintages genuínos e avaliação walk-forward em janela
não usada no treinamento. Nenhuma dessas etapas foi simulada como
homologada.


## 11. Continuidade 21/10/2026 — auditor independente de linhas CSV

**P0 executado para um formato controlado, não para fontes oficiais.**

`src/nivon/auditoria_extracao_csv_mercados.py` implementa
`verificar_extracao_csv_canonico`, que usa a biblioteca padrão
`csv` separadamente do produtor do JSONL e confronta **todas**
as linhas, posições físicas e hashes SHA-256 linha a linha:

- Contrato `NIVON_CSV_CANONICO_V1`, versão 1; CSV UTF-8,
  separador ponto e vírgula, cabeçalho de campos canônico em ordem fixa,
  quebra LF obrigatória, sem CRLF, BOM ou campos multilinha.
  **Não é o formato oficial CME/ICE/CEPEA/BCB e não deve ser rotulado
  como parser oficial de qualquer fornecedor.**
- Cada JSONL contém todos os atributos do CSV e
  `raw_linha` (número inteiro da linha original) e
  `raw_linha_sha256` (SHA dos bytes integrais da linha incluindo LF).
  Contrato não permite inserção de campos inesperados, omissão de
  linhas, adulteração de preço ou troca de ordem.
- O confronto é **exato por valor e forma textual**, incluindo
  escala e identidade econômica da cotação. Os campos opcionais vazios
  se normalizam explicitamente para `null`; preço bruto decimal
  nunca vira float.
- Antes da análise, é exigido o duplo hash raw/JSONL do manifesto,
  origem/tempo de captura coerentes e o contrato existente de
  qualidade point-in-time, revisão e vencimento.
- Testes negativos recalculam deliberadamente os dois hashes depois
  de adulterar valores, omitir linhas ou falsificar posição.
  **Mesmo nesse cenário**, a checagem independente rejeita a
  conversão discordante. Testes cobrem preço físico com ponto,
  qualidade, entrega, pagamento e regime tributário distintos.

O `auditar_previsao_ponta_a_ponta_csv_canonico`, no módulo
`auditoria_e2e_mercados.py`, exige o mesmo controle estrito para
os pacotes de preço-base e alvo, além do registro ancorado, do
ledger, da reconciliação as-of e do calendário já auditados.

A saída `extracao_csv_canonico_conferida=true` comprova apenas
a equivalência entre dois artefatos **neste contrato controlado**.
Mantém `parser_oficial_mercado_validado=false`,
`parser_independente_verificado=false` (formato do fornecedor),
`origem_mercado_autenticada=false`,
`licenca_publicacao_verificada=false`,
`publicavel=false` e `probabilidades_calibradas=null`.

**Próxima prioridade P0:** selecionar uma fonte histórica pública
legalmente permitida com formato real documentado, preservar os
bytes tal como recebidos e a licença, implementar seu parser
especializado, travar schema/mudanças, conferir arquivo/posição
raw de cada preço, comparar com amostra independente e verificar
data de divulgação, unidade, revisões e calendário.
Para CME/ICE/CEPEA, bloquear redistribuição/WhatsApp até
validar expressamente os direitos e condições contratuais.
O assinador HMAC e a localização declarada também ainda
não constituem prova externa de WORM ou timestamp independente.


## 12. Continuidade de 21/10/2026 — PTAX OData no formato público BCB

**Auditoria de fonte oficial realizada:**
- Catálogo BCB: https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios
- Documentação/serviço: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao
- O catálogo declara licença Open Database License **ODbL** para
  o dataset de cotações diárias e descreve a PTAX de fechamento;
  verificar formalmente as obrigações de atribuição e
  compartilhamento da base derivada antes de redistribuir valores.
- O NIVON já possuía `ptax_plano.py` para construir consultas oficiais
  e `bcb_ptax.py` para normalizar JSON recebido; a resposta bruta
  desses endpoints era processada em `float` no adaptador preexistente.

**Novo componente offline:** `nivon.ptax_odata_bruta_mercados`.
`verificar_ptax_odata_bruta` aceita bytes JSON OData originais,
URL da consulta planejada, moeda USD/EUR, data de coleta, corte as-of
e SHA-256 esperado. Verifica:

1. Serviço HTTPS `olinda.bcb.gov.br`, endpoint OData de **período**
   adequado a USD ou EUR, argumentos de período obrigatórios,
   datas canônicas, `$format=json`, `$top=500`, janela <=20 dias,
   ausência de parâmetros duplicados/extras e de trocas de domínio.
2. SHA-256 dos bytes recebido versus digest **declarado** pelo coletor;
   limite de 2MB por corpo, UTF-8, JSON sem chaves duplicadas,
   `NaN`, `Infinity`, valores estranhos ou paginação implícita
   `@odata.nextLink`; nenhum lote de 500 linhas é considerado completo.
3. `value` do OData e cada cotação com `cotacaoCompra`,
   `cotacaoVenda`, `dataHoraCotacao`; `tipoBoletim` e paridades
   somente quando retornados. Valores JSON são convertidos
   **diretamente a Decimal**, mantendo escala textual original
   (`5.10000` não vira `5.1`). Valida compra <= venda,
   positividade, finitude, intervalo, duplicação e tipologia.
4. Hora da cotação sem offset explicitamente interpretada sob
   `America/Sao_Paulo` (regra operacional da ingestão),
   sem confundi-la com horário de publicação; coleta precisa ser
   posterior à referência e anterior ao corte. Boletim sem campo
   `tipoBoletim` **não recebe o rótulo de fechamento**.
5. Cada linha carrega sua posição exata no JSON original
   `/value/<index>` e SHA-256 do raw. O output diferencia PTAX
   `BRL/USD` ou `BRL/EUR` de cotação CME, ICE ou preço físico.

**Observação metodológica:** exemplos dos testes são estritamente
*fixtures sintéticas reproduzindo a estrutura documentada*. A API
live/HTTP não foi acessada nem resposta real coletada. Uma URL oficial,
um hash correto e uma licença aberta no catálogo não constituem
autenticidade independente da captura, conferência de publicação
point-in-time, nem liberação automática de redistribuição em WhatsApp.
Por isso o retorno permanece `publicavel=false`,
`origem_http_autenticada=false`,
`publicacao_independente_comprovada=false`,
`direitos_redistribuicao_homologados=false` e
`apto_backtest_por_publicacao=false`.

**Dependências/P0 para avançar:** capturar e guardar respostas HTTP
reais com cabeçalhos, TLS e data/hora confiável sob autorização do
coletor, verificar a interpretação do horário BCB contra amostras
oficiais e versão da documentação, provar o cronograma de
disponibilização histórica e as vintages relevantes; comparar
valores contra documentação original sem usar dados posteriores em
backtests. Integrar à base transacional e ao briefing somente após
normalização testada e revisão de licença/uso.


## Integração: tendência + dinâmica de CBOT e preço físico sob validação de vintages (21/10/2026)

Nova API `nivon.qualidade_mercados:dinamica_preco_auditada`, integrada ao manifesto dos motores `SOJA`, `MILHO`, `TRIGO`, `ALGODAO`, `ACUCAR` e `BOI` (todos os gates operacionais desligados).

O contrato é intencionalmente **fail-closed**. Antes de classificar perda de força, aumento de força ou reversão histórica, o adaptador:
1. Recebe observações **externas e já coletadas por meio autorizado**; verifica a identidade de cada registro com `preparar_serie_precos`: mercado/produto/vencimento/tipo/instrumento, ou praça/produto/qualidade/entrega/pagamento/tributação; fonte, precisão decimal e vintages com referência/publicação/coleta anteriores a `as_of`.
2. Seleciona até duas janelas de `janela` sessões **disjuntas**, sem preencher lacunas ou reconstruir contratos sintéticos; exige um calendário explícito da fonte, com edição e captura disponíveis no corte. A cobertura confronta todas as sessões das duas janelas, não só a janela final.
3. Alimenta o novo `comparar_forca_tendencia` e devolve `tendencia_atual`, `dinamica`, métricas descritivas, cobertura de calendário, identidade econômica canônica, quantidade de revisões/duplicatas e os flags `precos_homologados=false`, `direitos_publicacao_verificados=false`, `probabilidades_calibradas=null`, `publicavel=false`.
4. Sem calendário, devolve `INDETERMINADA`. Sem 2 × janela observações, devolve `DADOS_INSUFICIENTES` e não preenche pontos ausentes. Dados posteriores ao corte, revisão sem cadeia, diferentes vencimentos, instrumentos, pontos de coleta ou condição de entrega bloqueiam o cálculo.

**Atenção:** um calendário entregue pelo chamador não é prova de calendário oficial da bolsa. A presença de URL HTTPS, SHA fornecido ou cálculo reproduzível não comprova integridade de bytes brutos nem direito de publicação. Revisões e cortes passam por teste sintético, mas o histórico real e a licença continuam pendentes.

A dinâmica histórica não deve alimentar `probabilidades_calibradas` nem ser publicada como previsão futura. O backtesting probabilístico em `validacao_tendencias_mercado.py`, ledger/auditoria E2E e a auditoria de holdout quantitativo são mecanismos complementares, que só terão poder de homologação após evidências reais verificáveis e validação independente.

**Frete rodoviário:** o painel de valores por lotes/município não é estatisticamente equivalente à variação pareada por estabelecimento e transportadora. A frente de fretes deve consumir o motor pareado e o contrato de coleta da integração logística específica, sem usar preços não comparáveis como média de mercado. Este adaptador é exclusivo de cotações CME/ICE e indicadores físicos.


## 13. Continuação 21/10/2026 — cliente HTTPS PTAX opt-in + RAW em SQLite

**Contexto prévio encontrado:** `ptax_plano.py` planejava os endpoints
`CotacaoDolarPeriodo` e `CotacaoMoedaPeriodo`; `bcb_ptax.py` e
`pipeline_api_dados.py` normalizavam respostas OData para `float` e
salvavam apenas hash de snapshot e linhas normalizadas, sem preservar
o corpo HTTP. O ledger canônico de proveniência
`registro_snapshots.py` já possuía datas de coleta/versionamento,
controles de direito e a função `savepoint_atomico`. Esses módulos
foram **reutilizados**, não substituídos.

### 13.1. Coletor `captura_ptax_http.py`

`capturar_ptax_odata` valida um plano produzido integralmente pelo
planejador oficial interno, antes de realizar qualquer I/O:

- **Rede desabilitada por padrão.** O usuário da biblioteca precisa passar
  `permitir_rede=True`, catálogo com dataset `BCB_PTAX`
  explicitamente `enabled=True, collection_authorized=True`,
  autorizações `COLETA` e `ARMAZENAMENTO`, e referência de evidência
  de direitos para executar **um único** GET HTTPS.
- Host/operação/parâmetros/intervalo validados; context TLS padrão
  da biblioteca SSL, proxies de ambiente desabilitados, sem seguir
  redirecionamentos, sem retries, timeout 10 segundos, resposta
  HTTP 200, conteúdo `application/json`, `Content-Encoding` identity
  e limite de 2 MB. HTML/WAF, paginação inesperada e JSON inválido
  são rejeitados pelo verificador `ptax_odata_bruta_mercados.py`.
- Registra os **bytes originais exatos**, SHA-256, conteúdo e cabeçalhos
  HTTP selecionados, data de coleta com timezone posterior à leitura,
  URL canônica, valores em `Decimal`, posição `/value/N`, tipos de
  boletim e condição point-in-time. `Date` do servidor é armazenado
  apenas como cabeçalho, **não** como hora de publicação certificada.
- Para testes, permite função `transporte` injetada, mas a resposta
  sempre recebe `tipo=SINTETICO` e
  `origem_execucao=TRANSPORTE_INJETADO_SINTETICO`. Não permite
  mistura de `permitir_rede=True` com transporte injetado.
  Não há chave/API premium, navegador, login, scheduler ou deploy.

**LIMITAÇÃO:** o novo coletor não foi executado contra o BCB em rede
nesta rodada. A documentação e o catálogo públicos confirmam o
conceito e a ODbL (https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios),
mas o endpoint OData não pôde ser obtido/validado como payload vivo
pelo ambiente de pesquisa. A existência do código não implica
ativação das flags do catálogo.

### 13.2. Persistência `ptax_raw_sqlite.py`

- `guardar_raw_ptax`: reconfere SHA e conteúdo antes de salvar os
  bytes integrais na tabela `nivon_ptax_raw_blobs` e os metadados de
  cada captura na tabela `nivon_ptax_raw_capturas`. Associa ao ledger
  preexistente de `nivon_snapshots`/`nivon_coletas`, sob
  `savepoint_atomico`, com deduplicação por SHA e preservação de
  múltiplas datas de coleta do mesmo corpo, sem reescrever histórico.
- A função recusa mudança de classificação `SINTETICO`/
  `REAL_AUTORIZADO` sem origem e direitos compatíveis; autorização
  real também é conferida novamente pelo ledger canônico.
  **É o catálogo oficial do projeto** que deve autorizar coleta.
- `consultar_raw_ptax_asof`: retorna somente versões disponíveis até
  `corte`; ignora fixtures sintéticas por padrão, recalcula SHA
  dos bytes persistidos e refaz o parse direto do JSON bruto para
  retornar preços Decimal. Não atribui arbitrariamente data de
  publicação à taxa de câmbio.
- DDL `CREATE TABLE` usa `execute`, não `executescript`,
  para não confirmar transações abertas pelo chamador.
  Regressões comprovam rollback de dados **e da criação das tabelas**
  quando ambas estão dentro do mesmo savepoint externo.

**LIMITAÇÕES:** SQLite é persistência local, não WORM; metadados de
captura são declarados pelo chamador, e o relógio não é assinável.
Um chamador privilegiado pode forjar dicionários/mudar o banco:
isolamento do serviço, autenticação do transporte, IAM, prova de
tempo e ancoragem remota ficam em Infraestrutura. O ledger de
snapshots antigo usa `(dataset_id, sha256)` como unicidade;
se o **mesmo raw SHA** já houver sido classificado com outro
`schema_versao` ou `tipo`, a operação falhará por conflito
de metadados, sem migração/reescrita silenciosa. Esse caso exige
plano de migração versionada, não bypass do gate.

### 13.3. Testes e próximos controles

`tests/test_captura_ptax_http.py` e
`tests/test_ptax_raw_sqlite.py` cobrem rede off,
catálogo/direitos, endereço HTTP, bloqueio de HTML/WAF,
redirecionamento, MIME/codificação, tamanho e Content-Length,
revisão de clock, mock sempre sintético, consistência do raw,
idempotência, duas coletas do mesmo SHA, corte histórico,
alteração indevida do arquivo, rollback e transações externas.

**Próxima P0:** revisar as flags reais do Source Registry e as condições
ODbL, executar teste manual de uma janela pequena com o Banco Central
em ambiente permitido, manter amostras de headers e bytes capturados,
testar corte histórico; depois planejar migração controlada do adaptador
`float` para o caminho Decimal, sem quebrar consumidores do briefing
ou promover nenhuma taxa com data de publicação não comprovada.
Nunca ligar fetch em CI de PR nem automatizar até segurança/licença e
custos homologados. Toda saída segue `publicavel=false`.


## 14. Continuidade 21/10/2026 — histórico Decimal PTAX multi-captura (PR #21)

**Problema corrigido nesta etapa:** `consultar_raw_ptax_asof` retorna
uma captura RAW mais recente, não necessariamente o **boletim econômico
mais recente**. Uma resposta coletada por último pode conter uma
cotação de referência mais antiga que respostas anteriores. A seleção
de mercado e o cross-check devem, portanto, reconstruir os boletins
de **todas as capturas visíveis no corte**. A API legada de
`indicador_ptax.py`, baseada em floats, **não foi alterada**.

**Novo módulo:** `src/nivon/ptax_historico_decimal.py`.

- `selecionar_ptax_decimal_asof(db, corte, moeda, ...)`: somente
  leitura, sem criação de tabela, sem rede e sem side effects.
  Usa o ledger existente `nivon_ptax_raw_capturas`,
  `nivon_ptax_raw_blobs`, `nivon_snapshots` e
  `nivon_coletas`, conferindo IDs, SHA, referência, versão
  `PTAX_ODATA_RAW_V1`, tipo de origem e classificação de direitos.
  Bloqueia conjuntos excessivos (10 mil capturas / 100 mil boletins).
- Revalida cada body OData **nos bytes originais** com SHA-256 e
  parser `verificar_ptax_odata_bruta`, preservando decimais textuais
  (inclusive zeros e escala), data/hora da cotação, `/value/N`,
  data da primeira coleta conhecida e edição RAW.
- Identidade de observação `(referencia_em, tipo_boletim)`.
  Recapturas idênticas são deduplicadas preservando a primeira
  evidência de coleta; **taxas diferentes para a mesma identidade**
  retornam `VINTAGES_CONFLITANTES` até existir contrato formal
  de revisão, sem substituir valores retroativamente.
- `Fechamento` somente se explicitamente reconhecido no raw;
  `somente_fechamento=True` retorna
  `SEM_FECHAMENTO_EXPLICITO` quando ausente.
  Para seleção geral o fechamento explícito tem precedência,
  seguido da última referência temporal dos boletins elegíveis.
  Controle de idade (1 a 336 horas), sessões e timestamps
  evita vazamento de coletas posteriores ao corte.
- `indicador_ptax_decimal_raw` é uma **prévia isolada** do
  indicador de câmbio: bloqueia por direitos `LEITURA`/
  `PUBLICACAO_DERIVADA` quando ausentes; não utiliza registros
  SINTETICO; formata valores com `Decimal`, sem arredondar antes da
  seleção nem regravar o adaptador antigo. Para manter governança
  retorna `INDICADOR_RAW_PTAX_PREVIA_NAO_HOMOLOGADA`,
  `publicavel=false`, `apto_backtest_por_publicacao=false`
  e `publicacao=None`.

**Testes:** `tests/test_ptax_historico_decimal.py` cria snapshots
sintéticos no ledger real de teste e confere Decimal textual,
recapturas repetidas, documentos de coleta mais recente contendo
boletins econômicos antigos, conflitos de vintage, idade/corte,
alteração de bytes originais, fechamento explícito, tentativa de
promover fixture para `REAL_AUTORIZADO`, banco vazio e ausência
de direitos. O teste de parâmetros foi corrigido após a primeira
CI acusar duplicação de argumento na própria fixture.

**Evidência:** commit testado `ec13183b67dfcf0249a3f8c5e0d444bafbe9dad0`,
GitHub Actions [#39663550521](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39663550521):
`success`, **1.417 testes, 5 skipped, zero falhas**.

**Limites/gates abertos:** o pipeline `bcb_ptax.py` e
`pipeline_api_dados.py` continua baseado em float; a prévia
Decimal ainda não substitui nem alimenta por padrão o briefing.
Não há coleta real verificada nem histórico com publicação independente;
um relógio de captura não prova quando a taxa ficou pública.
O catálogo operacional, licenciamento ODbL/reutilização, assinatura
de tempo externa, integração ao workflow do IVO/editor e migração
controlada do legado permanecem pendentes. Sem merges/deploys/
automação/compartilhamento WhatsApp.


## 15. Continuidade 21/10/2026 — auditoria de migração PTAX legado/Decimal

**Objetivo:** verificar a paridade entre `indicador_ptax_sqlite`
(legado com `float` e apresentação em quatro casas) e
`selecionar_ptax_decimal_asof` (RAW+SHA+JSON `Decimal`) **antes**
de qualquer troca editorial. Não há modificação do adaptador antigo
nem mutação das tabelas, cronjobs, rede ou habilitação de feature flags.

### Contrato de auditoria e bloqueio

Novo arquivo `src/nivon/auditoria_migracao_ptax.py`:

- `comparar_indicadores_ptax(antigo, novo, moeda)`: compara
  representação com quatro casas do texto LEGADO, preço Decimal bruto
  com precisão original, `referencia_em`, instante de coleta, tipo
  explícito de boletim, origem, moeda e coerência das alegações
  `REAL_AUTORIZADO`. Se a parte Decimal tiver frações não representáveis
  a quatro casas, classifica divergência em vez de arredondar
  silenciosamente; **qualquer diferença de cotação** também bloqueia.
- SHA-256 idêntico + mesma coleta + valores e atributos equivalentes
  é `PARIDADE_NUMERICA_MESMA_EDICAO_OFFLINE`, um resultado relativo
  aos metadados e bytes persistidos **não prova de autenticidade
  externa nem de horário de publicação pelo BCB**. Valores numericamente
  iguais oriundos de SHA/coletas diferentes recebem
  `PARIDADE_NUMERICA_SEM_MESMA_EDICAO_COMPROVADA`, que
  **não libera o gate**. Ausência de um dos caminhos devolve
  `COMPARACAO_INCOMPLETA`; diferenças devolvem
  `DIVERGENCIA_PTAX_BLOQUEADA`.
- `auditar_migracao_ptax(db_legado, db_raw, ...)`: chama
  as funções preexistentes de leitura sem acesso de rede;
  exige direito `LEITURA` e `PUBLICACAO_DERIVADA` no
  mapa de fontes para sequer comparar os números. Ambos caminhos
  excluem `SINTETICO` por padrão. Pode receber duas conexões
  SQLite distintas para evitar colisão histórica entre os esquemas
  `PTAX_ODATA_1` e `PTAX_ODATA_RAW_V1` no ledger
  `UNIQUE(dataset_id, sha256)`.
- `auditar_lote_migracao_ptax(..., cortes=[...])`: avalia até
  32 cortes temporais canônicos, em ordem crescente e extensão
  limitada a 366 dias. Relata paridade observada por corte, gaps,
  edições distintas e bloqueios. Mesmo quando todas as amostras
  conferem, o estado é `PARIDADE_LOTE_OFFLINE_SEM_HOMOLOGACAO`.
  Se algum corte falhar, `LOTE_MIGRACAO_BLOQUEADO`.
- Em **todos** os resultados:
  `substituicao_automatica_autorizada=false`,
  `publicavel=false` e `apto_backtest_por_publicacao=false`.
  A comparação deliberadamente não injeta o novo dado no
  briefing/IVO e **não é** uma decisão de rollout.

### Evidência de testes

`tests/test_auditoria_migracao_ptax.py` cria dois bancos SQLite
temporários separados, um com o legado e outro com o RAW.
Para testar a porta real, é necessário criar uma fixture
`REAL_AUTORIZADO` **falsa exclusivamente em memória** com o
catálogo também simulado: isso **não deve ser entendido como dados
ou direitos reais concedidos**. Os testes cobrem mesmo SHA e captura,
SHA diferente apesar de valores iguais, alteração de compra,
precisão de cinco casas, divergência de referência/tipo, ausência de
novo raw, rollback temporal, direitos ausentes, exclusão de sintéticos,
adulteração no banco, alterações não persistentes e auditoria de múltiplos
cortes, com bloqueio de lacunas e edições distintas.

**Execução verificada:** [CI #39671854879](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671854879),
1.437 testes executados, cinco ignorados e zero falhas.

### Requisitos de homologação restantes

1. Capturar amostras reais BCB sob catálogo ativado, TLS e evidência
   de direitos ODbL avaliada, verificando também mudanças de contrato.
2. Comprovar origem e horário de coleta por mecanismo independente,
   dados de publicação quando disponíveis e armazenamento/restore.
3. Auditar datas de diferentes sessões/feriados e todas as categorias
   de boletins, contrastando bytes reais com o adaptador antigo;
   não usar a hora da cotação como se fosse hora de publicação.
4. Planejar migração de schema versionada e rollback dos consumidores
   legados **sem sobrescrever** snapshots antigos ou permitir
   dependência de cotações `SINTETICO`.
5. Aprovação humana explícita para alteração operacional do briefing
   e deploy. A autorização atual cobre apenas código reversível,
   offline, em PR draft e testes de custo zero.
