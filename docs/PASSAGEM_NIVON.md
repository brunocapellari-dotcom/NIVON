# NIVON — Passagem de bastão

**Para quem assume a execução do projeto.** Este documento é a referência do que o Bruno (dono) quer no NIVON, do estado real em 23/11/2026 e de por onde começar. Em caso de dúvida, vale o que está aqui e o código na `main`; documentos datados antigos em `docs/` são histórico.

---

## 1. O que é o NIVON

Plataforma **privada** de inteligência de mercado, indústria e logística do agronegócio e de granéis do Brasil, com foco inicial em **Mato Grosso**. Ela coleta dados oficiais (preços, câmbio, safra, transporte ferroviário, rodoviário, hidroviário e portos), guarda tudo com proveniência no Google Cloud e mostra ao Bruno, **no celular**, o estado atualizado com data de referência e frescor de cada fonte. Depois do primeiro funcionamento, entram tendências e análises.

## 2. Primeira meta: "funcionando" (nada além disso até concluir)

1. **Coletor `nivon-coletor`** (Cloud Run Job + Cloud Scheduler) rodando **sozinho, sem ninguém disparar**, com 4 fontes: **PTAX (BCB), ANTT ferroviário, CONAB e PortWatch/marítimo**.
2. Cada coleta grava o **bruto com hash**, carrega o **BigQuery de forma idempotente** e atualiza **`nivon_core.saude_fontes`**.
3. **Terminal privado com IAP** abrindo no celular do Bruno, mostrando essas 4 fontes com **data de referência e frescor**.
4. **Sete dias seguidos** de coleta sem intervenção manual.

Ordem de prioridade: (1) coletor em produção → (2) terminal com IAP → (3) todo o resto (documentação final, limpeza, Ruff, núcleo `nucleo/`, novas fontes). O item 3 não pode atrasar os itens 1 e 2.

## 3. Regras que não mudam

**Infraestrutura**
- **Só Google Cloud.** Projeto `nivon-data`, região `southamerica-east1`. **Nada de Vercel.** O Neon (Postgres) está sendo substituído; não desligar sem reconciliação aprovada.
- **BigQuery é a fonte única de verdade analítica.** GitHub guarda código, SQL, testes e documentação. GCS guarda o bruto.
- **Custo-alvo perto de R$ 0** (cotas gratuitas). Nada pago, nenhum aumento de cota e nenhum serviço novo sem o Bruno aprovar. Existe alerta de orçamento.
- **Tudo privado.** Nunca `allUsers` ou `allAuthenticatedUsers`. O terminal é acessível só por identidades autorizadas (IAP / `run.invoker`).
- **Sem chave JSON de conta de serviço.** GitHub → GCP só via **WIF/OIDC**. Menor privilégio: sem Owner/Editor.
- **Nunca** credenciais, tokens ou dados restritos no repositório (ele é público), em logs, issues ou PRs.

**Dados**
- **OBSERVADO, INFORMADO, ESTIMADO, INFERIDO e PROJETADO nunca se misturam** e sempre aparecem rotulados.
- **Ausência é ausência, não zero.** Nada de dado inventado ou sintético apresentado como real.
- Preservar **data de referência, publicação, coleta, competência e vintage**. Execução do coletor **não é** frescor do dado.
- **CEPEA não informa data de publicação.** A data de coleta vale como disponibilidade conservadora, e **nunca** como data de publicação.
- Respeitar os direitos de uso de CEPEA, IMEA, CONAB etc. Direito desconhecido significa bloqueado por padrão.
- Line-up programado não é realizado. Volume amostral (ANTT/MDF-e por NCM) não é total observado. PortWatch é estimado, não carga real.

**Trabalho**
- **Reaproveitar e mover, não reescrever** código que funciona. O coletor não espera o `nucleo/` ficar pronto.
- **PRs pequenas**, revisáveis em minutos, com testes e CI verde.
- **Merge, deploy, IAM, custo e variáveis `*_APPROVED` são decisões do Bruno.**
- Teste aprovado não é implantação concluída. Só declarar "funcionando" com evidência real (Cloud Run, BigQuery, URL).
- Cada relatório termina com **"dias estimados até funcionar"** e **"o que está bloqueando agora"**.

## 4. Onde as coisas estão (código na `main`, commit `6d802f2`)

| Peça | Arquivo(s) |
|---|---|
| Orquestrador do coletor (Cloud Run Job) | `src/nivon/carga/coletor.py` |
| Registro das 4 fontes (reaproveita os pipelines existentes) | `src/nivon/carga/registro_fontes.py` |
| Imagem do coletor | `infra/google_cloud/Dockerfile.coletor`, `cloudbuild.coletor.yaml` |
| Preparação única do GCP (APIs, repositório Docker, SA, permissões, datasets, tabelas) | `scripts/preparar_coletor_gcp.sh` |
| Deploy do Job + Scheduler (3x/dia: 11:15, 17:15 e 23:15 UTC) | `scripts/deploy_coletor_job.sh` |
| Tabela de saúde | `database/bigquery/nivon_saude_fontes.sql` → `nivon_core.saude_fontes` |
| Terminal privado (ferrovia ANTT, `/healthz`, `/api/v1/ferrovia`) | `src/nivon/terminal_web.py`, `infra/google_cloud/Dockerfile.terminal` |
| Monitor das rotinas do GitHub Actions | `src/nivon/monitor_p0_workflows.py` |
| Testes | `tests/` (≈ 895, rodam offline: `python -m compileall -q src tests scripts && PYTHONPATH=src python -m unittest discover -s tests -q`) |

