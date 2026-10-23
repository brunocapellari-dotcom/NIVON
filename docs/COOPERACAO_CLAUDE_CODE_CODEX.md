# NIVON — cooperação Claude Code + Codex e economia de tokens

## Estado
Arquivos versionados em PR; **nenhuma execução noturna iniciada**. Não há prova de CLI autenticada no host, configuração MCP instalada ou serviços de nuvem ativos. Nenhum fluxo real de coleta foi habilitado.

## Arquitetura
- Orquestrador: [Cezar](https://github.com/open-mercato/cezar), duas workflows independentes \`nivon-claude-implement\` e \`nivon-codex-implement\`, cada uma com seu agente e testes offline.
- Coordenação: ledger SQLite no \`git-common-dir\`, compartilhado por worktrees, com atribuição transacional, escopos exclusivos, checkpoints e relatório. O ledger **não dispara** sessões, nem garante fallback automático.
- Eficiência de tokens: instruções curtas CLAUDE.md/AGENTS.md, busca dirigida, redução determinística de logs em \`nivon.token_guard\`, compactação nativa e medição de tokens informados pelas CLIs.
- Integrações a avaliar em piloto: **Codebase Memory MCP OU Serena** (grafo de código), Context Mode (respostas grandes), RTK (logs), Repomix (mapa estático), Claude-Mem (memória), CCPM (GitHub/issues). Não instalar todos: redundâncias, licenças e hooks podem piorar custo/segurança. ToolSearch do Claude e compactação nativa do Codex são preferidos antes dos proxies.

## Segurança indispensável
A documentação do Cezar registra que seu modo Codex padrão é \`danger-full-access\`/aprovação \`never\` e ignora \`allowedTools\`. No host, **CEZ_CODEX_NETWORK=0** ativa modo \`workspace-write\` sem rede. Verifique isso na versão instalada; use usuário ou contêiner isolado sem segredos de nuvem e sem diretórios privados montados. O workflow Claude tem apenas ferramentas de leitura/edição, sem Bash; o teste roda em passo fixo do orquestrador. Não usar \`--dangerously-skip-permissions\` ou Bash irrestrito.

Cezar não torna assinaturas ilimitadas; se ambos atingirem cota, pausar até renovação. Não rodar com APIs pagas, sem limites claros de recursos, nem abrir cockpit sem autenticação na internet. Dados privados/licenças de CEPEA e IMEA permanecem fora do GitHub público.

## Passos locais, após revisão e merge
Git, Python >=3.11, Node >=20 e os comandos \`claude\` e \`codex\` precisam estar disponíveis e autenticados pelo próprio usuário. **Não inserir tokens em repositório ou argumentos.**

\`\`\`sh
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python -m nivon.cooperacao seed docs/COOPERACAO_TAREFAS.json
PYTHONPATH=src python -m nivon.cooperacao claim --agent claude
PYTHONPATH=src python -m nivon.cooperacao claim --agent codex
PYTHONPATH=src python -m nivon.cooperacao report
# Primeiro testar com agente simulado e sem uso de assinatura:
CEZ_DRY_RUN=1 CEZ_CODEX_NETWORK=0 CEZ_TELEMETRY=0 npx cezar-run
# Somente em ambiente efetivamente isolado e validado:
# CEZ_CODEX_NETWORK=0 CEZ_TELEMETRY=0 npx cezar-run
\`\`\`

No cockpit, iniciar duas tarefas **distintas**, usando as workflows correspondentes e copiando ID, escopo, critérios e título retornados pelo ledger. Cezar cria worktrees e mantém branches; jamais habilitar merge automático.

Para marcar tarefa concluída só depois de validar código/commit:
\`\`\`sh
PYTHONPATH=src python -m nivon.cooperacao done --agent claude --id nivon-inmet-01 --note 'SHA + evidência dos testes'
\`\`\`
Em limite de uso, primeiro **confirmar encerramento do processo anterior** e salvar checkpoint; depois executar \`handoff --agent claude --to codex --id nivon-inmet-01 --note 'branch, SHA, arquivos, testes, próximo passo'\`. O Codex poderá reivindicar a tarefa na próxima tentativa. Isso não transfere automaticamente o checkout, nem finaliza commits pendentes. Tarefas com lease vencido não são retomadas automaticamente (o worker pode continuar vivo).

## Gates para uso noturno
1. Simulação local, revisão da segurança do Cezar e permissão workspace-write sem rede no Codex.
2. Teste real curto com duas worktrees disjuntas, sem secrets ou rede; verificar CI e commits.
3. Comparar tokens totais por tarefa aprovada, tempo, falhas, consultas repetidas e retrabalho. Números divulgados por projetos terceiros não são medição NIVON.
4. Instalar **um** indexador aprovado e testar antes/depois; optar por Context Mode/RTK apenas se houver ganho líquido comprovado.
5. Só depois programar o host; esta PR não configura agenda, deploy, cobrança ou execução ininterrupta.

Referências: [Cezar](https://github.com/open-mercato/cezar/blob/main/docs/reference.md), [Codebase Memory MCP](https://github.com/DeusData/codebase-memory-mcp), [Serena](https://github.com/oraios/serena), [Context Mode](https://github.com/mksglu/context-mode), [Repomix](https://github.com/yamadashy/repomix), [RTK](https://github.com/rtk-ai/rtk).
