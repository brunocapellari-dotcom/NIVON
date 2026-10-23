# NIVON — Coletores reais: Argentina, Canada e CCEE (2026-10-22)

## Entregues
- 209 fontes e 279 datasets no inventario canônico, rotas versionadas e 10 bibliotecas registradas (sem instalação).
- Cliente **Argentina Series API** usando identificador oficial documentado `168.1_T_CAMBIOR_D_0_0_26`, data de início/fim estrita, número de observações máximo e parsing de datas/valores. Unidade ainda provisória; observações ficam INTERNAS e NÃO publicáveis até validação da meta da série.
- Cliente **Canadian Grain Commission** para CSV acumulado da safra `2026-27` e outras safras com padrão `YYYY-YY`, sem presumir coluna e conversão monetária. Armazena RAW, registra cabeçalho amostral. Backfill histórico específico ainda não implementado.
- Cliente **CCEE** CKAN `pld_horario` consulta pacote, valida licença declarada, identifica recurso UUID CSV e baixa SOMENTE no domínio do provedor, seguindo contrato estrito. Estrutura de PLD não presumida: RAW ainda precisa de parser tipado e unidade por período.
- Persistência SQLite com WAL, hash SHA256 do payload, raw imutável, versão por identidade e valor, transação atomicamente confirmada, e saída JSONL de observações. Não conecta automaticamente ao BigQuery.
- CLI manual explícito por recurso; proteção contra URLs arbitrárias, redirects e tamanhos excessivos.

## Execução local
Instalar pacote: `pip install -e .`.
Teste offline: `python -m unittest discover -s tests -p 'test_coletores_dados_reais.py' -v`.

### Coleta real do câmbio da Argentina
```bash
python -m nivon.coletores_dados_reais --fonte ARG_SERIES_CAMBIO --inicio 2026-10-01 --fim 2026-10-15 --executar
```

### CSV canadense
```bash
python -m nivon.coletores_dados_reais --fonte CAN_GRAINS_WEEKLY --safra 2026-27 --executar
```

### Catálogo CCEE
```bash
python -m nivon.coletores_dados_reais --fonte BR_CCEE_PLD --executar
```
O comando acima apenas devolve lista de recursos CSV. Para baixar um recurso **com licença declarada CC-BY e hospedado no dominio oficial**:
```bash
python -m nivon.coletores_dados_reais --fonte BR_CCEE_PLD --recurso-id UUID_DA_RESPOSTA --executar
```
Os arquivos ficam em `data/nivon/raw/`; banco em `data/nivon/fontes_reais.sqlite`. Exportacao historica:
```python
from nivon.ingestao_fontes_reais import exportar_jsonl
print(exportar_jsonl(banco="data/nivon/fontes_reais.sqlite", destino="data/nivon/staging.jsonl"))
```

## Status e limites
- Contratos de coleta e SQLite têm testes offline de integração em GitHub Actions; testes com HTTP real e preenchimento da nuvem devem ser documentados separadamente.
- Essas três rotas não convertem os demais 97 candidatos em integrações operacionais. 10 projetos GitHub continuam somente avaliáveis (licenças, segurança e desempenho).
- A execução por CLI é opt-in, não tem scheduler configurado.
- Limites de licenciamento, API e acesso devem ser validados por operação, inclusive para uso não comercial.
- Proteger `data/nivon/` contra commit de dados brutos e monitorar disco/backup. SQLite é camada inicial local; BigQuery depende de projeto e serviço provisionados com credenciais seguras.
- Filtros de tempo e saidas sem amostra real devem ser considerados previstos; nunca preencher lacunas com zero.

## Registro de fontes
- API argentina: https://datosgobar.github.io/series-tiempo-ar-api-english/quick_start/
- Canada CSV: https://grainscanada.gc.ca/en/grain-research/statistics/grain-statistics-weekly/
- CCEE CKAN: https://dadosabertos.ccee.org.br/dataset/pld_horario

