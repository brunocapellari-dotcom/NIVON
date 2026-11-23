# NIVON — Migração do Neon para Google Cloud (23/10/2026)

## Objetivo e critério verificável

BigQuery é o destino de longa duração. **Neon é legado transitório**: somente desligar coletores e remover funções depois de duas cargas GCP em dias distintos, equivalência por chave/vintage, frescor e restore. A autorização do proprietário para migrar não garante que IAM/billing GCP já estejam conectados à conversa.

**Estado em 23/10/2026:** duas pontes de leitura Neon autenticadas: PTAX (5.529 registros) e demais fontes (1.092 registros). **6.621 registros extraídos/validados, 0 cargas GCP comprovadas**. Os snapshots ficam em arquivos efêmeros privados no GitHub Actions e não são anexados nem publicados. O reprocessamento é possível no Neon enquanto ocorrer a transição.

### Fontes e destino

| Fonte | Registros exportados | Tabela pretendida | Condição |
|---|---:|---|---|
| PTAX/BCB | 5.529 | `nivon_core.ptax_quotes` | Data de referência, vintage e moeda preservados |
| IMEA soja/milho/algodão/boi | 1.012 | `nivon_stage.neon_legado` | **Sem data de referência**, data de publicação somente |
| CEPEA | 30 | `nivon_stage.neon_legado` | Página original indisponível em alguns jobs; histórico não comprova frescor |
| CONAB safras | 4 | `nivon_stage.neon_legado` | Safra/competência e publicação distintas |
| CONAB balanços | 14 | `nivon_stage.neon_legado` | Datas e unidades originais |
| CONAB séries | 32 | `nivon_stage.neon_legado` | Sem inventar data de referência |

O dataset `nivon_stage` é área de **proveniência e quarentena**. Não substituir os motores analíticos por dados ainda não homologados. O conjunto `nivon_core` contém PTAX canônica e abrigará séries homologadas por fonte.

## O que já roda

- [GitHub Actions migração legada](https://github.com/brunocapellari-dotcom/NIVON/actions/workflows/nivon-gcp-migracao.yml): `/checkpoint` e `/export` da função privada `nivonlegacy`, atrelada a OIDC GitHub por repository/ref/workflow, com paginação por id BIGINT e JSON decimal preservado como texto.
- `scripts/nivon_gcp_migracao.py`: cinco contratos, hash normalizado, checkpoint, corte de IDs, limite de payload, validação, escrita BigQuery **opcional e bloqueada por padrão**, MERGE e reconciliação do lote.
- [Ponte privada PTAX](https://github.com/brunocapellari-dotcom/NIVON/actions/workflows/ptax-neon-private-export.yml): exportação diária sem write GCP, até migração.
- `database/bigquery/nivon_neon_legado_schema.sql` e `database/bigquery/nivon_ptax_schema.sql`: modelos de destino versionados.
- `scripts/bootstrap_nivon_gcp.sh`: **um bootstrap manual via Cloud Shell** que verifica projeto/billing antes de habilitar APIs, WIF, serviço de conta, ACL dos datasets e tabelas. Sem --aplicar apenas diagnostica.

## Ação indispensável do administrador do GCP (uma vez)

Este ambiente não possui conexão direta habilitada para BigQuery. No [Cloud Shell](https://console.cloud.google.com/?project=nivon-data), com conta que possua direitos sobre projeto e IAM:

```bash
git clone --depth=1 https://github.com/brunocapellari-dotcom/NIVON.git
bash NIVON/scripts/bootstrap_nivon_gcp.sh
# Somente após revisar cobrança e permissões:
bash NIVON/scripts/bootstrap_nivon_gcp.sh --aplicar
```

Se `git clone` já existir, atualizar o clone antes de aplicar. O comando `--aplicar` **pode gerar faturamento** pelo uso futuro do Google Cloud; conferir preços, orçamento e cotas antes.

O script imprime dois valores não secretos a registrar no GitHub, em **Settings → Secrets and variables → Actions → Variables**:

- `NIVON_GCP_WIF_PROVIDER` = caminho do provider exibido
- `NIVON_GCP_SERVICE_ACCOUNT` = conta de serviço exibida

Após avaliar o limite de custo e a disponibilidade, o operador habilita:

- `NIVON_GCP_WRITE_APPROVED=true`
- `NIVON_GCP_COST_REVIEWED=true`

Não registrar chaves JSON de contas de serviço; usar federação OIDC. Condição WIF limitada a `main` e a dois workflows específicos. O serviço dispõe de `bigquery.jobUser` no projeto e acesso WRITER somente aos datasets `nivon_core`/`nivon_stage`.

## Gates de corte definitivos

1. Validar que `nivon-data` realmente existe, possui billing ativo e IAM previsto.
2. Criar tabelas e autorizar WIF por operador habilitado; pipeline testar conexão sem imprimir credenciais.
3. Executar fluxo GCP real: lote PTAX + todos os cinco legados. Contar e reconciliar **6.621 registros do corte inicial** (recontar na hora: PTAX pode aumentar com o backfill). Diferenças devem bloquear.
4. Reprocessar as atualizações posteriores à primeira extração; validar identidade/vintage, valor decimal, período, duplicatas e datas por fonte.
5. Executar dois ciclos em datas distintas e consultar diretamente `nivon_core.ptax_quotes` e `nivon_stage.neon_legado`.
6. Implantar/validar **coletores diretos nas fontes originais com escrita GCP** para PTAX, CEPEA, IMEA e CONAB; a simples cópia periódica do Neon não remove dependência.
7. Só então desabilitar agendamentos Neon/GitHub que escrevem no Neon, manter snapshot restaurável e observabilidade por 7 dias, sem excluir dados imediatamente.
8. Após aprovação explícita do corte irreversível, desativar funções Neon e decidir retenção/remoção conforme política e requisitos de auditoria.

Sem WIF configurado o workflow faz **somente extração e validação**, ou falha de forma fechada. Não classificar a migração como concluída com base no README.

## Evidências

- CEPEA + IMEA + CONAB: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39951704162
- PTAX: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947905419
- Google Cloud WIF: https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
