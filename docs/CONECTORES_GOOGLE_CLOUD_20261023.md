# NIVON: conectores operacionais e integração Google Cloud — 23/10/2026

## Entrega de código na branch

Módulos implementados:
- `src/nivon/conectores_publicos_gcp.py`: obtém diretamente da fonte oficial **BCB/PTAX** (OData) e **IBGE/PAM** (SIDRA 1612), reutilizando os planejadores, normalizadores e a base RAW SQLite já existentes. Necessitam confirmação de direitos por operação, filtros, URL, versão e teste de amostra real.
- `src/nivon/coletor_imea_origem.py`: conexão HTTPS **somente IMEA**, com URL real parametrizada por configuração, sem endpoint presumido. Aceita XLSX das cinco abas do parser AgroLog reaproveitado. Dados entram em `IMEA_WORKBOOK_LEGADO_STAGING`, em estado `QUARANTINED` e não no mart de preços/fretes.
- `src/nivon/coletor_conab_sicarm_gcp.py`: endereço oficial legado SICARM/CONAB, valida TXT com o parser preexistente, testa agregação municipal e não divulga identificadores pessoais na parte normalizada. Qualidade e referência temporal requerem conciliação: quarentena, não publicação de ocupação/estoque.
- `src/nivon/persistencia_google_cloud.py`: camada durável e reutilizável para qualquer pipeline que escreva no `ingestao_fontes_reais.gravar_lote`. Verifica integridade do RAW em disco, grava RAW por SHA-256 e manifesto de proveniência no Google Cloud Storage com `if_generation_match=0`, salva o JSONL durável e chama o MERGE idempotente do carregador BigQuery **existente**. Replays não sobrescrevem objetos. Bloqueia carregamento canônico de lotes RAW ou `QUARANTINED`.
- `scripts/coletar_google_cloud.py`: CLI para os quatro conectores por fonte, com proibição de rede/nuvem por padrão; flags de aprovação, direitos e configuração do projeto. 
- `.github/workflows/fontes-google-cloud.yml`: workflow OIDC Google Cloud preparado para disparo manual de BCB/PTAX, IBGE/PAM, IMEA, CONAB; quando mergeado na branch de execução, agenda somente BCB/PTAX nos dias úteis sob gates. Não armazena service account JSON em GitHub.
- `pyproject.toml`: extra `gcp` passa a instalar `google-cloud-bigquery` e `google-cloud-storage`.

## Operação e divisão dos 680 links legados

Os 680 URLs herdados do AgroLog são **um catálogo de referências**, não 680 conectores executáveis. Links de Radar e Conhecimento não devem ser enviados como linhas de commodities. Cada fonte de Dados ainda precisa de adapter com endpoint, método de autenticação, semântica, unidade, vigência, direitos, QC e periodicidade. O motor de GCS/BigQuery é **compartilhado** para reduzir o custo de integração futura, não atalho para coleta sem parser.

| Fonte | Origem | Extrator | Stage local | GCS | BigQuery canônico |
| --- | --- | --- | --- | --- | --- |
| BCB PTAX | OData oficial | OData PTAX já presente no NIVON | NORMALIZED | Preparado | Preparado |
| IBGE PAM | SIDRA API oficial | PAM 1612 já presente no NIVON | NORMALIZED | Preparado | Preparado |
| IMEA workbook operacional | **URL XLSX IMEA ainda não identificada/confirmada** | Parser AgroLog portado | QUARANTINED | Preparado se arquivo existe | Bloqueado até homologação |
| CONAB Armazéns | URL TXT SICARM catalogada no AgroLog, operação real pendente | Parser SICARM NIVON existente | QUARANTINED | Preparado | Bloqueado até QA e vigência |
| CEPEA | Workflow CEPEA pré-existente em outra frente | Validar origem/integração e direitos | Não alterado nesta PR | Pendente | Pendente |
| ANTT/ANTAQ/portos/USDA | Conectores em outras PRs | Reusar após conciliação | Não alterado nesta PR | Motor compartilhado pronto para lotes compatíveis | Gate por dataset |

**Preparado** significa código e interface, não upload ou execução real. A disponibilidade e o layout da fonte só são comprovados por smoke com arquivo real e persistência após gate.

## Configuração Google Cloud necessária

