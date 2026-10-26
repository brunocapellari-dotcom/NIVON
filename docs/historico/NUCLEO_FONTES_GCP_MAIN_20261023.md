# NIVON — núcleo de coleta real independente (PR curto para main)

Este conjunto foi isolado da frente de catálogo expandido para que os coletores reais
possam integrar a branch principal **sem absorver centenas de commits de outros projetos**.

## O que faz
- BCRA Argentina v4, preços secundários granos.ar, grãos Canada, PLD horário CCEE:
  busca HTTP HTTPS em domínios permitidos, verifica contrato, dados e formato.
- Guarda RAW por SHA-256 e observações versionadas em SQLite no estágio local.
- Arquiva RAW no Google Cloud Storage com verificação de integridade antes da carga
  no BigQuery; snapshots já existentes têm identidade e SHA conferidos.
- Insere observações no BigQuery por staging+MERGE, com datas de referência, coleta,
  publicação e competência; tabela particionada por data de referência.
- Backfill de edições anuais CCEE e Canadian Grain Commission, executado manualmente
  com até cinco anos por lote na nuvem e exportação segmentada.
- Rotina recorrente programada para dias úteis (CCEE/Canada 1x semana);
  seu agendamento só roda **quando incorporado à main e com configuração válida**.

## Condições necessárias para operação contínua no Google Cloud
No repositório, configurar as variables do GitHub:
- `NIVON_GCP_PROVIDER`: identificador do provedor Workload Identity Federation.
- `NIVON_GCP_SERVICE_ACCOUNT`: conta de serviço GCP limitada ao NIVON.
- `NIVON_BQ_PROJECT` e `NIVON_BQ_DATASET`: projeto e dataset já existentes.
- `NIVON_GCS_BUCKET`: bucket Cloud Storage já existente.
- `NIVON_ZERO_COST_BQ_APPROVED=true` e `NIVON_RAW_ARCHIVE_APPROVED=true`:
  habilitação explícita das operações após avaliação das licenças, limites e custos.
- `NIVON_BQ_BOOTSTRAP_TABLE_APPROVED=true`: opcional e temporária, permite
  criar a tabela particionada no dataset existente; não cria bucket nem dataset.

IAM mínimo: GitHub OIDC federado para SA com permissão restrita no bucket
(ler metadados/criar objetos) e dataset (executar jobs, consultar e gravar tabela).
Permissão de criar tabela somente durante bootstrap. Não usar chave JSON no GitHub.

**Nenhuma variável é preenchida pelo código** e nenhuma operação Cloud é executada
enquanto faltarem permissões e pré-voo. Limites de bytes e variáveis não garantem
faturamento R$0; configurar alertas de orçamento GCP.

## Evidência
Na branch de desenvolvimento anterior, GitHub Actions coletou e normalizou
**28.416 linhas de PLD CCEE**, **11.786 registros de grãos canadenses**,
**10 observações granos.ar** e **4 séries BCRA** em estágio efêmero,
com HTTP real e testes offline aprovados. Isso **não significa persistência
na nuvem confirmada**. O PR estreito para main reaproveita o núcleo, não o catálogo
inteiro. As demais fontes permanecem fora desta etapa operacional.

## Rotas operacionais
- Manual: `python scripts/operar_fontes_reais.py --canada --ccee`
- Histórico local: `python -m scripts.backfill_fontes_reais --fonte BR_CCEE_PLD --inicio 2023 --fim 2025 --executar`
- Histórico Cloud sob OIDC: `python -m scripts.backfill_fontes_cloud --fonte BR_CCEE_PLD --inicio 2023 --fim 2025 --projeto PROJECT --dataset DATASET --bucket BUCKET --executar`
- Ações GitHub: `coleta-recorrente-fontes.yml`, `backfill-fontes-gcp.yml`.

Data do levantamento e integração: 23/10/2026.
