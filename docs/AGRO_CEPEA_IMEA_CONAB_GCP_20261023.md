# NIVON — CONAB, IMEA e CEPEA conectados ao núcleo GCP

Data: 23/10/2026. **Código/CI homologados apenas com fixtures sintéticas**;
HTTP de origem e gravação GCP *reais* ainda não demonstrados neste lote.

## Situação comprovada no projeto
- Google Cloud `nivon-data`: WIF/ADC e leitura de metadados confirmados pelo job
  de 23/10/2026 (Actions 39980530880). Dataset `nivon_raw` e bucket
  `nivon-data-raw-2026` estão na região `southamerica-east1`.
- A autenticação e a leitura de metadados **não comprovam permissão de escrita**.
- CEPEA, IMEA e CONAB têm pipelines existentes que gravam no **Neon**.
  Este lote não interrompe esses jobs e não muda tabelas do Neon.

## Código reaproveitado dos commits homologados
Movidos sem reinvenção funcional:
- `src/nivon/cepea_web_primario.py`: parser de soja (Paranaguá/PR,
  Paraná) e milho (Campinas/SP) de página oficial, com datas e preços explícitos;
- `src/nivon/imea_publico.py` e `src/nivon/imea_lotes.py`: IMEA por
  cadeias e metadados da API oficial com validação de indicadores;
- `src/nivon/conab_publicacoes.py`, `src/nivon/conab_safras.py`,
  `src/nivon/conab_job.py`: edições oficiais CONAB soja/milho MT,
  publicações e conferência do levantamento.

Novo `src/nivon/agro_origem_gcp.py` registra a coleta por meio do ledger
**já existente** `ingestao_fontes_reais.gravar_lote`: um único RAW SQLite,
SHA-256, snapshots e observações versionadas, reaproveitando
`arquivo_raw_gcs` e, somente quando homologado, o MERGE `carga_bigquery_fontes`.

## Contrato temporal que não pode ser violado
| Fonte | Data de referência | Destino padrão | BigQuery canônico |
| --- | --- | --- | --- |
| CEPEA soja e milho | Verificada na tabela diária | QUARANTINED até homologação e direitos | Opt-in se aprovado |
| IMEA preços/fretes | **Ausente** na fonte normalizada do adaptador | QUARANTINED / GCS privado | Proibido nesta integração |
| CONAB safras | Safra/levantamento verificados, mas não `data_referencia` | QUARANTINED / GCS privado | Proibido nesta integração |

Para IMEA/CONAB, a data de publicação é preservada. O campo
`referencia` exigido pelo SQLite é preenchido tecnicamente para localizar
o snapshot, com `campos.data_referencia=null` e
`tipo_referencia=PUBLICACAO_NAO_EQUIVALE_DATA_REFERENCIA`.
**Nunca** exportar essas observações ao `nivon_observacoes`
canônico, cujo `data_referencia DATE NOT NULL` exige uma referência
real. Não confundir COTAÇÕES ANUNCIADAS, preços informados ou estágio
com operação comercial efetivamente realizada.

O RAW GCS da CEPEA guarda a página HTML decodificada preservada no ledger
— não os bytes HTTP originais quando o charset diferir. IMEA/CONAB guardam
um snapshot **semântico** do resultado validado pelo agrobr, não os bytes
HTTP originais; isso está marcado no payload.

## Operação CLI
Sem rede nem cloud, apenas plano:
```bash
python scripts/coletar_agro_google_cloud.py --fonte CEPEA_SOJA
python scripts/coletar_agro_google_cloud.py --fonte IMEA
python scripts/coletar_agro_google_cloud.py --fonte CONAB
```

Coleta real só com `NIVON_AGRO_FONTE_AUTORIZADA=true` após verificação de
direitos, termos e disponibilidade. Para enviar GCS, também requer
`NIVON_RAW_ARCHIVE_APPROVED=true`, `NIVON_ZERO_COST_BQ_APPROVED=true`,
ADC/WIF e `NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET`.
Não habilitar os booleanos como atalho para faturamento, licença ou IAM.

```bash
python scripts/coletar_agro_google_cloud.py --fonte CEPEA_SOJA --executar --gcs
python scripts/coletar_agro_google_cloud.py --fonte IMEA --executar --gcs
python scripts/coletar_agro_google_cloud.py --fonte CONAB --executar --gcs
```

Para CEPEA com contrato validado e uso interno autorizado, além de checar
a tabela `nivon_observacoes` em BQ e a licença **CC BY-NC 4.0**:

```bash
# Requer NIVON_CEPEA_HOMOLOGACAO_APROVADA=true.
python scripts/coletar_agro_google_cloud.py \
  --fonte CEPEA_SOJA --executar --gcs --homologar-cepea --bigquery
```

