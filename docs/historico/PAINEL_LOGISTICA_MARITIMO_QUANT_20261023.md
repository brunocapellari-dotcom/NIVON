# NIVON — Entrega integrada: logística, marítimo e quantitativo (23/10/2026)

## Estado verificado e intenção

Esta entrega adiciona um **orquestrador analítico offline**, sem novo coletor,
sem novos datasets ou contas, sem Neon e sem gatilho de faturamento no Google Cloud.
Os insumos são snapshots gerados pelos módulos existentes. A análise é derivada,
sempre `SHADOW`, nunca automaticamente homologada. Testes usam exclusivamente
valores sintéticos, não comprovam que GCS/BigQuery foi executado em produção.

O estado real do NIVON na `main` em 23/10/2026 contém:
- MDF-e importado por recorte e ranking de polos em `inteligencia_corredores.py`;
- ANTT/SIADE ferroviário e verificações de fonte ANTAQ;
- `consulta_analitica_bq.py`, leitura temporal `as_of` de observações versionadas.
A reutilização do código avançado de AIS/line-up e dos anúncios de fretes
**ainda depende da consolidação dos PRs abertos**, sem conflito de versões.

## Um comando, três resultados isolados

```bash
python -m pip install -e .
python scripts/rodar_painel_operacional.py \
  --entrada tests/fixtures/painel_operacional_sintetico.json \
  --as-of 2026-10-23T12:00:00Z
```

Agora tambem ha uma **ponte executavel** sem pipeline paralelo:
- `corredores_sqlite: {banco, recorte, competencia}` chama diretamente o
  consultor MDF-e existente (alternativo a `corredores`);
- `consultas_bigquery: [{project_id, dataset_id, fonte, inicio, fim, classe,
  serie_id, limite}]` chama o leitor bitemporal NIVON existente.
  Sem a flag abaixo, somente planeja/valida e devolve
  `PLANO_SEM_REDE`. Respostas que atingem o limite de linhas sao
  recusadas para a tendencia; resultados sem serie/classe declaradas
  nunca sao automaticamente recategorizados.

```bash
# Mesmo comando; consultas reais somente com opt-in e IAM ADC/WIF.
python scripts/rodar_painel_operacional.py \\
  --entrada /diretorio/privado/pacote_com_consultas_bigquery.json \\
  --as-of 2026-10-23T12:00:00Z --executar-bigquery
```

A flag faz consultas **somente leitura**, porem pode consumir bytes
faturaveis no BigQuery. Usar exclusivamente destino privado ja
configurado, limite no leitor existente e orcamento GCP aprovado.
Ela nao cria dataset, tabela ou permissao.

A estrutura de entrada é um JSON com três chaves opcionais:
- `corredores`: saída íntegra de `consultar_corredores` (MDF-e; mesmo recorte);
- `portos`: snapshots AIS por porto com MMSI deduplicado, validação de
  geocercas, reconciliação física/operacional e **histórico do mesmo porto**;
- `series`: coleções de `observacoes` conforme contrato da consulta BigQuery,
  com `campos.serie_id`, `campos.classe` e as condições de comparação.

Todos os preços têm `data_referencia`, `data_publicacao`,
`data_coleta`, `identidade`, `valor`, `unidade`, `natureza` e
`campos`. Condições de transportadora, equipamento, regime, terminal,
origem, destino, produto e contrato não podem divergir dentro da mesma série.
Para `FRETE_ANUNCIADO`, apenas valores divulgados pela mesma transportadora
e condições entram na série; o maior anúncio do dia é usado, sem assumir
que é o mais recente ou foi efetivamente negociado. Para `CBOT`, o
contrato futuro é obrigatório. Observações sem publicação temporal verificável
ou coletadas/publicadas depois do instante consultado ficam de fora.

A tendência `ALTA/BAIXA/ESTABILIDADE` é uma classificação
**heurística das medianas em duas metades**, exige no mínimo seis dias
em ao menos sete dias de intervalo e frescor de referência, não uma
probabilidade calibrada. Ausência de dados é ausência, não preço zero.

No mar, o índice AIS provisório compara navios aguardando com 30+ pontos
do mesmo porto e exige geocercas validadas, MMSI únicos, conciliação
AIS×operação de pelo menos 95% e snapshot de até seis horas. Line-up
CDP não validado é apresentado como **não confiável** e jamais entra
no índice; mesmo um line-up validado só aparece como contexto. Nem
presença AIS no berço nem programação tornam um navio `OPERADO` ou
confirmam carga, tonelagem, DUV ou terminal contratado.

