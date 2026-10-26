# NIVON — Segurança, CI, custos e governança (Frente 5)

Data de corte: 26/10/2026. **Este documento é um plano e um checklist, não uma declaração de implantação.** Repositório: `brunocapellari-dotcom/NIVON` (**público**). Nenhum segredo deve ser registrado neste arquivo, no histórico Git, em tickets ou em logs.

## 1. Configurações do GitHub — aplicação exclusiva pelo proprietário

**1A. Proteger a `main`** (aplicar **depois** de existir e ter executado com sucesso o job `ci`, para não bloquear inadvertidamente o fluxo):
1. Abrir `https://github.com/brunocapellari-dotcom/NIVON` → **Settings**.
2. Na seção **Code and automation** → **Rules** → **Rulesets** → **New ruleset** → **New branch ruleset**.
3. Nomear `nivon-main-protegida`; selecionar **Active**.
4. Em **Target branches** → **Add target** → **Include default branch** (confirmar `main`).
5. Deixar **Bypass list** vazia: não adicionar admin, proprietário ou GitHub App.
6. Marcar **Restrict deletions**, **Block force pushes** e **Require a pull request before merging**.
7. Em **Require a pull request**, escolher **Required approvals = 0**; não ativar requisito de revisão de outra pessoa.
8. Ativar **Require status checks to pass**; selecionar o check realmente publicado com nome **`ci`** no PR. Não inventar um check antes de ele existir. Não usar nomes de checks antigos.
9. Confirmar as regras e clicar **Create**. Abrir o ruleset salvo e verificar status **Active** e aplicação à `main`.
10. Prova: PR de teste recebe o check `ci`; push direto, exclusão e force-push não são permitidos. Não executar force-push real apenas para comprovar.

**1B. Ambiente `producao`:**
1. **Settings** → **Environments** → **New environment** → nome exato **`producao`**.
2. Em **Deployment protection rules**, marcar **Required reviewers** e selecionar o perfil do proprietário `brunocapellari-dotcom`.
3. **NÃO** marcar **Prevent self-reviews**: com um único mantenedor, impediria a aprovação do deploy por ele próprio.
4. Em **Deployment branches and tags**, selecionar **Selected branches and tags** → adicionar apenas **`main`**; não permitir tags genéricas.
5. Salvar. Todo job que realmente pode implantar em produção deve declarar `environment: producao`; apenas criar o ambiente não protege workflows que não o usam. Verificar o bloqueio por revisão em execução manual de teste **sem** conceder permissões amplas.

**1C. Detecção de segredos e dependências:**
1. **Settings** → **Advanced Security** (em **Security and quality** ou área equivalente da interface).
2. Ativar **Secret scanning / Secret Protection** quando disponível e **Push protection**; conferir status ativo de ambos.
3. Ativar **Dependabot alerts** e manter **Dependency graph** habilitado.
4. Em **Security**, revisar alertas existentes; alertas de credenciais reais exigem **rotação imediata no provedor**, não apenas exclusão do arquivo.
5. Se uma configuração não aparecer, registrar a limitação do plano ou disponibilidade; não substituir por uma alegação de que está ativa.

Referências GitHub: [rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository), [environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), [secret scanning](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/detect-secret-leaks/enable-secret-scanning), [Dependabot](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-dependabot-alerts).

## 2. Pipeline único CI e migração sem indisponibilidade

Arquivo-alvo: `.github/workflows/ci.yml` com job obrigatório `ci`, disparado em **todo** PR e push da `main`, sem filtros de caminho. Executa Python 3.11, `compileall`, `pytest`, `ruff` (F2), build + smoke offline de `Dockerfile.terminal` (F3) e `Dockerfile.coletor` (F4), sem OIDC e sem segredos. O teste de publicação examina o catálogo `config/fontes.yaml` (F4) e impede qualquer anexo público de séries restritas. Faltando contrato ou artefato de F2/F3/F4, deve **falhar fechado**; não marcar verde com `continue-on-error` nem mascarar módulos ausentes.

