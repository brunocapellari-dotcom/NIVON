---
name: nivon-autonomo
description: Inicia a produção autônoma e cooperativa do NIVON com Claude Code e Codex, sem ativar nuvem ou custos novos.
disable-model-invocation: true
argument-hint: "[minutos] [numero-de-tarefas]"
---

# NIVON — produção autônoma

Quando invocada pelo usuário com \`/nivon-autonomo\`, esta skill deve executar **uma única vez** a sequência abaixo, sem construir ciclos próprios em mensagens da IA.

1. Ler \`AGENTS.md\` e \`docs/COOPERACAO_CLAUDE_CODE_CODEX.md\`. Informar caso o checkout esteja sujo, CLIs não estejam instaladas ou autenticadas.
2. Adicionar tarefas do manifesto ao ledger somente se ainda não existirem:
   \`PYTHONPATH=src python -m nivon.cooperacao seed docs/COOPERACAO_TAREFAS.json\`
3. Chamar \`PYTHONPATH=src python -m nivon.autonomia start --minutes 120 --max-tasks 8 --per-task 15\` para iniciar o supervisor **local**.
4. Responder com instruções curtas:
   \`PYTHONPATH=src python -m nivon.autonomia status\` e
   \`PYTHONPATH=src python -m nivon.autonomia stop\`.
5. Parar. Não abrir loops de mensagens, não usar bypass de permissões, não instalar pacotes nem ativar serviços externos.

Caso o usuário solicite outros limites, aceitar somente 1–480 minutos, 1–30 tarefas e 2–60 minutos por tarefa. Se a CLI não autorizar o comando local, não alterar configurações de segurança para contorná-la. O operador pode adicionar permissão restrita para esse comando após revisar sua implementação.

Regras: Claude e Codex são ambos programadores, em worktrees separados; cada tarefa é testada; merges e deploys são proibidos; somente branch local. Um supervisor externo precisa permanecer em host ligado e autenticado; esta skill não transforma a conversa em execução permanente.
