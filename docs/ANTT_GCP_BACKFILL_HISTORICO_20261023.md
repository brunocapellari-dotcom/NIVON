# NIVON — Backfill ferroviário ANTT/SIADE por lotes no BigQuery

Primeira carga 2026 **já comprovada**: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188 (tentativa 2). Primeiro ranking por polo: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984168784.

## Lote histórico novo: 2022–2025

- Workflow: .github/workflows/nivon-antt-backfill-2022-2025.yml.
- Coletor: nivon.coleta_antt (consulta catálogo oficial ANTT CKAN e baixa os quatro CSVs; verifica schema, competência, TU/TKU, SHA-256, manifesto).
- Execução: nivon.antt_gcp_backfill_historico (verifica TODOS os arquivos e metadados GCP antes de qualquer escrita, arquiva por SHA no bucket, anexa snapshot à tabela ANTT existente no BQ, compara COUNT e SOMA(TU) de cada ano após carga e registra progresso anual).
- Projeto/dataset/bucket fixos: nivon-data, nivon_raw, nivon-data-raw-2026.
- SEM autorização para criar projeto, bucket, dataset ou tabela nova. A tabela já existe desde o piloto 2026.
- Todos os CSVs com mais de 2 MB, o lote com mais de 6 MB, um ano com mais de 15 mil registros ou o total com mais de 42 mil registros bloqueiam a escrita antes do primeiro upload.
- Cada consulta de reconciliação usa máximo 50 MB de bytes processados faturáveis. Há também consultas internas de contagem por SHA com limite de 50 MB cada.
- Um lote contém **no máximo 4 anos consecutivos, somente entre 2006 e 2025**.
- Erro em um ano interrompe a expansão, mas as gravações verificadas anteriormente no lote permanecem append-only, idempotentes e identificadas por SHA.
- Artefato do GitHub com evidência por ano, hashes e totais; nenhuma planilha CSV bruta é armazenada no GitHub. Arquivos temporários removidos do runner.
- Workflow sem schedule; a gravação única é executada no primeiro push do novo workflow para main, ou via dispatch confirmado em main. As variáveis de autorização da atualização recorrente continuam inalteradas.

**Aviso de custo:** limites de bytes e jobs reduzem exposição, mas **não garantem custo zero**; cobrança de Cloud Storage, BigQuery ou GitHub Actions depende de preços/franquias. Alertas de faturamento GCP, se configurados, não impõem corte automático. Não foi feita alteração em IAM nem na conta de faturamento.

## Próximos passos, condicionados à execução real

Se 2022–2025 passar: obter contagens e TU por ano no BQ e atualizar o cadastro de cobertura. Backfill 2018–2021, 2014–2017, 2010–2013 e 2006–2009 deverá reutilizar o mesmo executor em lotes curtos; não declarar esses períodos carregados sem prova de job de carga e reconciliação. Atualizações recorrentes permanecem desativadas.

**Não confundir** toneladas ferroviárias por estação de origem com toneladas descarregadas de caminhões, transbordos reais, volumes MDF-e, fretes pagos ou volume único de grãos ao longo de todas as modalidades.