O bloco de corredores preserva o ranking do **único recorte** MDF-e.
Nunca soma MDF-e + TU ferroviárias + ANTAQ, nunca divide volumes
sem compatibilizar universo e período e nunca converte o município
de destino em um terminal de transbordo confirmado.

## Integração com Google Cloud sem duplicar pipelines

A tabela historizada e o loader existente continuam sendo a via principal:
coletor → RAW com SHA-256 no GCS → observação versionada no BigQuery
→ `consulta_analitica_bq.consultar(..., as_of=..., executar=True)`
→ adaptação explícita das observações ao pacote acima → motor → saída shadow.

Na ausência de fonte real, o motor retorna `DADOS_INSUFICIENTES`.
Este PR **não** cria cargas GCS/BQ, não executa Cloud Run ou cron,
não aciona coleta AIS/line-up, não publica sinais nem altera IAM.

## Prioridades de execução e testes em lote

| Gate | Tarefa de engenharia | Prova necessária |
|---|---|---|
| P0 | CI offline do novo contrato, CLI E2E em um único job | Três resultados num lote, bloqueios de tempo, MMSI, geocerca, frete e universo |
| P0 | Convergir PR #166 de estação ANTT com a `main` | TU por estação, MDF-e por município, sem alegação de transbordo |
| P0 | Consolidar PR #141 (AIS, line-ups CDP, reconciliação) e #150 (PDF isolado) | Backfill, escala/DUV quando confirmado, revisão as-of, segurança PDF |
| P0 | Consolidar PR #154/#146 (ledger fretes) e #82 (pareamento) | Sem duplicar anúncios, sem trocar condições/transportadoras, sem falsos movimentos |
| P1 | Adaptadores de saída das três famílias para o contrato do painel | BigQuery as-of real e rastreável + RAW/GCS verificado |
| P1 | Efetivar fontes por porto: Santos, Paranaguá, Itaqui, Rio Grande, Santarém, Vila do Conde, Itacoatiara, Suape, Imbituba, Ponta da Madeira | Linha de vida de escala por DUV quando existente, divergência CDP registrada; Amaggi Itacoatiara somente inferido por AIS |
| P2 | Baseline probabilístico de filas/ETA e tendências de frete/CBOT/físico | Backtests walk-forward point-in-time, erro MAE/calibração, comparação com baseline e intervalos empíricos |
| P2 | Promover indicadores após auditoria independente | Cobertura, frescor, performance fora da amostra, observabilidade, licença/custo e aprovação editorial |

**Não considerar concluídas** tarefas desta tabela só por estarem descritas.
A execução contínua depende de merges e credenciais/gates GCP que já existem
na governança do projeto e não são ampliados nesta entrega.


## Lote 2 — consolidação com a main e motores reaproveitados

Atualização incorporada sem conflitos a partir da `main` em
`f27a7eaf729ae7f5e979159c5b2a9b34c962ad76`. Os recursos novos da
base (série de corredores ferroviários, view de BigQuery, política GCP e
workflows associados) permanecem intactos. Esta branch acrescenta apenas
componentes destinados ao painel, com testes próprios; **não mescla**
a dependência Neon do PR #141 nem o histórico completo de PR #154.

A leitura de `ferrovia_staging: {pasta, ano, competencia, uf_origem}`
reaproveita `conciliacao_corredores_ferrovia.analisar_staging` e, junto
de `corredores_sqlite` ou `corredores`, gera
`conciliacao_intermodal` via `quadro_intermodal`. Também é permitido
`ferrovia` como saída pré-calculada para ensaio offline. É proibido
definir `ferrovia` e `ferrovia_staging` ao mesmo tempo. A comparação
relata toneladas ferroviárias e rodoviárias lado a lado com
`soma_entre_modais_permitida=false`; não converte registros em carga
efetivamente transbordada.

O pacote marítimo foi portado por hashes Git internos, preservando
testes dos módulos puros existentes no PR #141:
- `maritime_queue.py`: VQI e percentil local por porto;
- `maritime_queue_forecast.py`: baseline 6/24/48h de balanço
  chegada/atendimento com faixas de serviço, sem calibração probabilística;
- `maritime_source_health.py`: saúde do coletor separada de frescor da fonte.

