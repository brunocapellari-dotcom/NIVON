# Skill — NIVON Cooperative Development

Objetivo: implementar uma tarefa pequena, testada e isolada, compartilhando evidências — não fazer auditoria do outro agente.

1. Leia \`README.md\`, \`AGENTS.md\` e apenas documentação relacionada à tarefa.
2. Respeite escopo de arquivos e worktree alocados; outra tarefa pode rodar em paralelo.
3. Use descoberta semântica quando disponível: Codebase Memory MCP **ou** Serena, não indexadores redundantes. Sem MCP, faça busca direcionada por símbolo.
4. Evite saídas grandes; preserve logs completos localmente, e use \`python -m nivon.token_guard arquivo.log\` para extratos curtos. Falhas devem continuar visíveis.
5. Implemente e teste com fixtures offline; não habilite rede nem credenciais nos testes.
6. Não altere licenças, segurança, dados sensíveis ou fontes autenticadas sem autorização aplicável.
7. Não crie cobranças, deploys, crons ou integração com serviços pagos automaticamente.
8. Se alcançar limite de uso, deixe checkpoint: task ID, branch, SHA, arquivos, último teste, próximo passo. Não duas IAs no mesmo checkout.
9. Não faça merge automático nem instale extensões/roteadores que interceptem autenticação.
10. Entregue evidência de testes; prossiga para tarefas locais reversíveis sem solicitar aprovação rotineira.
