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


## Medição real de tokens e retomadas (23/10/2026)

A fila SQLite conserva **uma linha por tentativa** na tabela `attempt_metrics`, incluindo agente, horário de início/fim, estado (done/blocked/handoff), tokens observados e leitura de cache quando a CLI disponibiliza o campo. Transferir uma tarefa de Claude para Codex **não apaga** o consumo da primeira tentativa.

As origens são `claude --output-format json` e `codex exec --json`, com interpretação distinta:
- Claude: `input_tokens` representa entrada não cacheada; a métrica de entrada processada agrega `cache_read_input_tokens` e `cache_creation_input_tokens`, quando disponíveis.
- Codex: `input_tokens` já inclui `cached_input_tokens`; os eventos `turn.completed` são agregados sem contar as mensagens `item.*` novamente.
- Quando não houver dados, o relatório mantém `null` e contabiliza a tentativa como **métrica ausente**, não como zero consumo.
- Tokens cacheados **não são economia comprovada de tokens da assinatura**; análise de preço/cota depende do provedor e da modalidade de acesso.

Consultas permitidas durante o dia, sem usar modelos de IA:

```bash
bash scripts/nivon-autonomo.sh metrics
bash scripts/nivon-autonomo.sh integration-check
```

O primeiro oferece apenas indicadores consolidados por agente, sem anexar logs gigantes. O segundo verifica divergências entre a `main` local e a branch do checkout, sem `git fetch`, `merge`, `rebase` ou `push`. **Uma main local antiga não representa necessariamente a atual no GitHub**; comparar no GitHub antes de integração final.

### Próxima validação antes de ampliar a autonomia

Executar um piloto noturno real e confrontar as métricas com as saídas das CLIs. Medir: tarefas aprovadas por 100 mil tokens de entrada+saída, proporção de reexecução, duração das tentativas e tempo total até integração. Não atribuir economia percentual sem comparação de tarefas equivalentes. A branch `autonomo/integracao` segue estritamente local; nunca fazer merge remoto automático por causa de um relatório de divergências.

## Compatibilidade real com a assinatura do Claude e dependências Parquet

O modo `--bare` **não** é usado no supervisor: embora economize contexto, ele não recupera a autenticação OAuth da assinatura Claude. A execução passou a usar `--restricted --safe-mode` com ferramentas de arquivo limitadas e prompts não interativos; o modo `--safe-mode` desliga customizações opcionais mantendo a autenticação. Antes de iniciar, `doctor` exige `claude auth status` com método de assinatura e `codex login status` usando ChatGPT, além de confirmar as flags e imagem Docker local. Logins por API faturada são bloqueados por padrão, sem expor credenciais nem iniciar modelos.

Os novos testes de hidrovias ANTAQ incorporados à `main` usam `pyarrow`. O workflow genérico de testes offline do NIVON **não instala PyArrow**: nesse ambiente, os dois testes opcionais Parquet são explicitamente ignorados. Existe um workflow separado `antaq-hidrovia-detalhe.yml` que instala PyArrow para executar esses testes e fazer uma prova dedicada, sujeita a seus próprios critérios e condições de rede; não foi acionado nesta rodada. A dependência de PyArrow não é instalada no host pelo supervisor. **O contêiner local `python:3.11-slim` não inclui PyArrow**, portanto o piloto noturno com a `main` ampliada deve continuar bloqueado até que exista imagem local homologada com as dependências de teste; nenhuma instalação automática é feita pelos agentes. Não confundir êxito de CI com homologação E2E no host.

A suíte do supervisor passa a executar análise AST + unittest dentro de Docker com **bind mount de código somente leitura**, sem rede, com tmpfs e `PYTHONDONTWRITEBYTECODE=1`, protegendo os arquivos da worktree contra alterações feitas durante os testes. 

## Indicador de produtividade por token (somente dados efetivamente observados)

```bash
bash scripts/nivon-autonomo.sh efficiency
```

O indicador informa tarefas finalizadas por 100 mil tokens de entrada+saída, separando Claude, Codex e total. Se **qualquer** tentativa no recorte não possuir consumo confiável, a taxa é `null` e aparece `comparability: incomplete` — não interpreta medição ausente como uso zero. O consumo anterior a um handoff permanece contabilizado. Cache indica reaproveitamento de contexto, não aumento de franquia nem economia de custo comprovada.