O adaptador `maritimo_painel_avancado.py` não insere line-up
no índice: a variável de lineup do motor original recebe zero
exclusivamente como **neutralização de componente não validado**.
A estimativa de fila exige `saude_coletor`, `horas_espera_observadas`,
`taxas_atendimento_observadas_h` e
`chegadas_acumuladas_previstas: {"6": 2, "24": 5, "48": 9}`
(números ilustrativos, não dados reais); as chegadas são acumuladas
e devem ser não decrescentes. Sem amostras suficientes, retorna
`DATA_GATED` e previsões numéricas nulas. Qualquer índice, mesmo
validado em teste, é `SHADOW`, sem autorização de publicação.

Para tendência, os motores puros `motor_tendencias` e
`dinamica_tendencias` foram reutilizados da frente R09.
`dinamica_mercados_pit.py` valida identidade econômica e edição
original por fingerprint SHA-256 antes de chamar o método robusto
Theil–Sen, com duas janelas disjuntas, mínimo de 12 sessões e limiar
comercial explícito na observação. Os campos econômicos obrigatórios
incluem `ponto_embarque`, `pedagio`, `tipo_preco` e transportadora
para fretes, contrato e tipo de cotação para CBOT e praça/tipo para
preço físico. Metadados insuficientes não geram força nem reversão.
`dinamica_historica` nunca contém probabilidade calibrada nem sinal
de preço futuro.

### Critérios verificáveis da segunda rodada

1. Reutilização sem fork geral: Git blobs dos motores puros, sem
   migrar armazenamento ou infraestrutura antiga.
2. Testes de capacidade de filtro PIT, anomalias de preço, ausência
   de telemetria, cobertura de AIS, divergência CDP e competências.
3. Workflow `painel-operacional-ci.yml`: roda os testes dos módulos
   originais e os adaptadores do novo painel num mesmo job, além de
   executar a CLI E2E usando fixture sintética.
4. Dados reais do Google Cloud **não** comprovados nesta entrega;
   a flag `--executar-bigquery` somente autoriza leitura no destino
   existente e sujeito a IAM, orçamento e qualidade da fonte.

### Próximas entregas efetivas

- Leitura da view `vw_nivon_corredores_ferrovia_mensal` por competência,
  com filtro point-in-time, controles de bytes e reconciliacão mensal
  SIADE contra fonte primária;
- Ligar snapshots AIS/line-up de fonte autorizada ao adaptador, primeiro
  por lote privado e depois por agendamento Google Cloud;
- Importar e reconciliar o ledger de fretes pareados do PR #154 sem
  trocar ponto de embarque, terminal, regime ou pedágio;
- Backtest de previsão de filas por porto e de tendências de preços
  com vintages de dados reais, medidas de erro e gates de cobertura.


## Lote 3 — leitura operacional existente, sem cópia de banco

O novo `adaptadores_operacionais.py` entrega o primeiro contrato concreto
entre os dados de fretes/AIS dos coletores existentes e o painel integrado.
Não inclui pipeline de rede, scraping, acesso ao WhatsApp, chamada AISStream
ou escrita Google Cloud. Lê apenas entradas já autorizadas e persistidas.

### Dados de fretes anunciados

O pacote da CLI pode conter `fretes_consolidados` com a **saída integral**
de `fretes_registros.consolidar_ofertas` do ramo R09/#154. O adaptador:
- valida estado `FRETE_ANUNCIADO_NAO_CONTRATADO`, número de registros e
  identidade individual, e descarta publicações/coletas posteriores a `as_of`;
- separa séries **por origem e destino IBGE, ponto de embarque, transportadora,
  terminal, produto, equipamento, regime, pedágio, tipo base e provedor**;
- preserva `frete_base_brl_t` como anúncio em BRL/t; não transforma
  `frete_cheio_brl_t` em frete base nem remove pedágio;
- nunca inventa `fingerprint` do RAW. Sem SHA original nem banda técnica
  comprovada, a dinâmica histórica Theil–Sen fica **bloqueada**, embora a
  tendência descritiva simples possa ser analisada em modo SHADOW;
- preserva `fonte_id`, `provedor_id`, identificadores da oferta e
  `publicacoes_origem` sem assumir negociação efetiva.

Para não multiplicar dados, o consolidado é uma **entrada de processo**,
não outra tabela canônica. O conector R09 ainda precisa ser mesclado,
testado e conectado à persistência autorizada.

