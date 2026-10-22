# NIVON — Codex e demais agentes

Leia \`README.md\` e \`.ai/skills/nivon-cooperative-dev.md\` antes de editar.

- Claude e Codex são **dois implementadores paralelos**. Não existe divisão obrigatória programador/auditor.
- Cada agente recebe tarefa e arquivos exclusivos, usa branch/worktree própria e registra SHA, testes e próximos passos.
- Reduza tokens: busca de símbolos antes da leitura; trechos pontuais em vez de arquivos inteiros; logs resumidos mantendo evidências integrais.
- Execute testes offline: \`python -m compileall -q src tests && PYTHONPATH=src python -m unittest discover -s tests -q\`.
- Dados sintéticos nunca são observações. Respeite direitos de CEPEA, IMEA e CONAB, e os campos de proveniência/frescor.
- Proibidos: receituário agronômico, bypass de autenticação, compras, APIs pagas, deploy, cron ou gravação externa não autorizados.
- Proceda sem permissões intermediárias para mudanças locais reversíveis dentro do escopo. Pare por credenciais, custos, alterações destrutivas ou risco material.
- Não efetue merge automático na main; registre bloqueios com precisão. Não tente contornar cotas dos provedores.
