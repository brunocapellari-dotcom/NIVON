# NIVON — Dueto de desenvolvimento (Claude Code + Codex)

## Inspiração e decisão de arquitetura

Uma visualização com agentes lado a lado, tarefas, estado dos testes e evolução pode ajudar a operar o NIVON sem ler logs gigantes. Projetos públicos como [duet-agents](https://github.com/JonathanRosado/duet-agents), [duet](https://github.com/volkan/duet) e [agent-duet](https://github.com/chriswu727/agent-duet) exploram colaboração multiação, mensagens e revisão.

**A imagem de referência não prova que um desses repositórios é o projeto exato mostrado.** Não importamos scripts ou instaladores externos. Em especial, certos projetos usam permissões padrão como \`danger-full-access\` ou \`--dangerously-skip-permissions\`; não são compatíveis com a política de segurança do NIVON sem revisão substancial.

No NIVON, Claude Code e Codex continuam como **implementadores de igual autoridade**, cada um em sua própria worktree. Não existe "Codex arquiteto permanente / Claude executor permanente". Um eventual modo de revisão cruzada é uma decisão futura separada, dependente de orçamento e de benchmarks.

## O que está implementado

\`src/nivon/dueto_painel.py\` produz uma fotografia do estado do ledger compartilhado, consumindo apenas CPU local:
- tarefas pendentes, em execução, concluídas e bloqueadas;
- tentativas, transferências de cada agente e métricas de tokens observadas;
- produtividade por 100 mil tokens apenas com dados de CLI completos;
- tarefas recentes sem incluir notas, logs ou conteúdo de prompts;
- janela noturna America/Cuiaba com início permitido ou não.

O painel HTML **não tem servidor, rede, JavaScript, fontes externas nem comandos de geração de código**. Escapa títulos que vierem de issues e mantém o HTML em \`.nivon-local/painel-dueto.html\`, modo 0600. O resultado não deve ser enviado a terceiros sem revisão de informações de projeto. Arquivos de logs continuam no host. O painel é **uma fotografia quando solicitado**, não uma transmissão contínua.

### Comandos do dia, sem tokens de modelos

\`\`\`bash
bash scripts/nivon-autonomo.sh dueto  # JSON de status
bash scripts/nivon-autonomo.sh painel  # escreve caminho do HTML local
bash scripts/nivon-autonomo.sh metrics
bash scripts/nivon-autonomo.sh efficiency
bash scripts/nivon-autonomo.sh plan
\`\`\`

Depois de gerar o painel, abra o arquivo HTML impresso pelo comando no navegador local. Execute novamente para atualizar a fotografia; não existe watcher nem servidor nesta implementação.

### Execução à noite

Somente o comando separado \`bash scripts/nivon-autonomo.sh\` (ou \`/nivon-autonomo\` no Claude Code autenticado) pode tentar iniciar o supervisor. Ele está limitado a 20h–6h no fuso \`America/Cuiaba\` e exige confirmação de versões, autenticação das assinaturas e sandbox local. Não foi executado durante esta rodada.

## Gates que permanecem

- Integrar e homologar as duas CLIs autenticadas, sem chaves de API cobradas.
- Executar piloto noturno para confirmar permissões e limpeza dos processos.
- Medir tokens por tarefa aceita e qualidade antes/depois; redução de texto em logs não é automaticamente economia de tokens totais.
- Não habilitar execução colaborativa por tmux, proxy MCP ou revisão por um segundo modelo sem verificar segurança, consumo e sobreposição de tarefas.
- Não iniciar dois sistemas independentes de orquestração (Cezar e NIVON) sobre o mesmo checkout ou a mesma fila sem uma autoridade exclusiva.