### Replay AIS de fonte existente

O pacote pode conter `replays_ais_sqlite`, uma lista de pedidos contendo
`banco`, `porto_id`, `inicio`, `fim` e, opcionalmente, `limite`.
Cada pedido abre o ledger `MaritimeStore` já existente em **mode=ro**,
sem criar arquivos, gravações ou reprocessar posição AIS. A leitura:
- é restrita a um único porto e janela de até 7 dias anterior a `as_of`;
- valida SHA-256 do JSON bruto por evento, MMSI, identidade e cronologia,
  e detecta truncamento antes de publicar contagens;
- diferencia eventos coletados, eventos `CONFIRMED_SEQUENCE` e MMSIs
  distintos nessas sequências;
- devolve `navios_aguardando`, `navios_operados`, DUVs e tonelagem como
  **nulos**, pois sequência AIS sozinha não comprova estado físico/serviço.

Assim, `replays_ais` é auditoria de qualidade/identidade independente
da matriz `portos`. Sem geocercas/reconciliação AIS × eventos oficiais,
**não** alimentar automaticamente VQI, fila ou ETA com números do replay.

### Exemplo do contrato de execução

```json
{
  "fretes_consolidados": {
    "natureza": "FRETE_ANUNCIADO_NAO_CONTRATADO",
    "total_registros_individuais_deduplicados": 0,
    "registros": []
  },
  "replays_ais_sqlite": [{
    "banco": "/dados/privados/nivon_ais.sqlite",
    "porto_id": "SANTOS",
    "inicio": "2026-10-23T09:00:00Z",
    "fim": "2026-10-23T11:00:00Z"
  }]
}
```

O trecho mostra apenas a **estrutura**: uma entrada vazia de fretes não
é processável. O lote E2E de testes gera registros sintéticos reais do
contrato de consolidado e um SQLite AIS temporário, executando
`scripts/rodar_painel_operacional.py` como subprocesso.

### Consulta econômica BigQuery escopada no servidor

Em `consulta_analitica_bq`, se `classe` e `serie_id` forem indicados,
ambos se tornam parâmetros de SQL. A consulta escolhe a versão admissível
point-in-time, filtra `JSON_VALUE(campos, '$.classe')` e
`JSON_VALUE(campos, '$.serie_id')` **antes de** `LIMIT`.
Isso impede truncamento indevido de uma série econômica por séries
diferentes armazenadas na mesma tabela de observações. O adaptador
recusa linhas retornadas fora do contrato, em vez de excluí-las
silenciosamente. Custo BigQuery limitado por `maximum_bytes_billed`
no cliente existente; sem leitura GCP real comprovada neste PR.

### Testes integrados

`test_adaptadores_operacionais.py` gera anúncios por ponto e transportadora,
um SQLite AIS com hashes reais de payload sintético, conferência RO,
duplicidade, fonte divergente, dado futuro, corrompimento e limite de eventos.
O E2E invoca a CLI de verdade, em um processo independente, e exige fretes
anunciados, replay AIS separado e publicação desabilitada.
`test_consulta_analitica_bq.py` comprova parametrização, posição do filtro
antes do LIMIT, série divergente e proteção contra injeção.

### Bloqueios restantes

- Dados reais de fretes e AIS ainda precisam ser produzidos pelos coletores
  com armazenamento e licenciamento autorizados, não por fixtures.
- Não está comprovada persistência contínua GCS/BigQuery para AIS/fretes,
  nem execução autenticada dessa leitura em projeto real.
- Prévia de fila 6/24/48h ainda não foi calibrada em dados reais por porto.


## Lote 4 — integração da ferrovia efetivamente carregada no Google Cloud

O GitHub documentou carga *real* ANTT/SIADE 2026 para o projeto
`nivon-data`, dataset `nivon_raw`, região `southamerica-east1`,
com conferência da carga pela workflow
`39983416188` e criação/consulta da view mensal em `39984168784`.
É a primeira fonte logística com leitura cloud e volumes verificados;
a mesma evidência **não** comprova AIS, fretes WhatsApp ou backfill dos anos antigos.

### Código

- Novo `nivon.ferrovia_painel_bq` consulta
  `vw_nivon_corredores_ferrovia_mensal` por competência, UF de origem,
  referência mensal e `as_of`. Query parametrizada, no máximo
  **50 MB faturáveis** e **1000 registros**; excedentes bloqueados,
  sem aceitar totais parciais como totais reais.
