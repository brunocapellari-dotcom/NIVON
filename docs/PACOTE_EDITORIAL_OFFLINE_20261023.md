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

## Execução integrada — 23/10/2026

- Novo módulo de preparação registra automaticamente um pacote completo
  aprovado em SQLite, sem expor remetente/callback/HTTP.
- O CLI permite verificar um pacote ou um **lote de até 200** com
  --lote. Bloqueios por item são comunicados sem interromper os demais.
- A interface de registro em lote isola rejeições de consentimento, prova,
  identidade, notícia vencida e direitos. Pacotes inválidos não marcam
  idempotência como processada; uma edição válida posterior com a mesma
  chave pode ser registrada. O envio continua bloqueado.
- Casos E2E executam de entrada editorial realista (fixtures) até
  preflight -> provas -> registry -> registro da edição -> outbox,
  inclusive segunda execução idempotente e CLI via subprocess.
- A última validação GitHub Actions será citada na PR #53, no commit
  exato do fechamento deste lote.

### Critérios que ainda impedem operação

Além de emissores e consentimentos reais, a publicação em canal exige
**validade temporal da própria edição na data efetiva da tentativa**,
independentemente da janela de notícias calculada no horário de geração.
O pipeline offline aceita edições históricas para testes e auditoria;
isso NÃO as torna atuais ou publicáveis. Antes de conectar transporte,
o gate de reserva terá que impor/confirmar data de corte e expiração
editorial com base em relógio e calendário confiáveis. Necessário
também testar envio externo autorizado em ambiente homologado e
backup/restauração de infraestrutura persistente.

## Leitura explícita de validade editorial

O preparador offline e o comando CLI agora expõem
vigencia.estado_temporal e vigencia.valido_ate_utc para cada dossiê,
inclusive no modo --lote. Os estados DENTRO_DO_PRAZO, EDICAO_FUTURA e
EDICAO_VENCIDA são diagnósticos do relógio atual e do limite derivado
da notícia mais antiga. Mesmo um status DENTRO_DO_PRAZO **não permite
envio**: envio_habilitado continua sempre false e faltam homologações.
O status PREVALIDADO_OFFLINE continua significando apenas que a edição
passou no preflight histórico, não que possa ser publicada hoje.
