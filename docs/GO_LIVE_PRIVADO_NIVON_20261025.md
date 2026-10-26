# NIVON — Go-live privado 0.1 (plano operacional verificável)

**Objetivo:** disponibilizar uma interface web real, ligada ao BigQuery, antes da conclusão de todas as fontes e motores. O serviço inicia com a série ferroviária ANTT/SIADE 2006–competência atual, agregações anuais e proveniência explícita. Fontes restritas, ANTAQ não homologada, previsões shadow e fretes de WhatsApp não são publicados.

## O que está efetivamente construído

- `src/nivon/terminal_web.py`: servidor HTTP somente GET; `/` interface HTML responsiva, `/healthz` indica processo ativo (NÃO atesta fonte), `/api/v1/ferrovia` lê a *view atual* do BigQuery, aplica limites de cobertura, SHA distinto por ano, competência, TU e data de coleta; não fabrica zeros e não expõe erros IAM ou SQL.
- Consulta limitada a **250 MB faturáveis por execução** e cache em memória de 15 minutos por instância; isso não garante operação totalmente gratuita, nem inclui custo de instância/build/rede. `min-instances=0`, `max-instances=1`, IAM privado.
- `infra/google_cloud/Dockerfile.terminal`: imagem não-root; `infra/google_cloud/cloudbuild.terminal.yaml`: build em Artifact Registry existente.
- `scripts/deploy_terminal_privado.sh`: inspeciona projeto, dataset, view, service account, repo e serviço; recusa IAM público, não concede papéis, não habilita APIs, não cria scheduler, não cria service account.
- `.github/workflows/nivon-terminal-go-live.yml`: valida toda PR sem nuvem; **deploy somente por execução manual na main** com gates explícitos.

## Provas de dados já obtidas

- 21 anos no BigQuery: 2006–agosto/2026, 174.850 OD, 9.952.668.869 TU acumuladas. Fonte ANTT/SIADE, quantitativos declarados. Referência: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001461762.
- Mais detalhes de corredores MT: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001966549.
- Não se trata de peso multimodal único nem de todo o agronegócio; 2026 é parcial e a ANTT pode publicar revisões.

## O que falta para o serviço estar acessível

1. O GitHub deve ter `NIVON_BQ_PROJECT=nivon-data`, `NIVON_BQ_DATASET=nivon_raw` e variáveis WIF já utilizadas por outras rotinas.
2. Necessários: repositório Docker **existente** em `southamerica-east1` (`NIVON_TERMINAL_ARTIFACT_REPO`) e service account **existente, restrita a BigQuery read-only** (`NIVON_TERMINAL_EXECUTION_SA`) com permissão de consulta da view. O workflow de deploy não cria nem concede esses recursos.
3. Após revisar custos, aprovar `NIVON_GCP_COST_REVIEWED=true` e `NIVON_GO_LIVE_DEPLOY_APPROVED=true`. Não habilitar sem decisão humana; deploy e builds podem consumir recursos faturáveis.
4. Rodar em GitHub Actions o workflow **NIVON - Terminal privado Go Live**, opção `confirmar_deploy=true`. A saída apresenta a URL do serviço, **sem torná-lo público**.
5. Conceder acesso `roles/run.invoker` **somente às identidades autorizadas** pelo administrador do projeto; não liberar para `allUsers` nem `allAuthenticatedUsers`. Pessoas sem identidade autorizada receberão 403 e isso é esperado. Fazer login/teste autorizado na URL privada e observar `/healthz` + `/api/v1/ferrovia`. `/healthz` sem autenticação não deve ser público.
6. Validar resposta real da série, limites de custos e performance no Cloud Run. Somente então classificar **go-live interno restrito** como concluído. O código mesclado e a CI aprovados isoladamente **não são deploy nem go-live**.

## Política de lançamento

**Pode entrar na versão 0.1:** ferrovia ANTT/SIADE e referências ferroviárias auditadas, com competência e ausência de homologação editorial indicada.

**Não entra:** totais ANTAQ de réplica como se fossem oficiais, projeções AIS/ETA não calibradas, negociações inferidas a partir de fretes anunciados, dados privados CEPEA/IMEA sem direito validado de exibição, dados de testes e quaisquer somas entre modais.

**Critério para publicação privada:** CI E2E aprovada; deploy autenticado em Cloud Run; IAM restrito; endpoint real respondendo; retorno com versão/competência/fonte e sem dados fabricados; nenhum custo ou permissão além do aprovado.