**Recursos GCP:** datasets `nivon_raw` (ANTT, CONAB staging, marítimo) e `nivon_core` (`ptax_quotes`, `saude_fontes`); bucket `nivon-data-raw-2026`; SA de execução `nivon-coletor-de-dados@nivon-data.iam.gserviceaccount.com`; repositório Docker `nivon`. O GitHub usa as variáveis `NIVON_GCP_PROVIDER` e `NIVON_GCP_SERVICE_ACCOUNT` (WIF).

**Regras do coletor:** cada fonte só roda se estiver vencida (PTAX e marítimo 6 h, CONAB 24 h, ANTT 7 dias, com folga de 30 min). Uma fonte com falha não bloqueia as outras. Sem `NIVON_COLETOR_HABILITADO=true`, ou fora do projeto `nivon-data`, nada executa (fail-closed).

## 5. Estado real em 23/11/2026

**Rodando sozinho no GitHub Actions** (verificado): marítimo (GCS + BigQuery, 6 h), PTAX direta para o BigQuery, ANTT ferrovia para o GCP, CEPEA e IMEA para o Neon e vigias ANTAQ/ANTT. Os crons do GitHub atrasam e às vezes são descartados neste repositório; por isso o alvo é o Cloud Scheduler.

**Com falha recorrente:** CONAB → Neon, ponte privada PTAX → GCP e "P0 — Saúde real das fontes". Investigar depois do coletor; não bloqueiam a primeira meta.

**Coletor `nivon-coletor`:** o job existe no Cloud Run. A última execução conhecida falhou na CONAB (pasta privada), problema corrigido na `main` pela #339. **Ainda não há evidência de uma execução com as 4 fontes em OK.** Esse é o próximo marco.

**PRs abertas:**

| PR | O que é | Situação |
|---|---|---|
| #340 | `pypdf` 6.21.4 (segurança) | Revisada e aprovada; mesclar **antes** da #336 |
| #341 | Remove Vercel e interfaces públicas antigas | Revisada e aprovada |
| #337 | Governança e documentação (F1) | Revisada e aprovada |
| #336 | CI único + script de IAM para deploy pelo GitHub (F5) | **2 ajustes**: `roles/bigquery.jobUser` para a conta WIF; no bucket `nivon-data_cloudbuild`, `storage.objectAdmin` + `storage.legacyBucketReader` no lugar de `objectCreator`. Depois, trazer a `main` e aceitar o `pypdf` 6.21.4 |
| #343 | Deploy do coletor via GitHub Actions (WIF, ambiente `producao`) | **1 ajuste**: `--suppress-logs` no `gcloud builds submit` de `deploy_coletor_job.sh` |
| #324 | Terminal privado com IAP (M1) | Aberta desde 26/10; base para a F3 |
| #335, #246 | Catálogo de fontes; controles de auditoria | Rascunhos, fora do caminho crítico |

Os pareceres detalhados estão nos comentários de cada PR.

## 6. Próximos passos, em ordem

1. **Coletor rodando com as 4 fontes em OK.** No Cloud Shell do `nivon-data`: `git pull`, `bash scripts/preparar_coletor_gcp.sh`, depois o comando de deploy que ele imprime e, por fim, `gcloud run jobs execute nivon-coletor --region=southamerica-east1 --wait`. Conferir `nivon_core.saude_fontes`; se alguma fonte aparecer em `FALHA`, a coluna `etapa_falha` diz qual módulo corrigir. Lacuna conhecida: a PTAX não preserva o bruto OData byte a byte.
2. **Mesclar #340 → #341 → #337.**
3. **Ajustar a #336**, mesclar e rodar uma vez `scripts/conceder_deploy_github.sh` (IAM mínimo para o deploy via WIF). Criar o ambiente `producao` no GitHub.
4. **Ajustar a #343** e mesclar. A partir daí, o deploy e a execução do coletor podem ser feitos pelo GitHub Actions, sem depender do Cloud Shell.
5. **Terminal (F3):** ler `nivon_core.saude_fontes` e as datas de referência de cada fonte (`ptax_quotes.reference_date`, a view ferroviária, `nivon_raw.agro_fonte_stage`, as tabelas marítimas) e mostrar no celular status, última execução OK, data de referência e frescor, separados. Em seguida, deploy no Cloud Run com IAP e acesso só do Bruno.
6. **Sete dias seguidos** sem intervenção, comprovados pela `saude_fontes`.
7. Só depois disso: lock de dependências com hash e Ruff (F2), núcleo `nucleo/` (PR 0 da F2), novas fontes, tendências e análises.

**Estimativa:** coletor estável em 1–2 dias de trabalho, terminal no celular em 3–5 dias, e mais 7 dias de observação.

## 7. O que é decisão do Bruno

Merge na `main`; deploy; qualquer concessão de IAM; custos, orçamento e cotas; variáveis `*_APPROVED`; acesso ao terminal; licença e direitos de uso de fontes; apagar branches (há ~315 sem PR; arquivar em tags `arquivo/<nome>` antes de apagar).
