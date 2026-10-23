# NIVON — conexões reais para Google Cloud (23/10/2026)

## Situação comprovada

**Código e testes estão no GitHub. NÃO há confirmação de execução em Google Cloud.**
A conta Google Cloud, o bucket privado, as políticas IAM, o Workload Identity
e a tabela BigQuery de destino não puderam ser inspecionados nesta sessão.
A interface BigQuery do ChatGPT está indisponível nesta conexão.
Não contabilizar ensaios E2E simulados como dados recebidos no GCP.

## Coletores que compartilham a ponte NIVON existente

| Fonte | Adaptador efetivo | Cloud | Estado |
|---|---|---|---|
| BCB PTAX | `conectores_publicos_gcp.py` | `persistencia_google_cloud.py` | Código pronto; operação sujeita a gates |
| IBGE PAM | `conectores_publicos_gcp.py` | Mesma ponte | Código pronto; parâmetros municipais exigidos |
| IMEA XLSX de origem | `coletor_imea_origem.py` | GCS somente QUARENTENA | Direito/origem atual e layout real pendentes; não promove para BQ |
| BCB Selic diária (SGS série 11) | `coletar_selic_diaria` + `scripts/coletar_sgs_google_cloud.py` | Mesma ponte | Implementado; não confundir taxa diária com meta Selic |
| CONAB SICARM Armazéns | `coletor_conab_sicarm_gcp.py` | GCS original privado, depois GCS derivado + BQ agregados | Implementado, falta executar contra arquivo atual e ambiente real |

Os demais nomes dos inventários AgroLog (**68 fontes** operacionais legadas e **680 links** de
Dados/Radar/Conhecimento) são registros de rastreabilidade, não 748 conectores
funcionando. Não acionar coleta genérica de páginas ou downloads sem permissão,
layout e parser.

## Caminho E2E do SICARM

1. URL oficial fixa do SICARM: `portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt`.
2. HTTP sem redirects, MIME esperado, limite 120MB e bloqueio de página HTML/WAF.
3. Validação do layout de 16 colunas existente no NIVON, rejeição de IDs duplicados
   e gate de consistência municipal.
4. Armazenar **RAW completo** como `nivon/raw/original/CONAB_ARMAZENS_CAPACIDADE/<sha>.raw`
   em **bucket privado**, escrita imutável `if_generation_match=0`.
5. Criar derivado agregado por município/UF **sem razão social, e-mail, endereço ou ID do armazenador**,
   marcado como `capacidade cadastrada não equivale a estoque`.
6. Gravar derivado no mesmo ledger SQLite NIVON, subir RAW derivado + JSONL para GCS
   e executar MERGE idempotente na tabela `nivon_observacoes` do BigQuery.
7. Preservar a referência temporal como **snapshot da coleta** quando a fonte não
   informa uma data de referência própria. Sem publicação editorial automática.

## Caminho E2E BCB SGS

API oficial SGS 11 → `bcb_sgs_selic.normalizar_selic_diaria` existente →
`gravar_lote` existente → Cloud Storage RAW/JSONL → MERGE BigQuery.
Taxa diária em % ao dia, nunca meta anual. Dado ausente não vira zero.

## Configuração de Google Cloud necessária

A interface da conta e o custo não foram verificados. Sem gerar chave JSON de service account.
Usar WIF/OIDC GitHub com restrição de `repository` e `ref` do repositório NIVON,
permissões mínimas, bucket privado e dataset no mesmo projeto/região, se compatível.

Variáveis GitHub Actions que os workflows existentes e novos esperam:

- `NIVON_GCP_PROVIDER` — caminho exato do provedor WIF
- `NIVON_GCP_SERVICE_ACCOUNT` — service account dedicada
- `NIVON_BQ_PROJECT`, `NIVON_BQ_DATASET`, `NIVON_GCS_BUCKET` — recursos reais existentes
- `NIVON_GCP_OPERACIONAL_APROVADO=true` — gate de operação
- `NIVON_ZERO_COST_BQ_APPROVED=true` — gate de orçamento explicitamente aceito
- `NIVON_GCP_DIREITOS_DADOS=true` — gate de fontes públicas do lote já existente
- `NIVON_GCP_RIGHTS_EVIDENCE` — registro da base dos direitos por operação (sem token)
- `NIVON_FONTE_BCB_SGS_TAXA_SELIC_DIARIA_ATIVA=true` — ativação separada SGS
- `NIVON_FONTE_CONAB_ARMAZENS_CAPACIDADE_ATIVA=true` — ativação separada SICARM
- `NIVON_GCS_BUCKET_PRIVADO_VERIFICADO=true` — confirmar restrição de acesso ao
  bucket antes de armazenar o cadastro SICARM original, potencialmente pessoal

**Nunca** usar variável de aceite como prova independente de que os direitos
da fonte ou a privacidade do bucket foram efetivamente auditados.

Permissões mínimas práticas: Storage Object Creator/Viewer no bucket necessário,
BigQuery Data Editor restrito ao dataset de destino, BigQuery Job User no projeto
de execução, Workload Identity User na service account com condições por repositório.
A tabela de observações e o dataset devem existir; não provisionar
automaticamente. Auditar retenção, versionamento, acesso `allUsers`/uniform bucket,
quota BigQuery, localização dos dados, custo de armazenamento e backups.

## Ações pré-operacionais verificáveis

1. Confirmar `NIVON_BQ_PROJECT` real, existência da tabela `nivon_observacoes`
   e do bucket GCS privado no Google Cloud.
2. Confirmar WIF, service account, permissões por recurso e orçamentos.
3. Executar manualmente o coletor BCB SGS real e verificar snapshot SHA em GCS +
   linha correspondente no BigQuery, sem duplicata ao repetir.
4. Executar CONAB SICARM real depois de confirmar o bucket privado: validar que
   o RAW contém o cadastro somente em GCS e que o BigQuery contém apenas agregados.
5. Migrar o SQL atual de observações para **particionamento por data_referencia**
   sem quebrar os pipelines legados; a tabela existente de `nivon_observacoes`
   usa `referencia STRING` e está clusterizada, **ainda não particionada por data**.
6. Verificar custo real após primeiro lote e, somente então, liberar a cadência.

## Testes executáveis sem cloud

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_conectores_gcp_sgs_conab.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

O workflow `.github/workflows/fontes-google-cloud-conab-sgs.yml` usa
Workload Identity, executa da `main` somente com os gates de custo/direitos
e prevê SGS dias úteis e SICARM mediante execução manual. A rotina CONAB
não deve depender apenas da periodicidade cron; comparar SHA e estado de
publicação para detecção incremental.