Não eliminar CI antigo antes de **dois dias de execuções verdes reais** do novo `ci` e da validação das três frentes. Remoções só após revisão dos respectivos donos de arquivo/workflow. Os workflows de deploy devem permanecer separados, protegidos e sem implantação em PR.

## 3. Varreduras

`.github/workflows/seguranca.yml`: Gitleaks (nenhum artefato gerado e sem comentar dados sensíveis em PR), pip-audit em requisitos travados e CodeQL/Python. Triggers: PR, segunda-feira e manual; acesso mínimo; sem credenciais GCP.

`.github/dependabot.yml`: verificações semanais de `pip` e `github-actions` com limite de três PRs abertas por ecossistema. A F2 deve fornecer arquivo de dependências travadas **com fechamento transitivo**. O arquivo legado `requirements/antt-rgi.txt` não representa todas as dependências do NIVON e auditá-lo isoladamente não valida a cadeia toda.

## 4. Proposta IAM e identidade Google Cloud — AGUARDA APROVAÇÃO

Não executar nem aplicar até autorização explícita de Claude e do proprietário. Infraestrutura desejada: projeto `nivon-data`, região `southamerica-east1`, sem chaves JSON de Service Account e sem credenciais em PR.

| Identidade | Acesso proposto | Escopo mínimo |
|---|---|---|
| `nivon-deploy` | `roles/run.developer`, `roles/cloudbuild.builds.editor`, `roles/artifactregistry.writer`; `roles/iam.serviceAccountUser` somente sobre as outras duas identidades | Projeto para Run/Build, **um** repositório no Artifact Registry e **duas** service accounts para actAs |
| `nivon-coletor` | GCS somente objetos necessários, escrita nos datasets `nivon_raw`, `nivon_stage`, `nivon_core`; `roles/bigquery.jobUser` | Bucket escolhido, datasets específicos, criação de jobs no projeto |
| `nivon-terminal` | Leitura apenas do `nivon_mart` e `roles/bigquery.jobUser` | Dataset `nivon_mart` e jobs no projeto |

No BigQuery, usar `roles/bigquery.dataEditor` somente nos três datasets do coletor e `roles/bigquery.dataViewer` somente no `nivon_mart` para o terminal. No GCS, começar com `roles/storage.objectCreator` no bucket autorizado; acrescentar `objectViewer` caso readback/replay exija. Evitar `storage.admin` e `bigquery.admin`. Atualizar o leitor do terminal **somente depois** de a F3/F4 garantir `nivon_mart` (atualmente os fluxos ainda dependem de outros datasets).

No provedor Workload Identity Federation destinado a jobs do GitHub, condicionar **conjuntamente** as claims do token a:
```text
assertion.repository == 'brunocapellari-dotcom/NIVON' &&
assertion.ref == 'refs/heads/main' &&
assertion.environment == 'producao'
```
Usar também o identificador imutável do repositório (`repository_id`) e do proprietário (`repository_owner_id`) quando possível, após verificar os IDs no GitHub/GCP. O mapping e o binding `roles/iam.workloadIdentityUser` devem restringir **exclusivamente** a identidade de deploy e o repositório; nunca permitir fork, pull request nem outro environment. `environment: producao` precisa existir no job de deploy e a revisão humana é obrigatória.

**Conflito a resolver na aprovação:** auditar IAM e faturamento de forma realmente somente leitura exige permissões extras que não estão nas três identidades acima. Não adicionar `roles/viewer` e permissões de faturamento ao deploy apenas para fazer a auditoria parecer completa. Escolher auditoria humana no Console, ou uma **quarta identidade auditora** de leitura restrita, aprovada separadamente. O workflow `auditoria-gcp.yml` só poderá anunciar validação das dimensões que efetivamente consultar.

Após migração validada: revogar papéis amplos **antigos**, um a um, com rollback planejado, sem inutilizar o runtime nem tentar apagar a conta antes de comprovar os três novos acessos.

## 5. Custos — orçamento com aviso, não limite rígido

