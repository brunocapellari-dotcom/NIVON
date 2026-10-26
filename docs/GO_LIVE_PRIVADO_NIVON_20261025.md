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

## Gate automático de aceite privado após implantação (25/10/2026)

**Código:** `src/nivon/validar_terminal_go_live.py`. Esta rotina não efetua deploy, build, IAM, SQL livre ou escrita em Google Cloud. Seu modo padrão apenas mostra o plano, sem acessar rede e sem gastar recursos. Foi integrada ao workflow existente `.github/workflows/nivon-terminal-go-live.yml` somente na suíte offline de PR.

**Prévia segura, sem rede:**

```bash
PYTHONPATH=src python -m nivon.validar_terminal_go_live --url https://URL-DO-SERVICO.a.run.app
```

**Aceite REAL apenas depois de** aprovar custos, implantar o Cloud Run privado e atribuir `roles/run.invoker` à identidade de teste. Obter um ID token de curta validade por fluxo Google Cloud autorizado, compatível com a audiência (URL) do serviço, e fornecê-lo via variável de ambiente `NIVON_TERMINAL_ID_TOKEN`. Nunca gravar o token em arquivos, comandos versionados, logs de CI ou links. Executar manualmente:

```bash
PYTHONPATH=src python -m nivon.validar_terminal_go_live --url https://URL-DO-SERVICO.a.run.app --executar
```

O teste verifica nesta ordem: (1) requisição sem token recebe 401/403, nunca 200; (2) `/healthz` com token recebe `PROCESSO_ATIVO`; (3) `/api/v1/ferrovia` retorna JSON privado, `no-store`, série anual contínua a partir de 2006, proveniência, competência não futura, somatórios coerentes e estados metodológicos que proíbem homologação editorial ou soma multimodal.

**Importante:** URL deve ser raiz HTTPS oficial `*.run.app` (não domínio arbitrário); redirects e proxies não são seguidos, evitando encaminhamento de identidade. O teste não imprime token nem números de volume da base. Mesmo quando `go_live_interno_validado=true`, isso certifica somente o recorte 0.1 privado ANTT e não o go-live integral do NIVON.

**Bloqueio ainda externo:** a inspeção anterior do runner reportou `CLOUD_RUN_READ_ONLY_STATUS=NO_LIST_PERMISSION_OR_SERVICE` no [CI #40257187154](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257187154). Não interpretar como serviço inexistente com certeza; pode ser falta de permissão. É necessário resolver capacidade de inspecionar/implantar Cloud Run, confirmar repositório Docker e identidade BigQuery readonly, revisar custos e liberar o deploy manual. Nenhuma dessas ações é executada pelo novo smoke.

**Aceite técnico:** CI offline + diagnóstico metadata-only + implantação privada manual aprovada + smoke autenticado real. Sem todos esses sinais, manter status `NAO_GO_LIVE` e não divulgar URL como sistema pronto.
