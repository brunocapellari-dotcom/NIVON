# M1 — Roteiro para o Bruno: terminal NIVON privado ANTT + IAP

**Estado desta PR:** apenas código e testes offline. **Nenhum merge, recurso, IAM, deploy, aprovação ou URL real foi criado.** Só declarar M1 concluído após URL Cloud Run real, login IAP no celular e leitura ANTT.

**Projeto:** `nivon-data` · **região:** `southamerica-east1` (São Paulo) · **serviço:** `nivon-terminal` · **dataset:** `nivon_raw` · **repositório Docker escolhido:** `nivon-terminal-docker` · **ID da SA de execução escolhido:** `nivon-terminal-exec`.

## 1 — Google Cloud Console: serviços e custos

1. Abra [Console GCP](https://console.cloud.google.com/?project=nivon-data), seletor superior de projeto → **nivon-data**.
2. Menu ☰ → **APIs e serviços** → **Biblioteca**. Pesquise uma por vez e clique **Ativar** (se já ativa, não mudar):
   - **Cloud Run Admin API** (`run.googleapis.com`);
   - **Cloud Build API** (`cloudbuild.googleapis.com`);
   - **Artifact Registry API** (`artifactregistry.googleapis.com`);
   - **Identity-Aware Proxy API** (`iap.googleapis.com`).
   Confirme também que **BigQuery API** está ativa; não crie nem altere tabelas.
3. Menu ☰ → **Faturamento** → selecione a conta vinculada ao projeto → **Orçamentos e alertas** → **Criar orçamento** → nome `NIVON M1 R$ 10`, escopo somente `nivon-data`, valor **R$ 10/mês** se a moeda da conta for BRL (se não for BRL, configurar equivalente na moeda exibida e registrar a conversão). Alertas por e-mail em 50%, 90% e 100% para administradores de faturamento. **Orçamento não impede gastos automaticamente**: acompanhar manualmente.
4. Menu ☰ → **Artifact Registry** → **Repositórios** → **Criar repositório**. Nome exato `nivon-terminal-docker`, formato **Docker**, modo **Padrão**, região `southamerica-east1` → **Criar**. Copie `nivon-terminal-docker` para o GitHub.

## 2 — Contas de serviço e permissões mínimas

5. Menu ☰ → **IAM e administrador** → **Contas de serviço** → **Criar conta de serviço**. ID `nivon-terminal-exec`, nome `NIVON Terminal Execucao ANTT` → **Criar e continuar** → concluir **sem criar chave JSON**. E-mail final exato: `nivon-terminal-exec@nivon-data.iam.gserviceaccount.com`.
6. Menu ☰ → **BigQuery** → **Explorer** → projeto `nivon-data` → dataset `nivon_raw` → **Compartilhar/Permissões** → **Adicionar principal** `nivon-terminal-exec@nivon-data.iam.gserviceaccount.com`, papel **BigQuery Data Viewer** (`roles/bigquery.dataViewer`), **somente no dataset**. No IAM do **projeto**, conceda à mesma conta **BigQuery Job User** (`roles/bigquery.jobUser`) para executar consultas de leitura. Verifique a VIEW `nivon_raw.vw_antt_ferrovia_od_atual`. Se a VIEW usar dataset distinto, verificar autorização da view sem ampliar indiscriminadamente o acesso.
7. GitHub → repositório **NIVON** → **Settings → Secrets and variables → Actions → Variables**: consulte o valor **já existente** de `NIVON_GCP_SERVICE_ACCOUNT`. Ele identifica a conta federada WIF de **deploy** (diferente da conta de execução). **Não criar outra integração WIF nem trocar a conta existente** sem necessidade.
8. Menu ☰ → **IAM** (projeto `nivon-data`) → **Conceder acesso** à conta apontada por `NIVON_GCP_SERVICE_ACCOUNT`: **Cloud Run Admin** (`roles/run.admin`, necessário para `--iap`) e **Cloud Build Editor** (`roles/cloudbuild.builds.editor`) no projeto. Abra **Artifact Registry → repositório nivon-terminal-docker → Permissões** e conceda a essa conta **Artifact Registry Writer** (`roles/artifactregistry.writer`) **somente no repositório**. Abra **Contas de serviço → nivon-terminal-exec → Permissões** e conceda à conta WIF **Service Account User** (`roles/iam.serviceAccountUser`) **somente sobre esta conta de execução**. Verifique se a identidade efetiva dos builds do Cloud Build consegue publicar a imagem no repositório; caso falhe, conceda Writer à identidade do build no mesmo repositório, nunca Owner por conveniência. Não conceder `allUsers` nem `allAuthenticatedUsers`.

## 3 — IAP e OAuth: etapa obrigatoriamente manual em projeto sem organização

9. Menu ☰ → **APIs e serviços / Google Auth Platform** → **Branding / Público-alvo** (ou **Tela de consentimento OAuth**). Configure nome `NIVON Terminal Privado`, e-mail de suporte válido, audiência **Externo**, contatos do desenvolvedor e **adicione `brunocapellari@gmail.com` como usuário de teste** enquanto o aplicativo estiver em modo de teste, quando o console pedir. Salve as configurações.
10. Na primeira tentativa de habilitar IAP num projeto **sem organização**, pode ser exigida a configuração inicial pelo **Console**: Cloud Run → **Serviços** → `nivon-terminal` → guia **Segurança** → **Exigir autenticação → Identity-Aware Proxy (IAP)**. Em **Editar política → Configurar no IAP → Configurar tela de consentimento**, escolha **Externo** e **Gerar credenciais automaticamente** (ou cliente OAuth personalizado e seu ID/secret), **Salvar**. A criação do cliente OAuth **não pode ser automatizada pelo gcloud** neste caso. Se o serviço ainda não existir, complete o procedimento após o primeiro deploy; se a primeira execução não conseguir concluir o IAP, corrija no console e execute novamente o workflow manual. **Não escolha acesso público como alternativa.**
11. Cloud Run → `nivon-terminal` → **Segurança**: confirme **IAP habilitado** e **autenticação obrigatória**. Atribua **Cloud Run Invoker** (`roles/run.invoker`) **apenas ao agente de serviço IAP** no serviço (o Console pode fazer isso automaticamente ao ativar IAP): `service-NUMERO_DO_PROJETO@gcp-sa-iap.iam.gserviceaccount.com`. Descubra **NÚMERO_DO_PROJETO** em **Página inicial → Informações do projeto → Número do projeto**; **não é** a ID textual `nivon-data`. Cloud Run → **Permissões** → confirme que **nenhuma** permissão de invocação é dada a `allUsers` ou `allAuthenticatedUsers`.
12. Cloud Run → `nivon-terminal` → **Segurança → IAP → Editar política** → adicionar **somente** `brunocapellari@gmail.com` com papel **IAP-secured Web App User** (`roles/iap.httpsResourceAccessor`) **no recurso do IAP do serviço**; não no projeto inteiro. A conta de execução NÃO recebe esse papel.

Referência oficial: https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run

## 4 — GitHub: variáveis, proteção, PR e publicação

13. GitHub → **brunocapellari-dotcom/NIVON → Settings → Secrets and variables → Actions → Variables → New repository variable**. Criar/preencher os **quatro valores exatos**:
    - `NIVON_TERMINAL_ARTIFACT_REPO` = `nivon-terminal-docker`
    - `NIVON_TERMINAL_EXECUTION_SA` = `nivon-terminal-exec@nivon-data.iam.gserviceaccount.com`
    - `NIVON_GCP_COST_REVIEWED` = `true` **somente após revisão pessoal de custos** (não foi definido por esta PR)
    - `NIVON_GO_LIVE_DEPLOY_APPROVED` = `true` **somente após aprovação pessoal de implantação** (não foi definido por esta PR)
    Confirme sem alterar que `NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`, `NIVON_BQ_PROJECT=nivon-data` e `NIVON_BQ_DATASET=nivon_raw` já existem/correspondem.
14. GitHub → **Settings → Branches** (ou Rules → Rulesets) → **Add branch protection rule** para `main`: exigir **pull request**, pelo menos um review quando aplicável, checks verdes **NIVON - Terminal privado Go Live / testes-e2e** e **NIVON - Terminal privado Go Live / testes-conteiner**; impedir push direto e force-push. **Habilite depois de confirmar os nomes de checks efetivamente publicados na PR.**
15. Revise a PR consolidada; faça **merge manual** somente se CI verde. Esta PR **não realiza merge**.
16. GitHub → **Actions → NIVON - Terminal privado Go Live → Run workflow** → selecione branch **main**, marque `confirmar_deploy=true` → **Run workflow**. A execução só publicará se as **duas variáveis de aprovação** estiverem em `true`. Depois, examine os jobs `testes-e2e`, `testes-conteiner`, `publicar-privado` e o resumo; nenhuma conclusão em `skipped` prova implantação.
17. Se aparecer **ACEITE_IAP_PENDENTE_CONFIGURACAO_MANUAL**, vá ao **Console Cloud Run → Segurança/IAP e Permissões**, configure OAuth, agente IAP `roles/run.invoker` e acesso IAP de Bruno; então repita **Run workflow** se necessário. Não dê invocação pública. Confirme pelo Console que a revisão está Ready e que `Iap Enabled: true`.

## 5 — Aceite REAL no celular

18. Cloud Run → `nivon-terminal` → copie a **URL HTTPS real** `https://...run.app` (não adivinhar URL). Abra no navegador **do celular**, preferencialmente em aba anônima para testar fluxo: deve abrir a tela de login Google/IAP, entrar com **`brunocapellari@gmail.com`** e mostrar o NIVON com dados da ferrovia, nunca valores fabricados.
19. Após login, na mesma sessão abra `URL/healthz` → JSON **`{"estado":"PROCESSO_ATIVO"}`**; `URL/api/v1/ferrovia` → HTTP 200 JSON, **`estado=ANTT_SERIE_OBSERVADA_DECLARADA`**, `natureza=OBSERVADO_DECLARADO`, fonte **ANTT/SIADE**, série 2006–ano atual, competência real e dados numéricos. `/healthz` isolado **não comprova** BigQuery.
20. Sem a sessão/identidade: uma requisição direta de API não pode retornar 200; verifique 401/403 com cliente HTTP sem cookie, aceitando que **navegador** pode receber **redirecionamento 302 à tela de login**, que é diferente de acesso público. Nunca declare que 302 é erro de exposição sem conferir o destino. Confirme no Console **IAP ativo**, agente IAP invoker correto e **zero `allUsers`/ `allAuthenticatedUsers`**. Registre URL real, status IAM/IAP, competência, commit, horário e resultado do celular na issue #281.

**Observação técnica:** o aceite offline compara revisão, imagem do commit, IAM/IAP, HTTP 403 e dados ANTT; não equivale a uma prova online enquanto os artefatos reais não forem coletados. O script pós-deploy faz apenas a checagem IAM/IAP, sem conceder papéis nem configurar OAuth. **M1 somente ANTT; PTAX, marítimo, GCS e novos painéis ficam fora do gate.**