**Atenção:** snapshots existentes em QUARANTINED não são promovidos
automaticamente pela reapresentação do mesmo arquivo com flag diferente.
É obrigatória uma rotina auditável de transição de status e revisão de
direitos/fonte, não um UPDATE cego.

## Rotina programável
`.github/workflows/fontes-agro-gcp.yml` inclui disparo manual (fonte
escolhida) e agenda em dias úteis. A agenda **não executa** sem o conjunto
completo de gates `NIVON_AGRO_GCP_WRITE_APPROVED`,
`NIVON_RAW_ARCHIVE_APPROVED`, `NIVON_ZERO_COST_BQ_APPROVED`,
provedor WIF, SA, projeto, dataset e bucket.

Cada fonte exige aprovação explícita adicional:
`NIVON_CEPEA_FONTE_AUTORIZADA`,
`NIVON_IMEA_FONTE_AUTORIZADA` ou
`NIVON_CONAB_FONTE_AUTORIZADA`.
A agenda padrão só arquiva GCS em staging/quarentena. Promoção de CEPEA é
manual, condicionada a `NIVON_CEPEA_HOMOLOGACAO_APROVADA`,
`nivon.preflight_gcp_fontes` e permissão explícita do operador.

## Gates de produção
1. Sem WIF autenticado para **escrita** e IAM mínimo sobre bucket/dataset,
   não liberar `NIVON_AGRO_GCP_WRITE_APPROVED`.
2. Verificar URLs/mime/estrutura/frescor do CEPEA e endpoints IMEA/CONAB
   em amostras reais; sinais de bloqueio ou dado antigo não são sucesso.
3. Conferir objetos por hash, criação de manifesto e replay independente
   do runner; executar MERGE de CEPEA somente no recorte autorizado.
4. Validar linhas/datas/valores recuperados do BigQuery, incluindo latência,
   custo, limites, idempotência e datas de publicação.
5. Após dois ciclos em dias diferentes, comparar com os históricos Neon;
   nenhum corte de Neon antes de reconciliação e restore.
6. Estudar estágio BigQuery **não canônico** com `data_referencia` anulável
   para IMEA/CONAB quando o contrato e a data de referência forem auditados.

## CI
Fixtures determinísticas no workflow
`ci-nucleo-fontes-gcp.yml` e suíte global
`testes-acessos-isolados.yml`. Tests:
`test_agro_origem_gcp.py`, `test_cepea_web_primario.py`,
`test_imea_lotes.py` e pipeline GCS/BigQuery existente.


## Atualização: staging BigQuery distinto e incremental

**CONAB e IMEA não ficam restritos ao GCS:** o código também permite gravar
observações não canônicas em uma tabela própria `agro_publicacoes_staging`
dentro do dataset privado autorizado, desde que a tabela tenha sido criada e
que o gate de escrita de staging tenha sido aprovado.

- DDL: `sql/bigquery/003_agro_publicacoes_staging.sql`. Campos
  `data_referencia DATE NULL`, `data_publicacao DATE`,
  `publicacao_bruta STRING`, `referencia_tecnica STRING`,
  `data_coleta TIMESTAMP`; partição por `DATE(data_coleta)`.
- `agro_staging_bigquery.py`: valida dados do SQLite em `QUARANTINED`,
  exporta JSONL privado, salva stage por SHA-256 no GCS, verifica tabela
  existente e usa MERGE idempotente com filtro da partição.
- Variável extra para habilitar: `NIVON_AGRO_STAGING_BIGQUERY_APPROVED=true`.
  Essa flag exige que a tabela já exista com schema e IAM corretos e que o
  responsável tenha revisado custos e condições de uso.
- Exemplo de execução autorizada:
  ```bash
  python scripts/coletar_agro_google_cloud.py --fonte IMEA --executar --gcs --staging-bigquery
  python scripts/coletar_agro_google_cloud.py --fonte CONAB --executar --gcs --staging-bigquery
  ```
- O workflow agendado só acrescenta `--staging-bigquery` se a variável
  estiver ativa e a tabela for confirmada. A tabela
  `nivon_observacoes` **não recebe IMEA/CONAB** enquanto faltarem referências
  de período homologadas.

### Incremental verdadeiro
Os três conectores retornam os IDs SHA dos snapshots adquiridos na execução;
o RAW GCS e as exportações BQ usam exatamente esses IDs. Não reenviam a
base SQLite inteira a cada execução. Esse comportamento é importante quando
a base acumula mais de 200 snapshots e permite reprocessamento histórico em
lotes separados. Quando um arquivo novo não contém nenhuma observação inédita
associada ao snapshot, o sistema arquiva o RAW e registra
`GCS_RAW_SEM_DELTA_ANALITICO`, sem criar carga BigQuery vazia.

**Ainda pendente de confirmação real:** existência da tabela staging,
escrita no bucket, execução de MERGE, leitura posterior, limites/alertas
de cobrança e comparação efetiva com dados Neon em duas datas diferentes.
