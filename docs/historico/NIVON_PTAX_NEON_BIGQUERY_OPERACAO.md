# NIVON — Ponte PTAX Neon → Google Cloud (estado comprovado 23/10/2026)

## Estado operacional

**APROVADO:** consulta real do banco Neon, autenticação OIDC vinculada ao workflow GitHub, paginação por ID numérico, conversão de todos os registros para JSONL privado, validação de contrato de destino, idempotência lógica, bloqueio sem aprovação e agendamento em `main`.

**AINDA NÃO EXECUTADO:** criação do dataset/tabela BigQuery, acesso autenticado ao projeto GCP, carga real ou cutover do Neon. O Google Cloud **não** é fonte comprovada de armazenamento operacional desta ponte.

### Evidências verificáveis

- Job privado de exportação real: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946955627
- Primeira execução do workflow `main`: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947519626
- Execução `main` após consolidação do código: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947905419
- Amostra do snapshot completo no último job: **5.529 linhas**, **EUR 4.604**, **USD 925**, referência entre **2020-01-02 e 2026-10-22**; ID máximo da origem 5571; SHA-256 do JSONL validado `0b455e98233d8b68d9e04f7b2a4482f12c8a608cfe2a8f70e4cff4aa332ce55f`.
- Os logs declaram `GCP_OFF`, `bigquery_executed:false` e `BIGQUERY_WRITE_BLOCKED_BY_DEFAULT=true`. Todos esses campos são deliberados e devem continuar verdadeiros até haver confirmação de escrita no Google Cloud.

## Fluxo construído

```text
Banco Central/PTAX --> coletor Neon existente (preservado) --> nivon_ptax_quotes (Neon)
   --> ptaxbridge (Neon Function, GET /checkpoint e GET /export autenticados via OIDC GitHub)
   --> JSONL bruto privado em RUNNER_TEMP (0600)
   --> scripts/ptax_neon_private_export.py [normalização, hashes, vintages, cursor por ID]
   --> JSONL compatível com nivon_core.ptax_quotes (0600)
   --> scripts/ptax_bigquery_incremental.py [validação de linhas e custos]
   --> BigQuery MERGE apenas após gates explícitos
```

- Função `ptaxbridge`: Neon Function deployment 2 com JWT OIDC `urn:nivon:ptax:export:v1`, validando repositório, ref, `workflow_ref` e evento permitido. Acesso sem token não retorna dados.
- Workflow ativo: `.github/workflows/ptax-neon-private-export.yml`, agendado em dias úteis, às **23h45 UTC / 19h45 America/Cuiaba**. `workflow_dispatch` disponível.
- Scripts do fluxo versionados em `main`: `scripts/ptax_neon_to_bigquery_jsonl.py`, `scripts/ptax_neon_private_export.py`, `scripts/ptax_bigquery_incremental.py`.
- DDL de destino: `database/bigquery/nivon_ptax_schema.sql` — modelo, **não executado**.
- Os arquivos privados são apagados ao encerrar o job; nenhum artifact com cotações é publicado no GitHub. Os relatórios expõem somente contagens, hashes e datas.

## Incremental e consistência

- No Neon, cada execução começa congelando `MAX(id)` e pagina os IDs em ordem numérica até esse teto.
- Isso é um **cutoff por ID**, não snapshot transacional MVCC. Commits tardios com ID menor podem aparecer depois.
- Quando BigQuery estiver disponível, o checkpoint consulta `MAX(source_neon_row_id)` com filtro de partição, **retrocede 5.000 IDs** e reprocessa uma janela sobreposta. O `MERGE` por `quote_id` é idempotente e preserva revisões.
- A verificação de lote no BigQuery compara `record_sha256` de cada linha importada, procura ausências e duplicatas, sem considerar esse teste como prova de completude de todo o histórico.
- Campos `published_at` desconhecidos permanecem NULL; `origem_sha256` permanece NULL enquanto o payload RAW do BCB não estiver disponível. `record_sha256` identifica o registro normalizado, não o RAW.
- Nenhum trigger, dado Neon ou coletor primário foi desligado ou excluído.

## Condições obrigatórias para primeira carga GCP

1. Verificar por acesso real o projeto `nivon-data`, billing, cota de consumo, IAM e direito de armazenamento. Captura do console não substitui validação.
2. Configurar `nivon_core.ptax_quotes` de acordo com o SQL versionado: particionamento por `reference_date`, `require_partition_filter=TRUE` e tipos corretos. **Não** criar serviços sem rever custo.
3. Configurar WIF GitHub → GCP com atributo `repository=brunocapellari-dotcom/NIVON`, ref `main`, workflow exato e service account de mínimo privilégio.
4. Definir variáveis GitHub `NIVON_GCP_PROVIDER` e `NIVON_GCP_SERVICE_ACCOUNT`.
5. **Somente após revisão expressa de faturamento/custos**, definir `NIVON_GCP_WRITE_APPROVED=true` e `NIVON_GCP_COST_REVIEWED=true`. Sem todas as quatro variáveis, o workflow fica permanentemente em modo de leitura.
6. Executar o job e conferir carga, `MERGE`, conciliação e uma segunda rodada incremental. Nenhum sucesso da validação local equivale a Google Cloud implantado.
7. Não executar cutover ou remover Neon sem prova de backup/restore e reconciliação independente.

**Estado final:** `NEON_TO_PRIVATE_JSONL_E2E_OK`; `BIGQUERY_WRITE_NOT_CONFIRMED`; `NEON_KEPT_RUNNING`.

## Atualização operacional em 23/10/2026 (após primeira carga ANTT)

A execução [39983416188](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188) **comprovou escrita no BigQuery e GCS exclusivamente para o lote ferroviário ANTT 2026**. Essa prova não deve ser atribuída à PTAX nem aos dados de CEPEA/IMEA/CONAB.

A identidade já existente e confirmada por OIDC usa a variável GitHub `NIVON_GCP_PROVIDER`, não o nome legado `NIVON_GCP_WIF_PROVIDER`. Os workflows PTAX direto, ponte PTAX Neon e migrador agrícola passaram a reutilizar o provider canônico; continuam com gates independentes de autorização de escrita, revisão de custos e escritor único.

O script `scripts/bootstrap_nivon_gcp.sh` deixa de criar outra service account ou outro provider WIF: verifica o par já existente e recusa `--aplicar` se a condição da identidade não puder ser confirmada como restrita ao repositório e à `main`. Continua obrigatório revisar IAM, custo e o destino `nivon_core.ptax_quotes` (ainda não atestado).

**Dados reais e acesso à origem não são prova de carga PTAX.** Não desligar Neon ou preencher datas não fornecidas.