1. Selecionar projeto GCP, localização de dados, dataset privado e bucket GCS **privado**, sem Uniform Bucket Level Access desativado, sem acesso público, com versionamento/retenção calibrados, custos e orçamento aprovados. Exemplo de nomes abaixo é ilustrativo, não comprova existência.
2. Aplicar manualmente o DDL existente `sql/bigquery/002_observacoes_fontes_reais.sql`, adaptando `PROJECT_ID` e `DATASET_ID`; confirmar tabela `nivon_observacoes`. Antes de produção de longa duração, avaliar migração para particionamento por `data_referencia`, pois DDL atual tem `referencia` como string e apenas clustering.
3. Criar service account restrita, concedendo leitura de metadados e criação de objetos **somente no bucket NIVON**, operações BigQuery no dataset dedicado e `bigquery.jobs.create` no projeto necessário; evitar chaves JSON.
4. Configurar Workload Identity Federation com atributo de repositório/branch estrito, incluindo política `refs/heads/main` para cron/manual após merge. Validar OIDC em execução isolada com IAM mínimo.
5. Configurar **GitHub Actions repository variables**:

   ```
   NIVON_GCP_OPERACIONAL_APROVADO=true
   NIVON_GCP_DIREITOS_DADOS=true
   NIVON_ZERO_COST_BQ_APPROVED=true
   NIVON_GCP_PROVIDER=projects/<numero>/locations/global/workloadIdentityPools/<pool>/providers/<provider>
   NIVON_GCP_SERVICE_ACCOUNT=<service-account>@<projeto>.iam.gserviceaccount.com
   NIVON_BQ_PROJECT=<project-id>
   NIVON_BQ_DATASET=<dataset-id>
   NIVON_GCS_BUCKET=<bucket-privado>
   NIVON_GCP_RIGHTS_EVIDENCE=<referencia-de-autorizacao-publica-sem-segredos>
   NIVON_IMEA_XLSX_URL=<url-direta-confirmada-HTTPS-IMEA>
   ```

   Só habilitar os três booleanos depois de validar condições de acesso e custo. Não colocar tokens, credenciais ou URLs assinadas nos variables; usar Secret Manager quando necessário. **O termo zero_cost refere-se a aprovação de orçamento, não garante fatura zero.**
6. Validar GCS SHA antes e depois, IAM, região, DDL/schema e replay/restore em um teste real controlado. Jamais ativar o agendamento sem esse aceite técnico.

## Execução CLI

Planejamento inerte, sem rede:

```bash
PYTHONPATH=src python scripts/coletar_google_cloud.py --fonte BCB_PTAX
```

Coleta e Cloud **somente** com credenciais ADC, direitos/custos validados, variáveis configuradas e `--executar`:

```bash
PYTHONPATH=src python scripts/coletar_google_cloud.py --fonte BCB_PTAX --executar
PYTHONPATH=src python scripts/coletar_google_cloud.py --fonte IBGE_PAM --executar \
  --municipio-ibge 5107925 --ano 2024 --codigo-produto <codigo_c81_validado> --codigo-variavel <codigo_validado>
PYTHONPATH=src python scripts/coletar_google_cloud.py --fonte CONAB_ARMAZENS --executar
PYTHONPATH=src python scripts/coletar_google_cloud.py --fonte IMEA_WORKBOOK --executar
```

IMEA e CONAB entram no **GCS privado com manifesto e QUARENTENA**. O conector não transporta automaticamente dados desses datasets para BigQuery canônico. Quando os direitos e o parser de cada fonte estiverem homologados, desenvolver o contrato analítico no BigQuery em tabela de staging separada e promover a partir de gates explícitos.

## Controles de falha e temporalidade

- Fonte fora do domínio, redirecionamento, HTML/WAF, MIME errado, XLSX suspeito, variação de layout e séries sem valor fazem falhar a fonte, não viram zeros ou sucesso falso.
- Cada snapshot RAW inclui SHA, identidade por dataset, data de coleta real, origem auditável e estado. O arquivo no GitHub Actions é efêmero; somente confirmação GCS é persistência durável.
- `data_publicacao` não é inferida do HTTP Last-Modified; IMEA e SICARM continuam sem vintage de publicação comprovado. A `data_referencia` provisória SICARM recebe marca explícita de captura técnica, não período de vigência cadastral.
- GCS é armazenamento de origem; BigQuery tem números derivados e vintages por fingerprint. Se falhar o MERGE após GCS, o RAW e o JSONL são recuperáveis para repetição idempotente.
- A carga GCS e BigQuery **não equivale a publicar resultados** nem aprovar dados para uso comercial.
- Ordem para backfill: fonte oficial mais antiga acessível → RAW por hash → parser → QA → persistência → incremental; Drive histórico só entra como evidência auxiliar e não atualiza sozinho.

## Validação e próximos gates

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_conectores_publicos_gcp.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_coletor_conab_sicarm_gcp.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_persistencia_google_cloud.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

Pendências: teste HTTP de amostra real atual CONAB; endpoint de workbook IMEA publicado/autorizado; materializar GCP real (IAM, bucket, dataset, DDL), teste de gravação/releitura, ligar CEPEA e demais fontes já existentes ao mesmo sink, e reconciliação da cadeia de PRs antes do deploy. **Este lote não executou recursos Google Cloud, portanto não pode ser considerado homologado em produção.**