## Evidencia HTTP real em GitHub Actions, 23/10/2026 UTC
- BCRA v4 /Monetarias/1: 4 observações históricas reais, gravadas em stage SQLite efêmero da CI. Estado: NORMALIZED, unidade aguardando metodologia BCRA.
- granos.ar /pizarra: 10 observações reais de preços de soja, milho e demais grãos, com moedas ARS/t e USD/t, natureza INFORMADO e fonte SECUNDÁRIA. /status também respondeu.
- Canadian Grain Commission: arquivo CSV de safra obtido e RAW registrado no SQLite da CI; os campos ainda não têm parser canônico.
- CCEE PLD: CKAN oficial acessado, licença declarada cc-by-4.0, recursos CSV identificados, sem download de serie/homologação do esquema.
- Argentina Series API: HTTP 200 mas 0 linhas na janela setembro/2026; corrigido o estado para RAW_RECEIVED, sem fingir atualização de preço.

## CLI de fontes adicionais
```bash
python -m nivon.coletor_bcra_v4 --inicio 2026-09-01 --fim 2026-09-05 --executar
python -m nivon.coletor_granos_ar --endpoint pizarra --executar
python -m nivon.coletor_granos_ar --endpoint pizarra/historico --dias 30 --executar
python scripts/operar_fontes_reais.py --canada
```

## BigQuery e agendamento
- Contrato DDL: `sql/bigquery/002_observacoes_fontes_reais.sql`.
- Carga com deduplicação/revisões: `src/nivon/carga_bigquery_fontes.py`, extra opcional `pip install -e '.[gcp]'`.
- Agenda proposta em `.github/workflows/coleta-recorrente-fontes.yml`; **não executa na main até merge homologado**.
- Google Cloud projeto NIVON `nivon-data`: identificado, mas dataset BigQuery, tabela, billing e Workload Identity para este repositório não verificados/criados. A conta da AI-Holding NÃO serve para acesso automático ao NIVON.
- Política R$0: workload de BigQuery só pode autenticar se `NIVON_ZERO_COST_BQ_APPROVED=true` e existir provider OIDC/service account/projeto/dataset. Sem esses gates a ação registra explicitamente histórico efêmero e não publica na nuvem.
- Nenhuma credencial, série privada, preço proprietário ou dump bruto é publicado no GitHub.
- Nunca afirmar que o fato de haver workflow agendado em branch torna o serviço ativo.


## Resultado verificável do ensaio HTTP de 23/10/2026 UTC
- CCEE 2026, recurso oficial `pld_horario_2026`, CSV recuperado de `pda-download.ccee.org.br` após consulta CKAN: **28.416 linhas normalizadas** em R$/MWh com submercado/período/hora. Snapshot RAW e séries gravados em SQLite efêmero GitHub Actions. Identificador anual agora descoberto automaticamente no catálogo oficial.
- Canadian Grain Commission `2026-27`: **11.786 observações normalizadas** de soja, milho, trigo e canola com cultura/semana/descrição da métrica/região, Ktonnes convertidos em toneladas. Atenção: não somar métricas heterogêneas nem tratar movimentações acumuladas e semanais como iguais.
- API secundária granos.ar /pizarra: **10 observações reais** e status HTTP saudável. Fonte não primária.
- BCRA /Monetarias/1: **4 observações** na janela do ensaio. A série argentina genérica de câmbio retornou 0 e não entrou no conjunto normalizado.
- Total observado dos testes: **40.216 observações** processadas. Não implica 40.216 linhas no banco NIVON de produção; armazenamento dos ensaios foi temporário.
- Todos os processos acima permanecem separados do BigQuery, cujo dataset, IAM e política de custo devem ser comprovados antes da habilitação.