No **Google Cloud Console** → **Billing** → selecionar conta de faturamento do projeto `nivon-data` → **Budgets & alerts** → **Create budget**:
1. Nome: `NIVON — alerta 10 BRL`.
2. Scope: somente projeto `nivon-data`, considerando todos os serviços.
3. Período: **Monthly**; valor **10** na moeda de faturamento **se a conta for BRL**. Se não for BRL, converter explicitamente na cotação usada e registrar o valor/câmbio; não rotular uma quantia USD como R$ 10.
4. Configurar alertas em **50%, 90% e 100%** e destinatários da cobrança.
5. Confirmar o orçamento visível. **Alertas não impedem cobranças nem desligam serviços**; Cloud Build, BigQuery, Cloud Run, GCS e rede devem ter limites complementares.

## 6. Inventário inicial dos nove segredos referenciados em código

O inventário abaixo descreve **nomes e referências no código**, não confirma presença no GitHub Secrets (essa listagem é restrita ao proprietário). Nenhum valor foi lido.

| Nome | Uso conhecido | Decisão proposta |
|---|---|---|
| `NIVON_IA_OPENAI_API_KEY` | `nivon-integracoes-ia-pilotos.yml`, piloto PageIndex/IA | Remover **após** encerrar piloto, se terminal e coletor não usarem |
| `FIRECRAWL_API_KEY` | mesmo workflow, extração IA | Remover se fora do pipeline homologado |
| `PAPERCLIP_API_KEY` | mesmo workflow, tarefas IA | Remover se fora do terminal e coletor |
| `NIVON_HINDSIGHT_API_KEY` | mesmo workflow, consulta de memória | Remover se fora do terminal e coletor |
| `NIVON_ANA_IDENTIFICADOR` | `acessos-privados.yml`, ANA | Manter só se a F4 homologar coletor ANA privado |
| `NIVON_ANA_SENHA` | `acessos-privados.yml`, ANA | Igual à identificação ANA; evitar envio a workflows gerais |
| `NIVON_INMET_BDMEP_URL` | `acessos-privados.yml`, INMET | Manter apenas se coletor autorizado necessitar do acesso |
| `NIVON_ZARC_NEON_DSN` | `nivon-gcp-zarc.yml`, ponte Neon | Propor remoção **depois da migração/validação da F4** |
| `AGROBR_USDA_API_KEY` | `acessos-privados.yml`, USDA | Manter apenas se o coletor USDA com licença aprovada utilizar |

Nenhum segredo deve ser excluído até mapear consumidores efetivos no novo coletor/terminal. A remoção, rotação e revisão de escopo no GitHub e nos provedores são exclusivas do proprietário.

## 7. Etapa final, após integração de F2, F3 e F4

1. Fixar **todas** as ações restantes por SHA completo; impedir execução de workflows legados.
2. `permissions:` mínimas por job: `contents:read` no CI; `id-token:write` **somente** em deploy sob `producao`; `security-events:write` apenas no CodeQL.
3. Nenhum workflow restante publica anexos com séries de fontes restritas; preferir **nenhum** `upload-artifact` e nenhum release com dados.
4. Retirar os portões `*_APPROVED` do código **somente depois** da proteção real pelo Environment e IAM.
5. Gerar automaticamente, a partir dos nomes efetivamente existentes, o relatório **53 variáveis a excluir / 8 a manter**. A API conectada não permite consultar os valores/lista completa de variáveis e segredos do GitHub; não inventar nomes e não pedir exposição de valores.
6. Após autorização do proprietário, excluir as variáveis na interface GitHub e verificar que nenhum workflow ainda as referencia.
7. Fazer aceite demonstrável: ruleset `main` ativo, `ci` obrigatório verde durante dois dias, segurança e CodeQL executando, IAM real com menor privilégio, orçamento visível, terminal privado autenticado e catálogo F4 auditado.

**Situação na criação desta documentação:** inspeção realizada; controles do Console, WIF, orçamento, remoções e homologação **não executados**.
