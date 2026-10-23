# NIVON — Fontes de line-up, atualização 22/10/2026

Estado: coletores novos são parsers offline; coleta recorrente, banco, integração AIS real e homologação ainda pendentes.

| Local | Fonte | Política |
| --- | --- | --- |
| Santarém | CDP | Dados sujeitos a divergências; exigir reconciliação com AIS/terminais |
| Vila do Conde | CDP/SCAP | Reconciliar; excluir registros-placeholder e checar defasagem |
| Itacoatiara, porto público | Autoridade portuária | Identificar URL de line-up e validar atualização |
| Itacoatiara, terminal Amaggi/Hermasa | AIS próprio NIVON | Inferir presença na geocerca auditada; não inferir carga ou tonelagem sem fontes adicionais |
| Suape | Movimento Diário de Navios | Parser HTML offline criado; validar tabela real e dados históricos |
| Imbituba | Programação de Navios | Parser HTML offline criado; validar tabela real |
| Ponta da Madeira | Vale GPV | Importador CSV somente com acesso autorizado; não automatizar login sem permissão |

Fontes: https://www.suape.pe.gov.br/pt/operacoes/porto-em-tempo-real/movimento-diario-de-navios-novo-rest ; https://portodeimbituba.com.br/ ; https://vale.com/pt/logistica ; https://www.cdp.com.br/companhia-docas-do-para/programacao-de-navios/

Próximos passos: implementar coleta HTTPS autorizada, snapshot com hash, persistência operacional, reconstrução de escalas por IMO/DUV, validação AIS/terminal e detecção de divergências, evitando tratar programação como realizado. Separar Ponta da Madeira de Itaqui. Dados e credenciais de terceiros não entram no GitHub público.