## Orquestração recorrente preparada
- `scripts/operar_fontes_reais.py` coleta BCRA/granos.ar por execução e aceita `--canada --ccee` para conjuntos semanais.
- `.github/workflows/coleta-recorrente-fontes.yml`: segunda-feira inclui CCEE/Canadá, demais dias úteis BCRA/granos.ar; só roda automaticamente se a branch principal tiver workflow homologado **e** variables NIVON_ZERO_COST_BQ_APPROVED, NIVON_GCP_PROVIDER, NIVON_GCP_SERVICE_ACCOUNT, NIVON_BQ_PROJECT e NIVON_BQ_DATASET configuradas; execução manual é permitida.
- `src/nivon/carga_bigquery_fontes.py`: JSONL -> BigQuery por carga temporária seguida de MERGE, exigindo tabela existente, ADC e limites de bytes; **não executado contra Cloud real**.
- Snapshot RAW precisa de persistência durável adicional na infraestrutura NIVON; quando executado em GitHub Actions, o arquivo local é efêmero. **A operação contínua não está implantada.**
- Demais fontes (mais de 90 fontes adicionais sem coleta homologada) continuam requerendo implementação individual de endpoint, esquema e direitos.

## Persistência permanente GCS + BigQuery — implementação de 23/10/2026

**Arquitetura do código (PR #137):** autenticação Google OIDC/ADC -> pré-voo de acesso, bucket e tabela -> BCRA/granos.ar diários + CCEE/Canadá semanais -> SQLite/RAW local -> validação SHA-256 -> upload imutável de RAW para Cloud Storage -> carga JSONL no BigQuery via staging e MERGE -> verificação de falhas parciais. Uma falha no armazenamento RAW bloqueia a carga no BigQuery.

**Módulos criados:**
- `src/nivon/arquivo_raw_gcs.py`: lista a tabela `snapshots` do SQLite e valida arquivo, tamanho, SHA-256, origem e identidade antes de arquivar em `gs://BUCKET/nivon/raw/v1/DATASET/SHA256.raw`. Não sobrescreve objetos e valida o objeto já existente.
- `src/nivon/preflight_gcp_fontes.py`: verifica projeto, dataset, bucket, schema e particionamento. A opção `--criar-tabela` cria somente a tabela em dataset existente, se autorizada.
- `src/nivon/carga_bigquery_fontes.py`: valida datas ISO e identidade por versão e converte referência, publicação e coleta em DATE/TIMESTAMP, mantendo as datas originais auditáveis.
- `scripts/verificar_status_fontes.py`: reprova resultado parcial após tentar arquivamento e persistência.
- `.github/workflows/coleta-recorrente-fontes.yml`: cron segunda a sexta e execução manual; exige acesso cloud validado **antes** de qualquer coleta.

**Configuração única que falta para operação real na main:** no repositório GitHub, cadastrar variables `NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`, `NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET`, `NIVON_ZERO_COST_BQ_APPROVED=true` e `NIVON_RAW_ARCHIVE_APPROVED=true`. Se for permitir a criação da tabela dentro do dataset existente, acrescentar `NIVON_BQ_BOOTSTRAP_TABLE_APPROVED=true`; depois poderá ser desabilitada. Exigem-se IAM mínimo de escrita/leitura dos objetos do bucket (para integridade e idempotência), acesso ao dataset e execução de jobs BigQuery, e permissão de criação de tabela apenas durante o bootstrap. O GitHub Actions usa Workload Identity OIDC, **não** chaves JSON em repositório. Bucket e dataset **não** são criados automaticamente. Verificar termos e direitos de arquivamento de cada fonte.

**Custos:** o nome da variable `NIVON_ZERO_COST_BQ_APPROVED` representa uma autorização de controle operacional, **não** uma garantia de faturamento zero. BigQuery e Cloud Storage podem gerar custos de armazenamento, leitura e operações; configurar orçamento, limites e alertas antes da ativação.

**Situação real:** o código de arquivamento, preflight e carga está registrado e testado com clientes simulados; nenhuma leitura/escrita real no Google Cloud foi confirmada nesta frente. As coletas reais de CCEE/Canadá/BCRA/granos.ar foram testadas no GitHub Actions, porém em ambiente temporário. O workflow só passa a ser executado pelo agendamento após integração na branch principal e preenchimento dos requisitos.
