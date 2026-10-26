# NIVON — fila unificada de desenvolvimento Cloud
**Corte:** 25/10/2026 · **Origem:** requisitos e decisões consolidados dos chats, conferidos contra issues, módulos e documentação da `main`.

## Objetivo
Colocar o **NIVON utilizável o mais rápido possível**, começando por um terminal privado de dados reais. Concentrar trabalho de Codex Cloud e Claude Code em tarefas únicas no GitHub, sem agentes concorrendo pelo mesmo arquivo, sem criar mais uma plataforma de orquestração e sem depender do computador do proprietário ligado.

**Importante:** a fila identifica trabalho e prepara handoffs. Ela **não inicia sessões de Codex**, **não liga agendamentos**, **não autoriza cobranças** e não equivale a go-live. O serviço Cloud de Codex/Claude requer que alguém inicie uma tarefa no ambiente correspondente e aceite os limites da plataforma. Abrir o chat de origem no ChatGPT não inicia trabalhos.

## P0 — rumo ao go-live mínimo

| Ordem | Trabalho e evidência | Execução sugerida | Dependências e gate |
|---|---|---|---|
| 1 | [#263](https://github.com/brunocapellari-dotcom/NIVON/issues/263) proteção main, WIF/IAM e faturamento; [#264](https://github.com/brunocapellari-dotcom/NIVON/issues/264) auditoria remanescente | Claude / governança + Codex em PRs de código não sobrepostos | Evidência de administrador necessária para gates; não autoaprovar |
| 2 | [#277](https://github.com/brunocapellari-dotcom/NIVON/issues/277) terminal privado 0.1, E2E e diagnóstico | **Codex Cloud** | Serviços/Cloud Run permanecem privados e deploy condicionado a permissão de custo/IAM |
| 3 | [#143](https://github.com/brunocapellari-dotcom/NIVON/issues/143) ANTT/SIADE incremental/versionado GCP | **Claude Code** | Verificar BigQuery LIVE, artefatos RAW e replay; não criar recursos duplicados |
| 4 | [#94](https://github.com/brunocapellari-dotcom/NIVON/issues/94) CEPEA/IMEA/CONAB ponta a ponta | **Claude Code** | Datas, direitos, staging QUARANTINED, freshness e reconciliação Neon/GCP |
| 5 | [#144](https://github.com/brunocapellari-dotcom/NIVON/issues/144) ANTAQ oficial por hidrovia/produto | **Codex Cloud**, após concluir #277 | Fonte primária indisponível não pode virar realizado; não duplicar réplica |

A **entrega 0.1** usa dados ANTT/SIADE com proveniência e acesso privado. Outras séries entram só depois de homologação: [`GO_LIVE_PRIVADO_NIVON_20261025.md`](GO_LIVE_PRIVADO_NIVON_20261025.md). Leitura e CI do terminal existem; **não assumir** Cloud Run publicado ou custos aprovados. Projeto principal Google Cloud: `nivon-data`; dataset `nivon_raw`; bucket `nivon-data-raw-2026`.

## P1 — trabalho independente em paralelo

| Frente | Issue | Agente sugerido / arquivo principal | Atenção |
|---|---|---|---|
| Marítimo, AIS e CDP | [#278](https://github.com/brunocapellari-dotcom/NIVON/issues/278) | Codex · `src/nivon/maritime/` | Programado, observado e inferido não são equivalentes; Itacoatiara privada sem line-up oficial |
| Hidrometeorologia | [#279](https://github.com/brunocapellari-dotcom/NIVON/issues/279) | Codex · `src/nivon/hidromet_*.py` | INMET/ANA/INPE/CPTEC; observed vs forecast, SOURCE_LAG |
| Argentina MAGyP | [#280](https://github.com/brunocapellari-dotcom/NIVON/issues/280) | Codex · `src/nivon/argentina_magyp.py` | Replay, atualização, dados verificáveis, zero recursos duplicados |
| CEPEA fonte com indisponibilidade | [#145](https://github.com/brunocapellari-dotcom/NIVON/issues/145) | Claude após #94 | Corrigir frescor sem inventar observações quando origem HTTP falhar |
| Matriz rodoviária MDF-e | [#142](https://github.com/brunocapellari-dotcom/NIVON/issues/142) | Claude após #143 | Dependência de arquivo/API oficial: marcar BLOCKED se ausente |
| Frete anunciado, tendências | [#25](https://github.com/brunocapellari-dotcom/NIVON/issues/25) | Codex após #144 | Identidade de transportadora/estabelecimento, mesmo equipamento/condições |
| PTAX e grãos físicos | [#59](https://github.com/brunocapellari-dotcom/NIVON/issues/59) | Claude após #94 | Preservar Neon; migração GCP sem perda nem vazamento de tokens |
| Dados IBGE/PAM | [#131](https://github.com/brunocapellari-dotcom/NIVON/issues/131) | Codex após tarefas P0 | Direitos e revisões/competências antes da promoção |

## Estrutura de segurança e integração

- Toda tarefa tem **issue**, pequena branch, PR própria, contrato temporal, testes e evidência de resultados. Não tornar PRs antigas pré-requisito implícito; examine se a `main` já contém a correção.
- Codex e Claude são **ambos implementadores**. Os nomes na tabela são sugestões de distribuição; não autorizam acesso a contas nem iniciam tarefas automaticamente.
- Arquivos compartilhados (configuração GitHub Actions GCP, `AGENTS.md`, schemas ou documentação geral) têm **um único responsável por vez**. Evitar PRs simultâneas sobre os mesmos arquivos.
- Cada PR deve ser pequena e com branch atualizada a partir da `main`. Antes do merge, executar testes integrados e reconciliação; o proprietário decide permissões/IAM, divulgação de fontes privadas, custos e deploy.
- **Sem** criação de API Key faturada para ampliar tokens, bypass de limite, instalação em massa de extensões, acesso irrestrito da máquina ou mudanças destrutivas.
- Uma falha LIVE bloqueia uma afirmação de produção, não necessariamente todo desenvolvimento; registre evidência e avance para tarefas independentes.
- A arquitetura local da PR [#121](https://github.com/brunocapellari-dotcom/NIVON/pull/121) é **opcional** e não deve ser confundida com Codex Cloud. Não executar `/nivon-autonomo` na nuvem se isso exigir Docker/WSL/autenticação das duas CLIs no mesmo host.

## Critérios de aceite e ordem de verificação

1. **Código:** teste cobrindo erro, ausência de dado, limite, proveniência, competência/tempo, segurança, replay e idempotência.
2. **CI:** workflow aplicável ao commit exato, não testes antigos de uma PR diferente.
3. **LIVE:** quando houver acesso e autorização, evidência da coleta ou query ao GCP atual com data de execução e recursos reais; sem extrapolar CI.
4. **Entrega ao usuário:** terminal restrito acessível sob identidade autorizada e indicadores verdadeiros; custos previamente aprovados.

## Como usar agora no Codex Cloud

Crie **uma tarefa por issue**, apontando o Codex ao repositório `brunocapellari-dotcom/NIVON` e à branch `main` (ou branch recém-atualizada da tarefa). Instrua: “Leia `AGENTS.md` e a issue #277; implemente apenas o escopo de código; execute testes; abra uma PR pequena sem mesclar nem fazer deploy. Em seguida, entregue commit, evidência e bloqueios.”

Depois de iniciar #277, há tarefas independentes #278, #279 e #280 que podem usar ambientes Codex distintos (respeitando a cota real da assinatura). O mesmo vale para Claude em #143/#94, evitando conflitos de escopo. **Os chats do ChatGPT não são conectados automaticamente à fila**; novas decisões devem virar alteração no GitHub via issue/PR.

**Painel de acompanhamento:** GitHub Issues e PRs. Arquivo de máquina complementar: `docs/NIVON_BACKLOG_EXECUCAO.json`. O backlog é uma projeção e não substitui a prova de status no GitHub.
