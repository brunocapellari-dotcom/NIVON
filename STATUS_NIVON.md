# NIVON — Situação Operacional (fonte única de acompanhamento)

> **Corte da verificação:** 26/10/2026, horário de Mato Grosso. **SHA de referência:** `4cf7861a5df75ad84dfa6ca6def5aa4643622408`. Este arquivo é uma fotografia auditável, **não** telemetria em tempo real. Cada alteração de estado exige evidência nova. Não inferir que uma PR aberta, CI verde ou botão de workflow significa produção implantada.

## Situação atual

**NIVON integral: NÃO HOMOLOGADO.** **Go-live privado do terminal Cloud Run: NÃO COMPROVADO.** A infraestrutura de dados tem provas reais setoriais.

| Entrega | Estado verificado | Evidência / limite |
|---|---|---|
| ANTT/SIADE 2006–ago/2026 no BigQuery | **DADO REAL COMPROVADO** | [Leitura ferroviária](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257778476); não comprova terminal Cloud Run |
| Imbituba/PortWatch marítimo em GCS + BigQuery | **LOTE REAL EXECUTADO** | [Run 40293106092](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40293106092), concluído em 26/10/2026; não comprova todas as rotas/terminais, nem recorrência |
| Painel HTML no bucket privado | **PUBLICADO SOMENTE EM GCS** | [Documentação e limites](docs/GO_LIVE_INTERNO_NIVON_20261025.md); não é URL web autenticada |
| Terminal web privado Cloud Run | **IMPLEMENTADO; DEPLOY NÃO COMPROVADO** | [Issue de go-live #281](https://github.com/brunocapellari-dotcom/NIVON/issues/281); provas HTTP de contêiner não são URL Cloud Run real |
| CEPEA/IMEA/CONAB/Argentina em BigQuery canônico | **PARCIAL / NÃO HOMOLOGADO INTEGRALMENTE** | [Plano de ativação GCP](docs/ATIVACAO_GCP_CARGA_UNICA_20261025.md); exigir fonte/competência, dois ciclos e readback |
| Preços futuros/físicos, fretes, pecuária, agroindústria e clima | **PARCIAL / REQUER E2E POR DOMÍNIO** | Não rotular como operacional com base em testes unitários |
| Tendências, previsões, IVO e briefing/WhatsApp | **SEM PROVA DE OPERAÇÃO INTEGRAL** | Exigir backtest, URL/API e entrega real conforme o caso |
| Proteção da `main` | **DESATIVADA no corte** | Endpoint GitHub `branches/main`: `protected=false`; deve ser resolvida antes de escala de merges concorrentes |

## Bloqueios críticos: primeira publicação privada

1. **Unificar PRs concorrentes de go-live** (#309–#320) e manter apenas um servidor/terminal e um fluxo de deploy. A [PR #302](https://github.com/brunocapellari-dotcom/NIVON/pull/302) tem backlog proposto, mas não está mesclada.
2. **Verificar Artifact Registry, conta de execução, WIF e IAM** por inspeção autenticada; campos `NIVON_TERMINAL_ARTIFACT_REPO` e `NIVON_TERMINAL_EXECUTION_SA` estavam vazios no diagnóstico anterior. Não inventar conta nem autorizar privilégios amplos.
3. **Revisar e autorizar custos/deploy** explicitamente, sem aceitar `true` automático para gates de orçamento e publicação.
4. **Executar deploy manual autorizado, depois teste HTTPS autenticado real**: IAM sem acesso anônimo, URL, /healthz, API ferroviária, fonte, competência, limites, logs, revisão da imagem, rollback.
5. **Provar dois ciclos operacionais** quando a funcionalidade envolver atualização periódica; um run isolado não é operação contínua.

## Frentes com responsabilidade definida (8)

| Frente | Domínio e definição de pronto | Área principal |
|---|---|---|
| **F00 Direção e Integração** | Uma fila rastreável, matriz de entregas, responsáveis, integração e redução de PRs duplicadas | Issues, PRs, `STATUS_NIVON.md` |
| **F01 Execução Claude Code + Codex** | Funcionalidades completas em PRs, CI e evidências; assistência em worktree/branch isolado; sem comandos locais ao usuário | Engenharia transversal |
| **F02 Plataforma GCP e Dados** | Infraestrutura única, GCS, BigQuery, coleta/recuperação, segurança e operação | `infra/`, `src/nivon/*bigquery*`, workflows |
| **F03 Agricultura, Internacional e Cadeias** | CONAB, IMEA, CEPEA, IBGE, Argentina, pecuária, indústria e fertilizantes com E2E por família | Coletores e domínio econômico |
| **F04 Mercados e Modelos** | CBOT/CME, ICE, B3, PTAX, preços físicos, tendências e previsões com backtests | Mercados e quantitativo |
| **F05 Logística e Marítimo** | Fretes, rodovia, ferrovia, hidrovia, ANP, portos, AIS e line-ups conciliados | Logística multimodal e marítimo |
| **F06 Meteorologia e Hidrologia** | Séries oficiais, previsões, dados por localidade e consumo pelos motores | Hidromet e agrometeorologia |
| **F07 Terminal, IVO e Distribuição** | Único terminal privado com API, IVO, briefing diário e integração de envio autorizada | UI, API, editorial |
| **Controle independente** | Auditoria de cada PR e gate de release exercidos por F00 + revisor que não implementou o código; não usar autohomologação | CI, evidências e aprovação |

F01 não assume a propriedade permanente de módulos alheios; implementa em lotes encomendados por F00. F02 responde por contratos comuns. Integrações de arquivos compartilhados são serializadas.

## Previsão de entrega (metas condicionais, não promessa de produção)

**Premissas:** execução técnica frequente em ambiente remoto já disponível, resolução de IAM/custo na primeira semana, revisão rápida de PRs e acesso legítimo às fontes essenciais. Sem essas condições, não há prazo garantido.

| Marco | Janela-alvo | Critério real de aceite |
|---|---|---|
| **M0: baseline e backlog sem PRs duplicadas** | 26–30/10/2026 | Branch protegida e matriz de funcionalidades com donos, riscos e SHA |
| **M1: terminal privado real** | 03–10/11/2026 | URL Cloud Run autenticada, ANTT real, resposta de API, IAM e rollback verificados |
| **M2: núcleo de dados e mercados utilizável** | 23/11–11/12/2026 | Indicadores agrícolas/preços e transportes elegíveis com E2E, frescor e consulta integrada |
| **M3: produto multiárea, motores e interface ampliados** | 14/12/2026–29/01/2027 | Logística, marítimo, hidromet, tendências e IVO integrados, resultados experimentais identificados |
| **M4: go-live integral homologado** | 01/02–26/03/2027 | Todas as funções prometidas com evidência real, segurança, fontes legais, backtest quando aplicável, briefing, operação contínua |

**Alerta de prazo:** M4 pode ultrapassar março de 2027 se faltar acesso oficial a MDF-e/ANTAQ/AIS, direitos de cotações, cobertura histórica suficiente ou equipe/execução contínua. Nesses casos, registrar funcionalidade como BLOQUEADA POR FONTE EXTERNA, nunca como concluída.

## Regra de acompanhamento

Cada frente deve reportar no GitHub em formato: **Estado → próxima entrega → responsável → prazo-alvo → última prova (SHA, workflow, endpoint ou consulta) → bloqueio e ação necessária**.

Estados padronizados: `NÃO INICIADO`, `EM EXECUÇÃO`, `TESTADO EM CI`, `DADO REAL VALIDADO`, `INTEGRADO`, `HOMOLOGADO`, `OPERACIONAL`, `BLOQUEADO`. Não atribuir percentual genérico de conclusão.

**Fonte de verdade para andamento:** [Issues](https://github.com/brunocapellari-dotcom/NIVON/issues), [PRs](https://github.com/brunocapellari-dotcom/NIVON/pulls), [Actions](https://github.com/brunocapellari-dotcom/NIVON/actions), [gate #281](https://github.com/brunocapellari-dotcom/NIVON/issues/281). Status publicado deve ser atualizado quando evidências mudarem. Nenhum job novo ou custo de nuvem é criado por este documento.

**Não instalar nada no PC/celular.** O proprietário consulta GitHub e, após deploy aprovado, terminal NIVON por navegador. Claude Code/Codex rodam somente em ambiente remoto já disponível e autenticado, sem pressupor sessão eterna ou gratuidade ilimitada.