**Extensões seguintes após go-live:** preços físicos, CBOT, PTAX, fretes e line-up somente quando as consultas canônicas e as licenças estiverem reconciliadas. O terminal modular aceita novas seções sem redesenhar autenticação.


## Critério de aceite técnico automático após o deploy privado

O procedimento `scripts/deploy_terminal_privado.sh` continua **manual**, acionado exclusivamente por `workflow_dispatch` na `main`, com `confirmar_deploy=true` e as duas autorizações distintas `NIVON_GO_LIVE_DEPLOY_APPROVED=true` e `NIVON_GCP_COST_REVIEWED=true`. Isso pode consumir recursos faturáveis; não supor gratuidade.

Após o deploy, o workflow `.github/workflows/nivon-terminal-go-live.yml` invoca **`scripts/aceitar_terminal_privado.sh`** como segundo gate, sob a mesma sessão WIF explicitamente autorizada:

1. Recupera os metadados do serviço e o IAM efetivo (`gcloud run services describe` e `get-iam-policy`), sem alteração de permissões.
2. Rejeita URL diferente de HTTPS padrão `*.run.app`, recurso de outro projeto, service account externa, revisão não Ready, tráfego diferente de 100% na revisão testada ou imagem cuja tag não corresponda ao commit exato.
3. Confirma que o serviço **não** permite `allUsers` / `allAuthenticatedUsers` em `roles/run.invoker`; uma chamada sem token ao `/healthz` deve resultar em HTTP **401 ou 403**.
4. Emite identity token **apenas em memória** pela identidade WIF autorizada; chama `/healthz` e `/api/v1/ferrovia` com autenticação. Se a conta do job não possuir `roles/run.invoker`, o aceite falha: a permissão mínima deve ser aprovada por administrador, nunca concedida automaticamente pelo workflow.
5. Reconciliam-se anos 2006 até o ano corrente, totais de toneladas e registros, competência mais recente, data de coleta, rótulos de observação e a restrição de **250 MB processados por consulta**. Não basta que `/healthz` esteja ativo ou que HTML abra: o endpoint BigQuery deve funcionar e a resposta não pode conter valores inventados.
6. O resultado resumido marca `GO_LIVE_PRIVADO_01_ACEITE_TECNICO`, informa URL e revisão **privadas**, sem imprimir credenciais nem corpo original da consulta. Nenhum dado CEPEA/IMEA, AIS inferido, frete anunciado ou meteorologia shadow é promovido.
7. A prova atesta um **aceite técnico no instante do teste**, não estabilidade contínua, custo zero, direitos de fontes futuras ou acesso concedido automaticamente a outros usuários.

O teste de aceitação não roda em `push` ou PR, não faz BigQuery read real durante CI offline e **não** dispensa o gate de custo. O Cloud Run pode ter sido criado antes de um smoke falhar; um deploy concluído **sem aceite** não é anunciado como go-live.

### Recuperação/rollback

`scripts/rollback_terminal_privado.sh` é preparado para execução humana somente na `main`. Requer:
`NIVON_ROLLBACK_APPROVED=true`,
`NIVON_GO_LIVE_DEPLOY_APPROVED=true`,
`NIVON_GCP_COST_REVIEWED=true` e uma
`NIVON_ROLLBACK_TARGET_REVISION` existente e Ready no serviço `nivon-terminal`.

A operação altera **somente o tráfego** para uma revisão previamente aprovada por `gcloud run services update-traffic --to-revisions=REVISAO=100`. Não muda IAM nem elimina a revisão defeituosa automaticamente. A mudança exige credenciais/IAM autorizados, custos revisados e verificação autenticada posterior. Não executar rollback sem revisão-alvo comprovada.

### Decisão arquitetural para go-live 0.1

**Único runtime web implantado:** `nivon.terminal_web` no Cloud Run `nivon-terminal`, iniciado com ANTT/SIADE. O `portal_interno.py` já presente na `main` continua como consumidor/gerador de snapshot privado em evolução, **não** como segundo servidor exposto no primeiro deploy. Isso evita duplicar autenticação, service account, endpoint, custos e monitoramento.

**Ponto exato ainda pendente:** não há evidência nesta PR de URL Cloud Run implantada e acessível, nem de IAM runtime efetivo ou do custo real de build/consulta. O operador responsável deve revisar recursos/custos/identidades existentes e fazer o dispatch aprovado. Sem essas evidências, o estado correto é **CANDIDATA_DE_GO_LIVE**, nunca `LIVE`.
