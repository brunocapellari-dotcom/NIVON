# NIVON — Lote de engenharia de dados: isolamento por fonte e recuperação GCS → BigQuery

## Contexto
A cadeia #147 → #163 mantém o coletor, o parser, o ledger SQLite, o armazenamento
GCS e o MERGE BigQuery. Esta alteração **não cria outro pipeline** e não ativa
recursos GCP. Opera sobre a branch #163; `main` só deve receber a cadeia
após reconciliação das dependências e execução dos gates.

## P0 corrigido — datasets misturados
Antes, `planejar_envio` exportava todos os snapshots do banco local. Se um lote
PTAX NORMALIZED dividisse SQLite com IMEA/CONAB QUARANTINED, a existência da
quarentena impediria a carga permitida. Agora o escopo opcional
`fonte_dataset` restringe **simultaneamente**:
1. consulta de snapshots/RAW e verificação de hashes;
2. JSONL de observações selecionadas;
3. manifesto GCS do lote e destino do MERGE.

Os CLIs PTAX, IBGE/PAM, IMEA, SICARM/CONAB e BCB/SGS usam IDs de dataset
explícitos. A assinatura antiga sem escopo continua fail-closed (quarentena
mista não habilita BigQuery). Cada execução pode usar o mesmo SQLite
persistente sem enviar linhas de fontes vizinhas.

## P0 corrigido — recuperação independente do runner
O manifesto content-addressed (v1.1.0) inclui recibo da carga com SHA-256
do JSONL, contagem de linhas e projeto/dataset de destino. Como o manifesto
e o JSONL são enviados **antes** do MERGE, uma falha após o arquivamento
deixa evidência suficiente para recuperar o estágio no próprio GCS.

`reprocessar_bigquery_do_manifesto` baixa o manifesto e o JSONL do bucket
privado, verifica SHA, limites e metadata, confere a identidade do destino,
o número de linhas e a filiação de cada `snapshot_id` ao manifesto,
e invoca o carregador BigQuery original (MERGE idempotente).
Não depende do SQLite original e não faz HTTP à fonte.

Manifestos apenas RAW/QUARANTINED não têm recibo de BigQuery e são
**bloqueados para promoção**. Replays não permitem trocar destino
nem aceitar stage adulterado.

## Interface
Inspeção inerte (não acessa a nuvem):
```bash
PYTHONPATH=src python scripts/reprocessar_manifesto_gcp.py --manifesto-sha <sha256>
```

Execução apenas após checar projeto, bucket privado, dataset/tabela existentes,
WIF/ADC, permissões, orçamento e direito da fonte:
```bash
PYTHONPATH=src python scripts/reprocessar_manifesto_gcp.py --manifesto-sha <sha256> --executar
```

Variáveis exigidas: `NIVON_GCS_BUCKET`, `NIVON_BQ_PROJECT`,
`NIVON_BQ_DATASET`, `NIVON_GCP_RIGHTS_EVIDENCE` e booleanos
`NIVON_GCP_OPERACIONAL_APROVADO`,
`NIVON_GCP_DIREITOS_DADOS`, `NIVON_ZERO_COST_BQ_APPROVED`
todos `true`. A flag não configura IAM nem autoriza custos por si só.

## Testes de integração (sem nuvem nem downloads)
```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_gcp_lotes_replay.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_persistencia_google_cloud.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_conectores_gcp_sgs.py' -v
```

Cobertura: duas fontes no mesmo banco; isolamento de stage/RAW;
falha de MERGE após GCS; destruição do banco local; replay somente GCS;
imutabilidade dos uploads; SHA adulterado; destino diferente; quarentena
sem promoção; autorização fail-closed.

## Limites e próximo incremento
- Homologação real de bucket, objeto, identidade WIF e BigQuery ainda pendente.
- O DDL legado conserva referência temporal como texto; particionamento por
  data_referencia precisa de migração com backfill e comparação de totais.
- Recuperação é **manual e explícita**; não há monitor agendado de manifestos
  órfãos nem declaração de operação contínua.
- Não promover automaticamente CONAB SICARM nem IMEA a observações canônicas.
- Sem merge na main, deploy, custos novos, dados reais ou credenciais nesta PR.
