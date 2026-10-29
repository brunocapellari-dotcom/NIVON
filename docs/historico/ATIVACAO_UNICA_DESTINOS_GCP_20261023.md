# NIVON: criação única dos dois destinos BigQuery faltantes

Data: 23/10/2026. Evidência real do workflow `NIVON - Verificar Conexao Google Cloud` (run 39999222849): a identidade federada (WIF/ADC) consultou recursos de `nivon-data`; o bucket `nivon-data-raw-2026` e o dataset `nivon_raw` existem na região `southamerica-east1`. No inventário pós-verificação, as tabelas `nivon_observacoes` e `agro_publicacoes_staging` foram identificadas como **AUSENTES**. IAM informativo indicou possibilidade de criar objetos GCS, sem upload real.

## Entrega

Criado `src/nivon/bootstrap_tabelas_gcp.py`, orquestração curta das rotinas existentes:

- `preflight_gcp_fontes.verificar_nuvem` — tabela canônica `nivon_observacoes`, `data_referencia DATE` com partição diária/filtro obrigatório e clustering.
- `agro_staging_bigquery.verificar_ou_criar_tabela` — `agro_publicacoes_staging`, particionada pela data de coleta, com `data_referencia` opcional para IMEA/CONAB e estado de quarentena.

Nenhum contrato SQL adicional é criado. Ambas as operações usam o projeto/dataset GCP já existentes, não criam Storage, contas de serviço, usuários nem projetos. Em modo somente leitura, informa se cada tabela falta. Em `--aplicar`, exige autorização e executa somente a criação das tabelas ausentes, conferindo seus schemas. Se a primeira tabela existir e a segunda falhar, a repetição é idempotente, sem `DROP` ou alteração destrutiva.

## Ativação com uma ação no GitHub (após merge)

Ação: **NIVON - Ativar dois destinos BigQuery para coletores**.

1. Executar `workflow_dispatch` com `aplicar=false` para verificar.
2. Depois da aprovação de IAM/custos, selecionar `aplicar=true` **uma vez**, sem Cloud Shell. A execução ocorre em `main` e no ambiente `nivon-gcp-producao`.
3. O workflow falha fechado se faltarem `NIVON_BQ_BOOTSTRAP_TABLE_APPROVED=true`, `NIVON_AGRO_STAGING_SCHEMA_APPROVED=true`, `NIVON_AGRO_GCP_WRITE_APPROVED=true` ou `NIVON_ZERO_COST_BQ_APPROVED=true`.
4. Conferir o resultado `DESTINOS_BIGQUERY_VERIFICADOS` e as duas chaves `estado=SCHEMA_VALIDADO`. **Isso não prova MERGE, upload, custo zero ou carga real.**

O workflow reutiliza as variáveis já usadas pelo projeto (`NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`, `NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET`). Não publicar tokens/credenciais.

Teste local inerte: `python -m nivon.bootstrap_tabelas_gcp --projeto nivon-data --dataset nivon_raw --bucket nivon-data-raw-2026`.
CI sintética: `python -m unittest discover -s tests -p test_bootstrap_tabelas_gcp.py -v`.

## Após a ativação

Somente após ambas as tabelas serem verificadas: validar o primeiro upload RAW/manifesto real no GCS privado, inserir observação canônica BCB/SGS com leitura posterior, gravar IMEA/CONAB somente no estágio de quarentena, testar segundo replay sem duplicidade, e registrar faturamento IAM/retention. Nenhuma coletora recebe permissão automaticamente pela existência da tabela.
