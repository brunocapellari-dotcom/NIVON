# NIVON — motor local de desenvolvimento autônomo

**Estado:** código no PR, sem supervisão noturna ativa, sem deploy/custos. Requer verificação das CLIs instaladas no host. Testes sintéticos offline não provam operação real das sessões autenticadas.

## Como iniciar (após revisão/merge ou checkout da branch)

No terminal do repositório:
\`\`\`sh
bash scripts/nivon-autonomo.sh
# ou dentro do Claude Code: /nivon-autonomo
\`\`\`
Ambos chamam o módulo local \`nivon.autonomia\`, que:
- exige Git e CLIs \`claude\` e \`codex\` existentes e checkout principal sem mudanças;
- lê o backlog SQLite já alimentado por \`docs/COOPERACAO_TAREFAS.json\`;
- inicia supervisor local destacado; até duas tarefas em paralelo, uma por provedor;
- cria uma worktree/branch local exclusiva por tarefa, sem jamais escrever na \`main\`;
- impõe até **8 tarefas, 120 minutos totais e 15 minutos por tarefa** por execução;
- não concede ferramentas Bash ao Claude (modo restricted, ferramentas de arquivo e sem MCP);
- executa Codex em sandbox workspace-write com política sem perguntas e sem rede por padrão;
- exige \`compileall\` e unittest offline antes de commit local; arquivos fora do escopo bloqueiam conclusão;
- conserva logs no host e faz checkpoint no banco; quando identifica limite de cota, oferece a tarefa ao outro agente se ainda não houve segunda tentativa;
- **não** faz push, merge, instalação, deploy, agendamento, integração de dados, chamadas a bancos ou compras.

O supervisor **não espera infinitamente por renovação de cotas**. Uma tarefa marcada como quota pode receber handoff, mas worktree do agente original permanece para inspeção. Seu WIP **não** é migrado automaticamente: a segunda tentativa recomeça a partir da base Git. O programa não recupera leases vencidos porque um processo ainda pode estar ativo.

## Operação e parada

\`\`\`sh
bash scripts/nivon-autonomo.sh status
bash scripts/nivon-autonomo.sh stop
# modo acoplado ao terminal:
bash scripts/nivon-autonomo.sh run
\`\`\`

A parada é cooperativa: permite concluir as tarefas já iniciadas. Logs privados em \`.nivon-local/logs/\`, relatório em \`.nivon-local/last-run.json\`. Verificar branches \`autonomo/*\` antes de integrar PRs.

## Evoluções recomendadas e não habilitadas

- [Ralph](https://github.com/snarktank/ralph): iterações com contexto novo, uma história pequena de cada vez; já refletido no limite de tarefas por sessão.
- [CCPM](https://github.com/automazeio/ccpm): PRD, tarefas e dependências — adotar apenas quando o backlog GitHub estiver sincronizado com o ledger.
- [Superpowers](https://github.com/obra/superpowers): skills de execução/teste — instalar somente após medir carga adicional.
- [12-Factor Agents](https://github.com/humanlayer/12-factor-agents): estado e controle fora do prompt — usado como princípio.
- [Codebase Memory MCP](https://github.com/DeusData/codebase-memory-mcp) **ou** [Serena](https://github.com/oraios/serena): avaliar apenas um indexador inicialmente.
- Claude ToolSearch nativo e \`--restricted\` reduzem risco e sobrecarga de ferramentas no modo script.

## Validação que falta antes de deixar a madrugada inteira

1. Confirmar \`claude --help\` com \`--restricted\`, \`--permission-prompts none\`, \`--tools\`; confirmar \`codex exec --help\`.
2. Executar piloto curto local usando tarefas de teste, sem credenciais cloud, secrets, commits em branches oficiais nem serviços externos.
3. Testar travamento, quotas, interrupção, status/restart e checar que nenhuma worktree alterou dados privados.
4. Medir tokens reais e tarefas aprovadas por token antes/depois, **não** assumir economias anunciadas pelos repositórios.
5. Não instalar plugins que interceptem autenticação, exponham segredos, alterem termos de uso ou bypass de cota.

As CLIs usam sessões autenticadas no host; apenas o código nesta PR não demonstra acesso funcional. Não se pode inferir ausência absoluta de cobranças por execução a partir do script; o operador deve verificar o método de autenticação e faturamento das duas ferramentas.
