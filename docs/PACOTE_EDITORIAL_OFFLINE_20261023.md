# Fluxo offline do pacote editorial NIVON

A função registrar_pacote_offline vincula preflight editorial, template candidato, assinatura da edição, cinco provas independentes, registro de confiança local e outbox. A operação nunca envia mensagens e não recebe callback.

Fases: preflight de notícias, cotações e fretes -> criação de template offline -> verificação de documento e comprovantes -> verificação de registry sob lock SQLite -> registro idempotente de edição -> autorização sob lock separado. Uma revogação entre as fases bloqueia a autorização. Uma edição parcialmente registrada continua sem permissão de despacho.

Comando de verificação somente leitura:
PYTHONPATH=src python scripts/nivon_preparar_pacote.py pacote.json

O pacote JSON possui: edicao, gerado_em, noticias, cotacoes, fretes, destinatario, nome_template, resumo_template, url_briefing, documento, assinatura, comprovantes. A saída omite número, texto, assinaturas e provas brutas. A CLI não registra nem transmite.

A aprovação depende de emissores homologados fora da aplicação, direitos, consentimento e chaves segregadas. Os testes usam dados sintéticos e não autorizam publicação, deploy, cron nem integração Meta.

## Processamento de lotes, sem comandos por edição

As funções avaliar_lote_offline e registrar_lote_offline processam até 200
edições por chamada. Dados inválidos e repetidos não impedem a análise das
outras edições. O resultado retorna totais, posição no lote e estados
sanitizados; não contém telefone, texto ou provas brutas. Falhas de SQLite
não são convertidas em sucesso e continuam exigindo intervenção operacional.

O CLI de avaliação aceita: PYTHONPATH=src python
scripts/nivon_preparar_pacote.py lote.json --lote

Esse comando apenas lê um JSON contendo lista de pacotes e valida os
preflights. Não existe opção de registrar ou enviar na CLI. Para registrar,
o chamador interno precisa do registry confiável e de chaves externas.
Lote não implica distribuição, nem considera dados antigos atuais.
