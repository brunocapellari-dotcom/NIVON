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
- impõe até **8 tarefas, 120 minutos totais e 15 minutos por tarefa** por execução; dependências liberam tarefas adicionais apenas quando seus pré-requisitos ficam `done`;
- não concede ferramentas Bash ao Claude (modo restricted, ferramentas de arquivo e sem MCP);
- executa Codex em sandbox workspace-write com política sem perguntas e sem rede por padrão;
- exige \`compileall\` e unittest offline antes de commit local; arquivos fora do escopo bloqueiam conclusão;
- após testes, faz cherry-pick serializado do commit em `autonomo/integracao`, roda regressões novamente em Docker offline e só então marca a tarefa como `done`; preserva a branch de tarefa se houver falha; conserva logs e checkpoints; quando identifica cota, transfere a tarefa explicitamente ao outro agente;
- **não** faz push, merge na `main`, instalação, deploy, agendamento, integração de dados, chamadas a bancos ou compras. A única integração automática é a branch **local** `autonomo/integracao`.

O supervisor usa lock local `.nivon-local/supervisor.pid` para impedir duas instâncias e **não espera infinitamente por renovação de cotas**. Uma tarefa marcada como quota pode receber handoff, mas worktree do agente original permanece para inspeção. Seu WIP **não** é migrado automaticamente: a segunda tentativa recomeça a partir da base Git. O programa não recupera leases vencidos porque um processo ainda pode estar ativo.

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


## Planejador de backlog — uso e limites
\`\`\`sh
PYTHONPATH=src python -m nivon.planejador preview --github
PYTHONPATH=src python -m nivon.planejador refresh --github
PYTHONPATH=src python -m nivon.contexto_codigo index
PYTHONPATH=src python -m nivon.contexto_codigo find precipitacao --limit 8
\`\`\`

O planejador executa sem LLM, cruza \`docs/PLANEJADOR_ROADMAP.json\`, o código efetivamente presente e as issues abertas. Gera candidatos por falta de testes e, se houver \`gh\` autenticado, lê até 60 issues sem realizar mutações. O uso de informações externas é sempre classificado como **não confiável**.

Apenas issues com label \`nivon-auto-ready\` e bloco HTML estrutural são elegíveis:
\`\`\`text
<!-- NIVON-AUTO {"title":"Aprimorar normalizador de chuvas","scope":["src/nivon/inmet_historico.py","tests/test_inmet_historico.py"],"priority":30,"acceptance":"Testes offline e preservação de nulos."} -->
\`\`\`
Não há execução de comandos extraídos de comentários. Arquivos fora de \`src/\` e \`tests/\`, referências a implantação, licenças e credenciais ou dependências pendentes não entram na fila. Issues complexas não são transformadas automaticamente em código sem escopo revisado. O roteiro versionado é a fonte confiável de objetivos.

O índice AST é incremental por hash, guarda só nomes/linhas de símbolos e fornece cápsula de contexto de até 450 caracteres quando houver correspondência com a tarefa; não lê o código completo no prompt.

Quando o roteiro terminar e não houver novas issues aprovadas ou lacunas seguras, **o supervisor encerra o ciclo**. Não inventa tarefas intermináveis e não efetua merge automático; isso é uma proteção contra loops de custo e alterações descontroladas.


## Isolamento obrigatório dos testes e diagnóstico
**Atenção:** testes são execução de código escrito por agentes, portanto o supervisor exige Docker disponível e imagem \`python:3.11-slim\` **já instalada localmente**. Não baixa imagens nem instala ferramentas sozinho. A compilação e os testes rodam com \`docker run --pull never --network none\`, sem capabilities, privilégios extras nem credenciais de nuvem injetadas; limites de CPU, RAM e processos. Imagens/volumes não são publicados. Em host que não aceite esse isolamento, **a produção autônoma é bloqueada**.

\`\`\`sh
bash scripts/nivon-autonomo.sh doctor
bash scripts/nivon-autonomo.sh plan
bash scripts/nivon-autonomo.sh
\`\`\`

\`doctor\` só verifica binários, flags de CLI e imagem Docker local. **Não confirma autenticação ou franquias**. Para baixar manualmente uma imagem de teste, após revisar origem e custos do ambiente, usar o procedimento documentado pelo Docker; o supervisor não fará esse download.

## Ferramentas de terceiros e estado real
- **Funcionalmente incorporados sem dependências:** busca estrutural AST incremental, contexto mínimo, separação em tarefas estilo Ralph, checkpoints, GitHub read-only e critérios de aceite estilo CCPM; Ruff usado opcionalmente para reparar erros.
- **Opcionais detectadas pelo doctor:** \`ruff\`, \`rg\`, \`ast-grep\`, \`serena\`, \`codebase-memory-mcp\`, \`rtk\`, \`uv\`.
- **Não instaladas nem ativadas automaticamente:** Serena / Codebase Memory MCP, Context Mode, RTK, Claude-Mem, Superpowers e qualquer proxy de autenticação. Devem ser avaliadas separadamente em um piloto, porque instalação global de hooks/MCP pode interferir nas duas CLIs. Os agentes autônomos atualmente usam busca interna restrita; o índice Python é injetado como dica estrutural, não como ferramenta MCP com acesso ampliado.
- **Não há promessa de tokens infinitos.** Métricas de consumo vindas das CLIs podem ser \`null\`. O sucesso deve ser medido por tarefa concluída e integrada, não apenas pela contagem de commits em worktrees.

## Plano de execução em ondas
1. Rodar \`doctor\`, instalar manualmente só as dependências ausentes sob controle do host e fazer piloto curto de duas tarefas.
2. Medir tokens e qualidade no fluxo sem MCP; instalar *um único* indexador para comparação, sem duplicar o índice.
3. Expandir a geração de backlog a issues com label \`nivon-auto-ready\` e especificação JSON delimitada; não autorizar texto livre de issues como instruções.
4. Após CI, revisar integração de worktrees. Merge na \`main\`, coleta live, cron/cloud e gastos não são decisões da IA.


## Quando o código fica pronto
Cada tarefa concluída deixa seu commit na branch \`autonomo/<tarefa>-<agente>-<tentativa>\`. Após passar nos testes, o executor faz cherry-pick da alteração em \`autonomo/integracao\`, que nunca é \`main\`. A conclusão no backlog somente é registrada depois que a branch integrada passa também nos testes dentro do Docker offline. Tarefas dependentes passam a se basear nessa branch atualizada.

A integração local não implica uma PR publicada no GitHub. O resultado pode ser inspecionado pelo operador com:
\`\`\`sh
git log --oneline autonomo/integracao -15
git diff main..autonomo/integracao --stat
\`\`\`
O push e a PR ampla de integração são decisões separadas; o processo não muda repositórios remotos automaticamente. Isso evita conflitos com as dezenas de PRs existentes do NIVON ainda não reconciliadas com \`main\`.
