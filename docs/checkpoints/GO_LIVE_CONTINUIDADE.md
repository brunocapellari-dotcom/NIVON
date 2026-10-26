# Continuidade NIVON — primeiro bloco de código para go-live

Branch de integração: `codex/go-live-checkpoint`. Base de origem `97f032d` da
main. A main não foi mesclada, alterada ou publicada por esta sessão.
Backlog lido na PR #302, ref `d34b4ec1b76a45701f33131ba54785c42124faa2`.
PRs #276/#283 inspecionadas; issues #286/#288/#289/#287/#290/#291 consultadas
abertas em páginas públicas do GitHub. Estados não foram alterados.

## Commits e revisão

| Issue | Branch | Commit de implementação | Base sugerida da PR |
|---|---|---|---|
| #286 | codex/286-remove-vercel | 2b7a1e0 (checkpoint adicional 8a20dc1) | main |
| #288 | codex/288-gcp-readiness | d393298 | main |
| #289 | codex/289-antt-reader-contract | 6068079 | main |
| #287 | codex/287-single-private-interface | bfc703f | codex/289-antt-reader-contract |
| #290 | codex/290-operation-smoke | 370ed83 | codex/287-single-private-interface |
| #291 | codex/291-source-health | 35a70c4 | main |

Branches enviadas ao origin. Integração feita apenas na branch de checkpoint,
preservando commits individuais e sem resolver conflitos artificialmente. Não
abrir PRs duplicadas: verificar primeiro se outro operador já abriu alguma para
essas branches. Cada `ISSUE_*.md` contém entrega, testes, bloqueios e continuidade.

## Evidência do conjunto

- Suíte Python integrada: **792 testes, sem falhas, 2 ignorados** por pyarrow
  opcional no teste Parquet dedicado.
- Node integrado: **15 testes aprovados**, incluindo JS real com DOM/fetch
  simulados, estados da fonte, zero/ausência e remoção de configs legadas.
- HTTP local sintético: raiz, assets, API, health e readiness, inclusive 503
  para fonte defasada e erros sanitizados. Não é autenticação IAM real.
- Wheel da interface produzido, instalado fora do checkout e HTTP exercitado
  com consulta sintética injetada; assets empacotados verificados.
- `git diff --check` aprovado. Nenhum frontend novo, coletor, banco, cron,
  serviço ou projeto GCP foi criado.

## Bloqueios externos e limites de evidência

1. **PR/CI GitHub:** API REST e GraphQL retornam `Forbidden`, inclusive fora do
   sandbox. Fetch/push Git e páginas públicas funcionam. `gh pr create` foi
   tentado sem sucesso. PRs não foram criadas, comentários não foram publicados,
   CI remoto não foi confirmado. Não há revisão/merge automático.
2. **Google Cloud LIVE:** configuração NIVON/gates e URL do terminal não estão
   informados neste processo. Há binding de credencial Google; não é evidência
   de credencial inválida ou recurso inexistente. Pré-voo retorna
   `CONFIGURACAO_PENDENTE`, smoke retorna `BLOCKED`. Nenhuma query faturável,
   token de smoke, criação de recurso, deploy, IAM ou gasto novo foi realizado.
3. **Imagem Docker:** build local falhou por `CERTIFICATE_VERIFY_FAILED` na
   instalação pip dentro da imagem base, por trust da CA do proxy ausente.
   Verificação TLS foi preservada. Imagem não está validada; não extrapolar essa
   falha de ambiente para Cloud Build. Primeiro corrigir trust pelo mecanismo
   suportado, sem trusted-host/disable TLS.
4. CI local e contrato simulado não são homologação, dados reais atualizados,
   serviço Cloud Run ativo ou rollback realizado. Go-live #281 continua pendente.
5. Radar #291 disponibiliza JSON puro; não ativa leitura/polling de fontes ou
   integração LIVE do painel. Nenhuma homologação agro é concedida pelo código.

## Próxima atividade já selecionada

**#296 — reconciliação Neon → BigQuery**, issue pública consultada aberta.
Antes de implementar, inspecionar PRs #155/#171/#192/#217 e issue #59, schema
`database/bigquery/nivon_neon_legado_schema.sql`, exportador PTAX e documentação
`NIVON_PTAX_NEON_BIGQUERY_OPERACAO.md`. Não duplicar reconciliador existente.
Comparar fonte/chave/vintage/período/checksum/ausência e produzir diferenças em
JSON, com testes E2E sem credenciais; não desligar writer, migrar ou excluir Neon.

Depois: #292/#94, #294 e #297, seguindo o backlog. Consultar o estado atual do
GitHub antes de cada bloco. Leitura LIVE, IAM, segredos, novos gastos, deploy,
publicação pública, exclusão irreversível e merge na main continuam dependentes
das aprovações específicas do proprietário. Trabalho offline reversível segue
autorizado; não pedir confirmação por etapa.
