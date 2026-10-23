# Fluxo offline do pacote editorial NIVON

A função registrar_pacote_offline vincula preflight editorial, template candidato, assinatura da edição, cinco provas independentes, registro de confiança local e outbox. A operação nunca envia mensagens e não recebe callback.

Fases: preflight de notícias, cotações e fretes -> criação de template offline -> verificação de documento e comprovantes -> verificação de registry sob lock SQLite -> registro idempotente de edição -> autorização sob lock separado. Uma revogação entre as fases bloqueia a autorização. Uma edição parcialmente registrada continua sem permissão de despacho.

Comando de verificação somente leitura:
PYTHONPATH=src python scripts/nivon_preparar_pacote.py pacote.json

O pacote JSON possui: edicao, gerado_em, noticias, cotacoes, fretes, destinatario, nome_template, resumo_template, url_briefing, documento, assinatura, comprovantes. A saída omite número, texto, assinaturas e provas brutas. A CLI não registra nem transmite.

A aprovação depende de emissores homologados fora da aplicação, direitos, consentimento e chaves segregadas. Os testes usam dados sintéticos e não autorizam publicação, deploy, cron nem integração Meta.
