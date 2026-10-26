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
