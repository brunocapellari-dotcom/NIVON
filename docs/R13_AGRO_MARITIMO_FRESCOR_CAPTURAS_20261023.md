# NIVON — R13 | Integração agrícola/marítima e rastreabilidade de recoletas

**Corte do desenvolvimento:** 23/10/2026. **Status:** PR #211 draft sobre PR #194. Sem merge, deployment, GCP live, Cloud API, webhook, scraping ou custo externo nesta frente.

## Priorização e execução

| Frente | Código entregue | Teste relevante |
|---|---|---|
| P0: integração | 29 arquivos originais da main no SHA `53d70c8d95971e7501fc42cb57d183fce0affb98`, por SHA git | CI de todos os módulos, sem incorporar workflows agendados |
| P1: CEPEA/IMEA/CONAB | Leitura/normalização de CEPEA físico, metadados IMEA, safras CONAB, ledger local e preparação GCP | RAW e observações, duplicação, data futura, quarentena, publicação não convertida em referência |
| P2: marítimo | Cadastro e parsing de line-ups, histórico e execução em lote, parser PortWatch | CDI/CDP com reconciliação, AIS Amaggi INFERIDO, sem programado→realizado |
| P3: segurança | CEPEA via `HTMLParser` padrão, egress implícito proibido tanto em CEPEA quanto em marítimo | Regressões de URL, HTML hostil, parser sem `beautifulsoup4` e ausência de transporte |
| P4: rastreabilidade | Eventos de recoleta `capturas_fonte` e `auditoria_frescor_agro.py` | SHA RAW, coleta recente vs referência antiga, nova coleta de mesmo arquivo, banco legado sem backfill |
| P5: evidências | Documento, CI integrado e atualização de PR | Repetir CI sobre HEAD final |

## Fonte e direitos: não confundir existência do código com coleta homologada

Os 29 arquivos incluem módulos `cepea_web_primario.py`, `imea_publico.py`, `imea_lotes.py`, `conab_publicacoes.py`, `conab_safras.py`, `conab_job.py`, `agro_origem_gcp.py`, `ingestao_fontes_reais.py`, `arquivo_raw_gcs.py`, `lote_cloud_recuperavel.py`, `carga_bigquery_fontes.py`, `agro_staging_bigquery.py`, `lineup_portos.py`, `maritimo_pipeline.py` e seus testes. O script operacional `scripts/coletar_agro_google_cloud.py` foi incluído **como código**, mas não foi executado. Os workflows de cron da main não foram importados.

**CEPEA:** séries devem preservar série, praça e unidade; preço físico não é uma média municipal de fretes. Data de referência e data da coleta são distintas; a data de publicação continua NULL quando desconhecida. A indicação de licença CC BY-NC no código de origem **não é prova de autorização comercial**. Publicação é sempre bloqueada até revisão de direitos e finalidade.

**IMEA/CONAB:** publicações e levantamentos sem data de referência por célula permanecem em QUARANTENA. Não usar `data_publicacao` como se fosse referência/competência. Consultas e normalizações reais pelo agrobr precisam de credenciais/direitos aplicáveis, e GCS/BigQuery requerem autorização separada, idempotência e evidência de dados efetivamente persistidos.

**Line-up:** Suape, Imbituba e Ponta da Madeira estão no catálogo. Santarém e Vila do Conde, quando oriundos da CDP, exigem reconciliação; Itacoatiara público é separado de Amaggi. Escala Amaggi obtida por AIS/geocerca fica explicitamente inferida. Em todos os casos: PROGRAMADO, ATRACADO e REALIZADO não se confundem.

## Segurança de rede

- `cepea_web_primario.consultar_pagina_primaria()` exige `open_url` injetado. Sem um transporte homologado, retorna `EGRESS_CEPEA_NAO_HOMOLOGADO`, sem conexão externa.
- `maritimo_pipeline.baixar_html()` exige `habilitar_rede=True` E transporte injetado com `open()`, senão bloqueia por `EGRESS_MARITIMO_NAO_HOMOLOGADO`. O fato de ser injetado **não garante** DNS/TLS/SNI, IP pinning, bloqueio anti-redirect ou licenciamento: homologar na camada de egress antes de live.
- O extrator CEPEA agora usa `html.parser.HTMLParser` da biblioteca padrão. A regra associa tabelas às seções de título do indicador; tabela ausente, ambígua, repetida, com data futura ou preço ilegível falha fechada. Mudança do HTML oficial deve gerar nova fixture e auditoria antes de confiança.

## Evento de consulta separado de conteúdo novo

Em `ingestao_fontes_reais.py`:
- `snapshots` preserva conteúdo original por `(dataset_id,SHA256)`; dados idênticos não são regravados como preços novos.
- A nova tabela `capturas_fonte` registra **dataset, snapshot, instante da nova consulta e URL de origem**, com UNIQUE por dataset+snapshot+instante. Reconsultar a mesma página em outro horário grava um evento novo, mas não duplica `observacoes` nem altera o snapshot original.
- O retorno indica `captura_nova` e `snapshot_ja_existente` de forma independente de `novas_observacoes`. Um erro detectado em teste ao usar o objeto Cursor (em vez de `.rowcount`) para inferir reutilização foi corrigido.
- `auditoria_frescor_agro.py` lê SQLite em modo read-only. Verifica datas UTC, última captura, SHA físico de RAW (somente sob raiz local declarada), quantidade de snapshots, observações e capturas. Em bancos legados, usa a data original do snapshot se ainda não existirem eventos de captura.
- Uma captura recente (limite inicial: 72 horas) **não torna o valor atual**. Para CEPEA, o alerta de referência usa um limite conservador de 7 dias corridos; condições de calendário/feriados requerem política operacional posterior. IMEA/CONAB em staging não são promovidos, independentemente da recência do arquivo.
- A auditoria nunca imprime preço, telefone ou identificador de observação; nunca concede `publicavel=True`, nem afirma presença em BigQuery.

Auditoria local, sem rede e sem escrita:

```bash
PYTHONPATH=src python -m nivon.auditoria_frescor_agro \
  --banco /caminho/seguro/fontes_reais.sqlite \
  --raw /caminho/seguro/raw
```

## Evidência e riscos pendentes

- Após integração de 29 arquivos, o primeiro CI teve **7 erros** porque o parser CEPEA importado dependia de `beautifulsoup4` ausente. O parser foi reimplementado sem a dependência, mantendo testes com fonte sintética.
- O segundo CI passou: [núcleo #39999940063](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39999940063) **2.304 testes/3 ignorados**; [acessos #39999939998](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39999939998) **2.304 testes/35 ignorados**.
- O teste de captura histórica detectou uma inconsistência no valor `snapshot_ja_existente`, corrigida ao avaliar `.rowcount`; nova validação após implementação dos eventos de captura e deste documento deve estar vinculada ao HEAD final.
- Pendências materiais: execução real de conectores com egress aprovado, rights CEPEA/IMEA/CONAB, status verificável das agendas em main, confirmação GCS→BigQuery, políticas de atualização por fonte, processamento histórico e restore em GCP; teste PostgreSQL real da outbox continua pendente de ambiente isolado autorizado.
- A main avançou independentemente durante o ciclo; nova reconciliação deve comparar SHAs antes de importar qualquer arquivo, e **jamais importar cron automaticamente**.

**Regra de corte:** nenhuma ativação de workflows, deploy, gasto, publicação, envio ou merge nesta PR draft.
