# NIVON — Auditoria agregada da origem PTAX (21/10/2026)

**Fonte operacional:** Neon, projeto `divine-lab-03469752`, banco `nivon`, tabela `public.nivon_ptax_quotes`.

**Verificação real:** consulta **somente leitura**, via conexão Neon, executada em 21/10/2026 **22:58:24 UTC**. O SQL versionado encontra-se em `database/neon_ptax_readonly_audit.sql`. Não foi alterado nenhum dado Neon, trigger ou agendamento.

## Medidas confirmadas

| Indicador | Resultado |
| --- | ---: |
| Linhas de cotação USD + EUR | 796 |
| USD (linhas / datas distintas) | 133 / 133 |
| EUR (linhas / datas distintas) | 663 / 133 |
| Execuções | 14 |
| Execuções com SUCCESS | 14 |
| Execuções com ERROR | 0 |
| Checkpoints | 14 |
| Duplicações de chave de negócio | 0 |
| Registros com preço não positivo | 0 |
| Timestamp de verificação anterior à coleta | 0 |
| Publicação suspeita posterior à verificação | 0 |

Histórico por **ano de referência** (a presença de linhas em dois extremos não significa cobertura do intervalo):

| Ano | USD: datas / linhas | EUR: datas / linhas |
| --- | --- | --- |
| 2020 | 126 / 126 | 126 / 628 |
| 2021 | 0 / 0 | 0 / 0 |
| 2022 | 0 / 0 | 0 / 0 |
| 2023 | 0 / 0 | 0 / 0 |
| 2024 | 0 / 0 | 0 / 0 |
| 2025 | 0 / 0 | 0 / 0 |
| 2026 | 7 / 7 | 7 / 35 |

Datas mínima e máxima de referência da origem: **02/01/2020** e **21/10/2026**. Última verificação da EUR **22:05:03 UTC** e USD **22:05:02 UTC** em 21/10/2026. Essas contagens são um retrato daquele instante e podem mudar com o backfill; não representam uma série anual completa.

## Contrato de validação

O script `scripts/validate_ptax_source_manifest.py` aceita o campo `source_audit_manifest` do resultado da consulta SQL, ou seu objeto JSON interno. Ele reconcilia totais USD/EUR com somas por ano, conta datas distintas, detecta inconsistências de fonte, contagem e contratos e lista **anos inteiros ausentes**. Não reclassifica lacunas de cobertura como erros do coletor: a aquisição histórica continua.

A validação pode ser feita offline, com um arquivo contendo **somente o manifesto agregado** (não contém preços):

```sh
python3 scripts/validate_ptax_source_manifest.py --input /tmp/nivon-ptax-agg-audit.json
```

O relatório de saída expõe apenas medidas agregadas, sinaliza os anos 2021–2025 ausentes e mantém **historical_coverage_verified=false**, **external_backup_restore_verified=false**, **bigquery_data_verified=false** e **migration_or_cutover_approved=false**. Mesmo se houver registros em todos os anos, isso NÃO comprova cobertura diária nem homologa restauração de backup.

**Limitações:** zero erros de runs observados não garante execução futura, licença de armazenamento, fonte primária completa, backup independente, cobertura de pregões nem carga GCP. Consulta agregada não gera backup imutável. A existência de 14 checkpoints não significa 14 dias ou janelas históricas completas.

## Próxima ação

1. Não substituir Neon nem interromper os triggers; aguardar e validar as janelas de backfill com cobertura real e calendário do BCB.
2. Confirmar **billing_status** e IAM do projeto Google Cloud `nivon-data` por evidência autenticada da auditoria Cloud Shell; o resultado da execução anterior **não está acessível a partir daqui**.
3. Preparar backup privado, restauração de teste e importação em ambiente isolado, com critérios de hash e deduplicação; manter bloqueado qualquer deploy pago ou migração automática não autorizada.
4. Repetir auditoria agregada no Neon antes e após cada cópia e só comparar snapshots equivalentes.

Relatórios relacionados: `docs/MIGRACAO_NEON_PTAX_BIGQUERY.md` e PR #84. Nenhuma credencial, cotação individual nem arquivo privado deve entrar no repositório público.
