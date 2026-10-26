# NIVON — Lançamento interno controlado, sem depender da stack marítima em draft

**Referência:** 25/10/2026. **PR:** #310. **Objetivo:** colocar rapidamente em uso a menor versão real do NIVON, sem publicar dados de terceiros nem misturar informação programada com operação realizada.

## Decisão de escopo

| Ordem | Produto | Base existente na main | Estado do release |
|---|---|---|---|
| 1 | Painel interno SHADOW | `painel_lancamento.py`, `publicar_painel_interno.py`, `nivon-go-live-interno.yml` | Código de consulta e renderização pronto; **primeira publicação autenticada deve ser comprovada nos logs GCP** |
| 2 | Terminal web privado ANTT | `terminal_web.py`, `deploy_terminal_privado.sh`, `nivon-terminal-go-live.yml` | Testes e bloqueios de custo/IAM passam; **Cloud Run não foi implantado por esta PR** |
| 3 | Ingestão marítima piloto Imbituba/PortWatch | `maritimo_gcp_job.py` + workflow de seis horas | Habilitar/agendar **somente** quando coleta, direitos e quotas estiverem aprovados; dados de PortWatch são **estimativas** |
| 4 | Line-ups PDF, Nº Prog–DUV, AIS e predição | PRs draft da stack marítima, fora da main | **Não entram no primeiro go-live**; sem comprovação de direitos/DUV, sem publicar escalas físicas |

O piloto é de **uso privado**, sem dependências de Vercel ou Neon. Aproveita BigQuery e GCS já previstos no projeto `nivon-data`. O status de plataforma inteira em produção continua **NÃO COMPROVADO** até evidência autenticada de runtime.

## Entrega A — primeira edição do painel privado GCS

Fluxo já implementado: consulta BigQuery *read-only* da ferrovia ANTT/SIADE (recorte de competência fixada), programação histórica Imbituba e PortWatch Panamá → HTML gerencial e JSON → gravar dois objetos imutáveis no bucket privado GCS, com SHA-256 e readback. Não cria bucket, IAM, tabela ou URL pública.

Pré-condições que **um responsável precisa verificar** no GitHub Actions e no Google Cloud:

- Ambiente exato: `NIVON_BQ_PROJECT=nivon-data`, `NIVON_BQ_DATASET=nivon_raw`, `NIVON_GCS_BUCKET=nivon-data-raw-2026`.
- Provider WIF/OIDC e service account já existentes: `NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`.
- Autorização **afirmativa** para qualquer operação que possa consumir cota: `NIVON_GCP_COST_REVIEWED=true`.
- Autorização separada para gravar o relatório privado: `NIVON_PAINEL_INTERNO_WRITE_APPROVED=true`.
- Bucket deve comprovar Public Access Prevention `enforced` e ser compatível com o IAM do principal; o contrato de dados rejeita inferir navios concluídos e tonelagem realizada.

**Após consentimento explícito e aprovação de custos**, na branch `main` execute o workflow **“NIVON - Painel Operacional Interno Diario”** com `workflow_dispatch` e `publicar=true`. Conferir logs e o sumário por `PUBLICADO_REVISAO_PRIVADA_GCS`, hash SHA-256, duas versões de objeto e `latest_atualizado=false`. A publicação é privada e exige acesso GCS autorizado; não afirmar que uma URL acessível foi publicada. O agendamento periódico permanece desabilitado até `NIVON_PAINEL_INTERNO_AGENDADO=true`, com revisão de custo.

## Entrega B — terminal web autenticado

Workflow existente **“NIVON - Terminal privado Go Live”**; deploy somente em `main`, manual, com `confirmar_deploy=true`, `NIVON_GO_LIVE_DEPLOY_APPROVED=true` e `NIVON_GCP_COST_REVIEWED=true`. Exige configuração `NIVON_TERMINAL_ARTIFACT_REPO` e `NIVON_TERMINAL_EXECUTION_SA` **existentes** e acesso do operador. Cloud Run configurado para `--no-allow-unauthenticated`, min-instances=0, max-instances=1. Não amplia papéis IAM, não abre uma URL pública, não cria service account.

**Preflight mínimo:** existência real do repositório Docker, service account, APIs Cloud Run/Build/Artifact Registry e view `nivon_raw.vw_antt_ferrovia_od_atual` — o comando estático **não confirma** esses recursos. Primeiro deploy e testes HTTP IAM devem ser verificados antes de compartilhar acesso com os usuários internos.

## Entrega C — marítimo recorrente

O workflow `maritimo-gcp-primeiro-lote.yml` passou a exigir `NIVON_MARITIMO_GITHUB_SCHEDULE=enabled`, `NIVON_ZERO_COST_BQ_APPROVED=true` e `NIVON_RAW_ARCHIVE_APPROVED=true` para executar no cron, além de `main`. A implementação não prova, por si só, a existência de direitos ou de linha de dados nova; homologar fontes, limites de coleta, deduplicação e GCS/BigQuery antes de habilitar. Não executar outro cron em Cloud Scheduler em paralelo.

## Comando único de preparação sem gastar cota

```bash
python scripts/nivon_release_readiness.py --strict-policy
```

Retorna JSON com `arquivos_presentes`, `politicas`, `configuracao` (**booleanos apenas**, sem valores de segredos), `trilhas`, `violacoes_de_politica`. O comando **não usa rede, não autentica, não consulta BigQuery nem faz deploy**. As flags de configuração validadas neste teste não são evidência de permissões GCP reais; em CI de PR, variáveis podem estar ausentes por desenho de segurança. Nenhum sinal de sucesso offline implica go-live efetivamente publicado.

## Critérios objetivos de aceite

1. Repositório `main` com alterações revisadas e CI verde, sem merge automático da grande stack divergente.
2. Operador confirma ausência de custos imprevistos e validade das licenças de cada fonte; preços, fretes, cadastros e dados sensíveis ficam fora do piloto.
3. Workflow autenticado apresenta evidência de consulta BigQuery válida, data/hora do corte, frescor/defasagem e publicação privada GCS verificada por readback.
4. Terminal Cloud Run só é anunciado como disponível após deployment manual, URL privada testada sob IAM, respostas reais do endpoint e rollback documentado.
5. Go/no-go formal: **GO_INTERNO_SHADOW** apenas para o conjunto comprovado; demais módulos **BLOQUEADOS**, sem confundir demo com produto operacional completo.

**Dependência externa inevitável:** autorização explícita para operar sobre serviços medidos Google Cloud (inclusive quando se pretende ficar na camada gratuita), permissões WIF/IAM adequadas e aprovação de cada fonte. Nenhum serviço foi ativado ou alterado por esta PR.
