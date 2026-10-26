# AGENTS.md — NIVON (Codex Cloud, Claude Code e desenvolvimento colaborativo)

Este repositório é a **única fonte operacional** para desenvolvimento do NIVON. O histórico de chats é contexto de origem, não autorização para publicar, pagar, apagar ou implantar. Antes de codificar, use o backlog em `docs/EXECUCAO_UNIFICADA_NIVON.md` e a fonte técnica explicitamente indicada na tarefa.

## Missão e ordem de prioridade

**P0:** alcançar go-live privado verificável com a série ANTT/SIADE no terminal web, integridade de dados no BigQuery, proteção IAM/orçamento e coleta incremental confiável. **P1:** CEPEA, IMEA e CONAB com freshness, direitos de uso e registros point-in-time; ANTAQ e cadeias rodoviárias, AIS/portos, meteorologia, indicadores e pesquisa quantitativa. **P2:** melhorias editoriais, análises avançadas e expansões aprovadas.

**Vercel está proibido no NIVON:** não sugerir Vercel, adicionar dependências de Vercel ou abrir novos deployments nessa plataforma. O legado de configurações Vercel deve ser removido por PR específica (#286), preservando frontend e sem tocar em recursos remotos.

A infraestrutura primária é Google Cloud (projeto `nivon-data`, dataset `nivon_raw`, bucket `nivon-data-raw-2026`), conforme verificação na tarefa. **Não crie outro dataset, bucket, projeto, arquitetura ou coletor canônico sem detectar uma lacuna real.** Neon/PTAX existente não deve ser apagado ou cortado antes de reconciliação. AgroLog MT é fonte legada para reaproveitamento; Hermes e Holding não são dependências do go-live. WhatsApp é projeto separado.

## Disciplina de implementação

1. Leia esta instrução, a tarefa designada, `docs/EXECUCAO_UNIFICADA_NIVON.md` e **apenas os módulos relevantes**. Evite reprocessar toda a documentação.
2. Verifique o estado atual da `main`, PRs relacionadas e testes para **não repetir soluções prontas**. Distingua código/CI de execução real no Google Cloud.
3. **Autonomia para trabalho reversível:** criar branch/PR, implementar, testar, corrigir e continuar para a próxima tarefa elegível sem perguntar ao usuário. Apenas custos, mudanças de IAM, deploy, segredos, permissões de fonte, merge main e remoção remota irreversível exigem gate explícito. Quando houver gate, documentar e avançar. Uma tarefa por branch e PR; primeiro entregue a menor mudança E2E que resolva a falha. Em tarefas independentes, Codex e Claude podem trabalhar em paralelo **apenas sem alterar os mesmos arquivos**. Se houver sobreposição, serialize.
4. Faça testes em lote: unidade/integrados, replay, idempotência, erro, limites de rede, segurança, contratos temporais. Rode o conjunto CI adequado; não marque GO com testes sintéticos apenas.
5. Use comandos de terminal resumidos e busca de símbolos/arquivos específicos; leia logs enormes por filtros/trechos. Registre tarefas, commits e evidências em PR/issue. Avalie progresso por **entregas aceitas por token**, não por linhas alteradas.
6. Se um acesso externo, token, direito de uso, Cloud Run, orçamento ou IAM bloquear uma tarefa, anote o bloqueio com precisão e **avance para outra tarefa independente**. Não oculte a limitação.
7. **Não efetue merge na main**, deploy, criação de recursos faturáveis, concessão de IAM, API paga, coleta restrita, alteração destrutiva nem autorização de publicação sem gates humanos explicitamente documentados. Não copie credenciais para issues/commits.
8. Não inicie execuções autônomas no computador do usuário. A automação noturna local em PR #121 tem pré-requisitos próprios e **não deve ser executada dentro de Codex Cloud/Claude Code Cloud**.

## Contratos de verdade

Todo dado precisa preservar fonte/URL, hash RAW quando aplicável, `data_referencia`, `data_publicacao`, `data_coleta`, competência, unidade, granularidade, natureza (**OBSERVADO, ESTIMADO, PROJETADO, INFERIDO, SOURCE_LAG**) e limite de direitos. `PROGRAMADO`/line-up não é `REALIZADO`; AIS não prova tonelagem, carga, trading ou operação. Publicações de transportadoras são **divulgações de fretes anunciados**, não cotações negociadas. Não promover staging `QUARANTINED` para série canônica sem homologação temporal e de uso. Não somar ANTT, ANTAQ e estimativas como se fossem cobertura completa.

## Encerramento de cada tarefa

No PR: **(1)** decisão e problema específico; **(2)** arquivos e funcionalidade; **(3)** evidência de teste/CI e, separadamente, prova LIVE, se houver; **(4)** riscos, custos, licenças/IAM; **(5)** próximo item e dependências. Quando houver bloqueio real, deixar o código e testes em estado utilizável e marcar `BLOCKED`, não prometer conclusão.