Para comparar versões, executar tarefas equivalentes antes/depois e analisar qualidade, retrabalho e conclusão. Sem log real das duas CLIs, não há estimativa de percentuais.


## Encerramento obrigatório da árvore de processos (atualizado em 23/10/2026)

O módulo `nivon.processos` inicia cada CLI em grupo/sessão de processos independente e aplica timeout por tarefa. Em Linux/macOS/WSL2, encerra o grupo inteiro com SIGTERM seguido de SIGKILL e verifica se ele continua acessível. Isso se aplica **inclusive quando o processo principal termina com código 0**, mas deixa descendentes em execução. Logs das CLIs são arquivos privados com criação exclusiva, para não sobrescrever evidências anteriores.

Se o supervisor **não conseguir confirmar** o encerramento da árvore, registra tarefa bloqueada e cria o arquivo `.nivon-local/STOP`, impedindo novas tarefas até revisão humana. A ordem STOP emitida imediatamente depois de um `start` é preservada pelo supervisor filho: somente um **novo comando explícito de início** a limpa antes de executar. O comando `stop` continua cooperativo e não mata de forma abrupta tarefas em andamento; estas são limitadas pelos timeouts.

**Atenção ao sistema operacional:** o mecanismo de confirmação de árvore de processos está homologado apenas no caminho POSIX. O `doctor` recusa piloto autônomo no **Windows nativo** até existir isolamento verificável para processos filhos. Em PCs Windows, usar WSL2 com Git, Python, Docker e ambas as CLIs dentro do Linux. Não habilitar modos sem sandbox para contornar esse bloqueio.

A CI testa encerramento real de subprocessos locais e simula STOP durante a inicialização; isso ainda não substitui o piloto noturno com as duas CLIs autenticadas. A CI também não confirma o consumo de tokens do provedor, que depende do host.

## Painel Dueto local

Os comandos `bash scripts/nivon-autonomo.sh dueto` e `bash scripts/nivon-autonomo.sh painel` consultam o ledger local e apresentam estado Claude/Codex, tarefas, transferências e consumo realmente observado. **Não iniciam modelos.** O HTML é uma fotografia local privada em `.nivon-local/painel-dueto.html` (0600), sem servidor, sem JavaScript nem logs/segredos. Consulte [DUETO_DESENVOLVIMENTO_NIVON.md](DUETO_DESENVOLVIMENTO_NIVON.md). A geração pode ocorrer de dia, mas o trabalho autônomo das CLIs continua restrito ao horário noturno.


## Pré-homologação de um comando, sem usar modelos

A integração com `main` está no PR #121. **Este procedimento é para o host local, não evidência de que Claude e Codex já foram autenticados nele.**

O supervisor prefere uma imagem reproduzível que inclui PyArrow, para que testes Parquet não sejam omitidos:

```bash
# Uma vez, no host, após instalar Docker e revisar a origem da imagem:
docker build -f infra/docker/Dockerfile.agentes -t nivon-agentes:test-py311 infra/docker

# No clone atualizado da branch da PR:
bash scripts/nivon-autonomo.sh preflight
```

O build é **ação explícita do operador**, pode baixar imagem base e wheel públicos e ocupar disco/rede; não é iniciado pelo supervisor nem incluído no comando noturno. O `preflight` verifica instalação, autenticação, flags e executa análise estrutural + suíte Python em Docker sem rede, sem escrita na worktree, sem chamadas a modelos. Falhas, testes omitidos ou falta de login impedem prontidão.

`doctor` aceita flags documentadas do Claude em versões compatíveis mesmo que o `--help` omita opções, conforme ressalva oficial. O Codex é verificado por `codex --help` e `codex exec --help`.

Depois de passar no preflight, à noite (Mato Grosso):

```bash
bash scripts/nivon-autonomo.sh night-status
bash scripts/nivon-autonomo.sh plan
bash scripts/nivon-autonomo.sh
bash scripts/nivon-autonomo.sh status
bash scripts/nivon-autonomo.sh painel
```

O comando autônomo é restrito a 20h–6h em America/Cuiaba, com até 8 tarefas e 120 minutos por ciclo. Ao final, revisar commits em `autonomo/integracao`. O supervisor repete o teste completo do Docker em seu preflight, mesmo quando iniciado diretamente, impedindo execuções com contêiner inadequado.

Ainda não há piloto real com ambas as assinaturas autenticadas. Segredos, arquivos privados e logs da assinatura não devem ser publicados no GitHub.