- Preserva `arquivos_sha256`, mercadoria literal da ANTT, classe de
  fonte primária, `linhas_fonte`, estação e polo por correspondência
  nominal exata. Valida explicitamente `transbordo_confirmado=false`.
- A resposta `polos_ferroviarios` integra-se à função existente
  `quadro_intermodal`, sempre lado a lado com MDF-e, sem somar
  toneladas entre modais ou inferir terminal físico.
- `ponte_painel_fontes.analisar_fontes` aceita
  `ferrovia_bigquery` sem concorrência com
  `ferrovia_staging` ou `ferrovia`. Em modo comum, devolve
  `PLANO_SEM_REDE`; com `--executar-bigquery`, usa ADC/WIF.
- **Cuidado com PIT:** a view ferroviária representa a versão **atual**
  selecionada pelo upstream. Filtrar `data_coleta <= as_of` não
  reconstrói necessariamente as versões que estavam disponíveis em
  um as-of histórico. Por isso `historico_pit_reconstruido=false`
  permanece explícito; não treinar walk-forward com essa view como
  se fosse histórico de vintages.

### Fluxo comprovável após integração na main

A workflow nova `nivon-painel-ferrovia-leitura-gcp.yml` roda
todos os testes da interface somente offline nos PRs. Em `push`
na main, autenticará via WIF GitHub OIDC com as **variáveis
preexistentes**, realizará **uma única** consulta BigQuery à
competência 2026-08 por meio da CLI do painel e salvará um JSON
de evidência com retenção de 30 dias. Nenhuma tabela, bucket,
credencial ou nova view é criada nesse job. No uso manual, só
consulta se `workflow_dispatch.executar=true`.

A suíte de testes inclui consulta com schema da view, integridade
dos hashes de arquivo, agrupamento TU exato por polo/mercadoria,
limite de leitura, bloqueio de fontes divergentes, retorno vazio
sem zero presumido, impossibilidade de somar MDF-e e ferrovia e
CLI completa. Os testes usam dados sintéticos; a prova de nuvem
dessa *nova* interface só deverá ser considerada concluída depois
de haver sucesso no job OIDC/BigQuery com artefato real.


## Lote 5 — execução real da leitura marítima no BigQuery (23/10/2026)

**PR #230 mesclado na main**:
https://github.com/brunocapellari-dotcom/NIVON/pull/230

**Leitura real com OIDC no projeto `nivon-data`, dataset `nivon_raw`**:
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40008847040

Resultado auditado na saída `NIVON_MARITIMO_READBACK_REAL`:
- **Imbituba**, fonte de programação: 5 revisões, 5 IDs de programação
  distintos. Natureza `PROGRAMACAO_HISTORICA_READONLY_SHADOW`.
- **PortWatch, passagem Panamá**: 4 revisões.
  Natureza `PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW`.
- O job verificou consulta autenticada, compatibilidade de origem,
  não publicação e ausência de atribuição indevida de carga realizada.
- Artefato: `nivon-maritimo-readback-40008847040`, retido até
  22/11/2026. Evidência limitada à janela consultada de outubro/2026.

As consultas passam por `scripts/rodar_painel_operacional.py`,
`ponte_painel_fontes.py` e `maritimo_painel_bigquery.py`, usando as
tabelas marítimas **já existentes**, sem criação de tabelas, bucket
ou recursos de cron. O leitor usa no máximo 35 dias por recorte,
1.000 registros e 50 MB faturáveis por consulta. A reconciliação
PortWatch elimina vintages repetidas no mesmo dia antes de agregar
estimativas. Uma consulta vazia é `SEM_DADOS_NAO_EQUIVALE_A_ZERO`.

**Bloqueio operacional ainda existente:** os 5 IDs não representam
5 escalas realizadas e não estão validados como DUV. Não existem
posições AIS por navio suficientemente conciliadas com geocercas e
eventos portuários nesse contrato de leitura. Por isso a ponte não
popula `navios_em_fila_ais`, nem tonelagem realizada, VQI ou ETA.
Para avançar é necessário disponibilizar eventos AIS historizados por
MMSI/IMO e horários + correspondência independente com eventos oficiais
(chegada, atracação, desatracação, DUV e porto/terminal).
Somente depois disso medir erros de previsão de filas e tempo de espera.
