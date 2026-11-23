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

## 2A. Visão completa (tudo o que o NIVON deve cobrir depois da primeira meta)

Levantado de 32 issues, 135 PRs (128 arquivadas na issue #342, com o código preservado no histórico de cada PR), ~120 módulos em `src/nivon/` e do catálogo `config/catalogo_integracoes_github_20261026.json`. A coluna "Estado" diz o que existe **hoje** na `main`.

### Domínios e fontes

| Domínio | Fontes / conteúdo | Estado | Onde procurar |
|---|---|---|---|
| **Câmbio** | PTAX USD/EUR (BCB), SGS (série 11 e outras), expectativas de mercado | PTAX direta → BigQuery rodando; SGS11 com gate fechado | `scripts/ptax_bcb_bigquery_direto.py`, `sgs11_gcp.py`, issue #59 |
| **Preços físicos** | CEPEA (soja Paranaguá/Paraná, milho), IMEA (cadeias MT), preço atacado | Coletores reais funcionam; CEPEA/IMEA → Neon rodando; para GCP com gate fechado; CEPEA no painel com coleta como disponibilidade | `cepea_web_primario.py`, `imea_publico.py`, `agro_origem_gcp.py`, issues #94, #145, #292 |
| **Safra e oferta** | CONAB (levantamentos, progresso semanal, séries históricas MT 2010–2025, balanço), IBGE PAM/LSPA, USDA (oferta e demanda global), WDI | CONAB real em quarentena + GCS/BigQuery pelo coletor; PAM/WDI com prova E2E; IBGE setoriais via agrobr testados | `conab_*.py`, `coletores_agro_ibge_wdi.py`, `agrobr_setoriais.py`, issues #94, #131, PRs arquivadas #16, #34, #58, #115 |
| **Pecuária** | IBGE PPM, abate trimestral, leite industrial; motores por cadeia | Coletores agrobr na `main` (sem execução recorrente); motores na PR #22 arquivada | `agrobr_setoriais.py`, PR #22 |
| **Mercados futuros e fluxos** | CBOT, CFTC (posição de fundos), ComexStat (exportação/importação), ANEC (embarques, com direitos pendentes) | ComexStat/CFTC via agrobr na `main`; CBOT no motor de tendências (PR #12 arquivada) | `agrobr_mercados.py`, `cftc`, PR #12 |
| **Transporte ferroviário** | ANTT/SIADE 2006–2026 (OD, TU, corredores MT), revisões | **No BigQuery** (21 anos), view atual, vigia de revisões rodando | `antt_*.py`, `corredores_bigquery.py`, issue #143 |
| **Transporte rodoviário** | ANTT RGI (anuário, top fluxos), MDF-e OD (amostral) | Anuário RGI extraído (Tabela 12); MDF-e só monitor de catálogo, pendente arquivo oficial | `antt_anuario_rgi.py`, `antt_mdfe_*.py`, issue #142 |
| **Transporte hidroviário** | ANTAQ (toneladas por hidrovia e produto), painel Aquarela | Vigia rodando; extração oficial pendente; réplica secundária só como referência | `antaq_*.py`, issue #144 |
| **Comparação multimodal** | Rodovia × ferrovia × hidrovia 2025, corredores intermodais | Painel trimodal 2025 em somente leitura | `painel_trimodal_2025.py`, `corredores_multimodais_2025.py` |
| **Marítimo e portos** | Line-ups (Imbituba, Suape, Santarém, Vila do Conde), PortWatch (Ormuz, Bab-el-Mandeb, Suez, Panamá), AIS/geocercas, DUV/Nº Prog, filas e ETA | Imbituba + PortWatch → GCS/BigQuery rodando (6 h); AIS/geocercas em replay; line-up multi-porto e conciliação CDP/AIS pendentes | `maritimo_*.py`, `maritime/`, `lineup_portos.py`, issues #278, #293 |
| **Fretes** | Fretes anunciados (inclusive WhatsApp) por estabelecimento, transportadora, condições e unidade; tendência sem viés de composição; avaliação 7/30/90 dias | Motores e ledger em PRs arquivadas (#18, #82, #91, #123, #151); P0 aberto contra tendência agregada por município | issue #25, PRs #12, #18, #30, #42 |
| **Combustível** | ANP diesel (revenda), ANP PPI | PPI integrado; diesel via agrobr; fonte oficial de revenda a confirmar | `anp_ppi.py`, issue #295 |
| **Meteorologia e hidrologia** | INMET (BDMEP, horário), CPTEC, CEMADEN, ANA (vazão), NOAA RONI/ENSO, MJO/RMM, NASA POWER | Conectores na `main`; pipelines completos em PRs arquivadas (#11, #19, #46, #129, #191) | `inmet_*.py`, `ana_hidrowebservice.py`, `hidromet_*.py`, issue #279 |
| **Argentina** | MAGyP (séries 1969–2025), BCRA, granos | Coleta real no ledger e prova GCS na `main` | `argentina_magyp.py`, `coletor_bcra_v4.py`, `coletor_granos_ar.py`, issue #280 |
| **Agro/ambiental (catálogo a priorizar)** | 35 bases agrobr: crédito e seguro rural, custo de produção, defensivos, cultivares, desmatamento, queimadas, uso do solo, ZARC, CAR, censo agro, açúcar e etanol, entre outras | Só catalogado | `config/catalogo_integracoes_github_20261026.json` |
| **Núcleo v0.1** | Consumo, indústria, fluxos e contratos portuários | PR #1 arquivada; reorganização planejada em `nucleo/` (PR 0 da F2, adiada) | PR #1 |

### Produtos que o Bruno quer receber

| Produto | Estado |
|---|---|
| **Terminal privado no celular** (fontes, frescor, ferrovia, mercado) | Base existe (`terminal_web.py`, PR #324 com IAP); falta saúde/frescor, deploy e IAP |
| **Painel operacional interno** (logística, marítimo, quantitativo) | `painel_operacional.py` + workflow diário rodando; issue #300 |
| **Motores de tendência e análise** (preços físicos, CBOT, fretes; backtest point-in-time; sem previsão apresentada como fato) | `motor_tendencias.py`, `dinamica_*.py` na `main`; issue #299; PRs #12, #20, #21 |
| **Resumo diário de 1 página e mapas semanais CONAB/IMEA** (editorial) | PRs #26, #45, #49 arquivadas |
| **Radar 24h e briefing** (incluindo envio por WhatsApp com consentimento e outbox) | PRs #8, #40, #95, #110 arquivadas; **nada em produção** |
| **IVO** (relatório PAM, histórico incremental, inteligência agrícola) | PRs #7, #24, #50, #78 arquivadas; issue #131 (direitos e vintages antes de promover) |
| **Identidade visual NIVON** | PR #48 arquivada (v0.3) |
| **Camada de IA opcional** (P0–P2) | Na `main`, opt-in (`integracoes_ia/`) |

**Como usar esta lista:** as PRs arquivadas não estão perdidas. O código continua acessível em cada PR (links na issue #342). Para retomar um produto, reaproveite a PR correspondente sobre a `main` atual, em PR pequena, **depois** da primeira meta.

## 2B. Perguntas que só o Bruno pode responder

O repositório não responde a estas perguntas. Combine com o Bruno antes de avançar além da primeira meta.

1. **Ordem dos produtos depois do terminal:** resumo diário? Radar 24h? tendências de fretes? IVO?
2. **WhatsApp:** os fretes e o briefing ainda passam por WhatsApp? Qual número ou conta, e com que consentimento dos participantes?
3. **Fretes:** de onde vêm hoje (grupos, transportadoras, planilhas)? Quem fornece, e com que direito de uso?
4. **Usuários:** só o Bruno, ou também a esposa, a equipe ou clientes? Isso define o IAP e se o NIVON será um produto vendido.
5. **Direitos de CEPEA, IMEA, ANEC e futuros:** existe assinatura ou licença? Sem isso, esses dados ficam fora do que é exibido.
6. **Portos e praças prioritários:** além de Imbituba e das praças de MT, quais acompanhar primeiro?
7. **Neon:** qual a data para desligar, depois da reconciliação com o BigQuery?
8. **Orçamento mensal máximo** aceito no Google Cloud.
9. **Quem aprova merges** e o que o responsável pela execução pode fazer sozinho.

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

**Repositório:** 319 branches antigas, sem PR aberta, aguardam arquivamento. Rodar uma vez, num clone com permissão de push: `bash scripts/arquivar_branches.sh` (simulação) e depois `bash scripts/arquivar_branches.sh --executar`. O script cria uma tag `arquivo/<nome>` para cada branch, confere que as tags existem no GitHub e só então apaga as branches. Recuperar uma: `git fetch origin tag arquivo/<nome> && git switch -c <nome> arquivo/<nome>`.

**Coletor `nivon-coletor`:** o job existe no Cloud Run. A última execução conhecida falhou na CONAB (pasta privada), problema corrigido na `main` pela #339. **Ainda não há evidência de uma execução com as 4 fontes em OK.** Esse é o próximo marco.

**Já mescladas em 23/11:** #340 (`pypdf` 6.21.4), #341 (Vercel e interfaces públicas removidas), #337 (governança; documentos datados movidos para `docs/historico/`) e esta passagem.

**PRs abertas:**

| PR | O que é | Situação |
|---|---|---|
| #336 | CI único + script de IAM para deploy pelo GitHub (F5) | Ajustes aplicados em 23/11 (`bigquery.jobUser` para a conta WIF; `objectAdmin` + `legacyBucketReader` no bucket de build; `pypdf` 6.21.4). CI verde. **Pronta para merge**; depois rodar `scripts/conceder_deploy_github.sh` uma vez no Cloud Shell |
| #343 | Deploy do coletor via GitHub Actions (WIF, ambiente `producao`) | Ajuste `--suppress-logs` aplicado em 23/11. CI verde. **Pronta para merge, depois da #336** e do script de IAM |
| #324 | Terminal privado com IAP (M1) | Aberta desde 26/10; base para a F3 |
| #335, #246 | Catálogo de fontes; controles de auditoria | Rascunhos, fora do caminho crítico |

Os pareceres detalhados estão nos comentários de cada PR.

## 6. Próximos passos, em ordem

1. **Coletor rodando com as 4 fontes em OK.** No Cloud Shell do `nivon-data`: `git pull`, `bash scripts/preparar_coletor_gcp.sh`, depois o comando de deploy que ele imprime e, por fim, `gcloud run jobs execute nivon-coletor --region=southamerica-east1 --wait`. Conferir `nivon_core.saude_fontes`; se alguma fonte aparecer em `FALHA`, a coluna `etapa_falha` diz qual módulo corrigir. Lacuna conhecida: a PTAX não preserva o bruto OData byte a byte.
2. ~~Mesclar #340 → #341 → #337~~ — feito em 23/11.
3. **Mesclar a #336** (já ajustada) e rodar uma vez `scripts/conceder_deploy_github.sh` (IAM mínimo para o deploy via WIF). Criar o ambiente `producao` no GitHub.
4. **Mesclar a #343** (já ajustada). A partir daí, o deploy e a execução do coletor podem ser feitos pelo GitHub Actions, sem depender do Cloud Shell.
5. **Terminal (F3):** ler `nivon_core.saude_fontes` e as datas de referência de cada fonte (`ptax_quotes.reference_date`, a view ferroviária, `nivon_raw.agro_fonte_stage`, as tabelas marítimas) e mostrar no celular status, última execução OK, data de referência e frescor, separados. Em seguida, deploy no Cloud Run com IAP e acesso só do Bruno.
6. **Sete dias seguidos** sem intervenção, comprovados pela `saude_fontes`.
7. Só depois disso: lock de dependências com hash e Ruff (F2), núcleo `nucleo/` (PR 0 da F2), novas fontes, tendências e análises.

**Estimativa:** coletor estável em 1–2 dias de trabalho, terminal no celular em 3–5 dias, e mais 7 dias de observação.

## 7. O que é decisão do Bruno

Merge na `main`; deploy; qualquer concessão de IAM; custos, orçamento e cotas; variáveis `*_APPROVED`; acesso ao terminal; licença e direitos de uso de fontes; apagar branches (usar `scripts/arquivar_branches.sh`, que arquiva em tags antes de apagar; já aprovado pelo Bruno em 23/11).
