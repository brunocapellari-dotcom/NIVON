## Problema e entrega
Remove as configurações de deployment Vercel da raiz e da prévia técnica, preservando os frontends e o handler BCB existentes. O servidor de entrada continua sendo `nivon.terminal_web` e a imagem/fluxo Cloud Run existentes; nenhum servidor ou recurso adicional foi criado.

Headers dos assets são preservados em JSON neutro como contratos para a consolidação #287. Os JSON não são carregados pelo servidor atual. CI e testes deixam de depender dos arquivos removidos.

Refs #286. Commit: 2b7a1e0. Não fecha #281 nem afirma integração completa do portal estático.

## Validação local
- Suíte Python: 754 testes, sem falhas; 2 skips opcionais de Parquet.
- Node: 12 testes aprovados (contratos do frontend, BCB, falhas e remoção de configurações).
- Sintaxe dos três arquivos JS e `git diff --check` aprovados.
- Testes `test_terminal_web` incluídos na suíte; nenhuma consulta BigQuery real.

## Limites e continuidade
Sem deploy, alteração de IAM, novos gastos, exclusão de recursos externos ou merge. CI remoto ainda precisa executar neste commit. Próxima atividade: #288, pré-voo GCP read-only. Backlog conferido na PR #302 e PRs #276/#283 inspecionadas via refs Git.

### Checkpoint de publicação
Branch `codex/286-remove-vercel` enviada ao origin; commit de implementação
`2b7a1e0`. Abertura de PR tentada com `gh pr create --body-file`; a API GraphQL
retornou `Forbidden`. A API REST também retornou `Forbidden`, inclusive fora do
sandbox. Leitura de páginas públicas e fetch/push Git funcionam. Não há PR criada
ou CI remoto confirmado por esta sessão. Este arquivo contém o corpo preparado
para a PR. Próxima branch independente: `codex/288-gcp-readiness`.
