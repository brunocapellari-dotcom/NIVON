# BCB PTAX — do histórico ao briefing NIVON

Data-base: 20/10/2026. Estado: integração de código testada em fixtures; não é coleta real habilitada.

## O que foi conectado

- Normalização offline da OData PTAX: src/nivon/bcb_ptax.py.
- Ingestão autorizada/versionada em SQLite: src/nivon/pipeline_api_dados.py.
- Conversão do histórico persistido em indicador CAMBIO:
  src/nivon/indicador_ptax.py.
- Inclusão opcional no pacote de briefing:
  compor_pacote_historico(db_mercados=...,incluir_ptax_usd=True).
- CLI offline: --db-mercados /volume/mercado.sqlite --incluir-ptax-usd.
- Integração Hermes read-only: briefing.preview com incluir_ptax_usd=true,
  desde que o adaptador tenha banco mercados injetado.
- Observabilidade local: PTAX_SEM_COLETA_REAL, PTAX_COLETA_ATRASADA,
  PTAX_COLETA_FUTURA, PTAX_BANCO_INVALIDO.

## Governança dos números

Os boletins PTAX preservam compra e venda, moeda USD, horário de referência,
tipo do boletim (Fechamento quando identificado), hash e data de coleta.

A interface só publica dados classificados REAL_AUTORIZADO, com direitos
LEITURA e PUBLICACAO_DERIVADA aprovados pela governança da fonte.
Snapshots SINTETICO não entram no briefing, mesmo quando o mapa de fontes
está marcado como aprovado. Na falta de observação, o bloco é BLOQUEADO,
não preenchido com zero nem valores presumidos.

Não confundir PTAX com dólar comercial no mercado à vista ou cotação
indicativa de outra fonte. Não tratar horário de referência como prova da
data exata de publicação: a publicação é DESCONHECIDA neste pipeline,
logo dados PTAX persistidos aqui não servem para backtest publication-as-of.
O monitor de PTAX mede tempo da CAPTURA, não a validade intrínseca do
boletim nem disponibilidade do endpoint externo.

Quando existem registros conflitantes para o mesmo horário de referência,
a publicação é bloqueada até reconciliação explícita. A regra de frescor
padrão de câmbio é 168h e deverá ser ajustada para dias úteis/feriados
no processo de homologação com dados reais.

## O que NÃO foi ativado

Nenhuma API BCB foi chamada nesta etapa, nem contas ou servidores externos.
O catálogo oficial da plataforma permanece com gates de coleta e direitos
desativados, até homologação. Nenhum WhatsApp foi enviado, nenhuma quota,
fatura ou deploy foi ativado. O operador real ainda deve estabelecer
agendamento, snapshot bruto autorizado, SLA, recuperação, templates e custos.
