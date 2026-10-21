# NIVON — auditoria estática das rotas e fontes

`src/nivon/auditoria_coletores.py` foi implementado sobre o inventário canônico; não cria outra planilha de fontes nem torna o notebook necessário para operação. Executa **sem rede** e em custo zero.

O relatório diferencia: direitos restritos, endpoint técnico ainda não comprovado, parser a desenvolver, código offline sem snapshot real e snapshot real testado sem gates operacionais. Conta os datasets por prioridade e grupo, sem fixar totais históricos (o inventário cresce). Inspeciona invariantes de permissões e fecha em erro se qualquer rota passar para coleta ou agendamento sem revisão do contrato.

Estado `SNAPSHOT_REAL_SEM_GATES_OPERACIONAIS` NÃO significa operação real: há ainda autorizações de uso por operação, histórico permitido, reconciliação, backup durável, testes de falhas e publicação.

Comandos: `PYTHONPATH=src python -m nivon.auditoria_coletores --resumo` ou `--prioridade P0` para próximos itens.

O código é auditoria documental, sem coletar, contratar, publicar, enviar WhatsApp ou realizar deploy.
