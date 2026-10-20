# Mercado financeiro e fertilizantes — contratos de uso NIVON

Data de elaboração: 20/10/2026. Implementado em branch de PR;
testado apenas com fixtures. NENHUM market data real está homologado aqui.

## Cotações externas para o briefing

Arquivos:
- `src/nivon/cotacoes_externas.py` — valida campos de futuro ou preço físico,
  direito de redistribuição, moeda, unidade e contrato/vencimento.
- `src/nivon/cotacoes_briefing.py` — mantém hora e fuso, origem HTTPS oficial
  por fonte, SHA-256 DECLARADO, horário de referência e coleta e janela de frescor.
- `src/nivon/indicadores_historicos.py` — compõe os indicadores homologáveis.
- `src/nivon/ensaio_vertical.py` — recebe arquivo separado
  `--licencas-mercados`, não realiza HTTP e não transmite mensagens.
- `src/nivon/hermes_adapter.py` — dados de cotações podem ser submetidos
  pelo cliente, mas licenças só são aceitas injetadas pelo operador confiável.

Mercados admitidos no contrato técnico inicial: CME, ICE, B3, CEPEA, IMEA,
sem afirmar que seus direitos de republicação já estejam negociados.
Suporta USC/BU (centavos de dólar/bushel) e outras unidades declaradas;
a especificação do contrato não substitui verificação de lote e unidade.

A verificação de hash hexadecimal na ponte NÃO substitui conferência dos
bytes originais. Para operar comercialmente, um coletor autorizado deverá
obter bytes da fonte, recalcular o hash e preservar a cópia e a evidência
de licença por operação com renovação e auditoria. Um item que indique
`documento_sha256` sem prova externa é apenas uma DECLARAÇÃO.

Se faltar licença de redistribuição, referência temporal, unidade correta,
contrato, host oficial ou integridade documentada, bloquear o conjunto
solicitado. Não usar valores substitutos nem marcar o fechamento anterior
como negociação intradiária. Fixar referência temporal em UTC/fuso explícito.

A autorização documental de mercado aqui injetada é um contrato DE TESTE:
o código não confere assinaturas de licença de CME, ICE, CEPEA ou IMEA.
O executor de produção deve validar autorizações oficiais e sua validade
antes de permitir `PUBLICACAO_DERIVADA`/`REDISTRIBUICAO`.

## MDIC / fertilizantes: somente consulta analítica

Arquivos:
- `src/nivon/mdic_stream.py` lê CSV anual já adquirido por meio autorizado
  e agrega NCM/ano/mês/UF fiscal.
- `src/nivon/ingestao_mdic.py` guarda os agregados e vintages de coleta.
- `src/nivon/mdic_fertilizantes_asof.py` calcula volume em toneladas,
  FOB em dólares e FOB unitário USD/t sem inferir preço local.
- `src/nivon/hermes_adapter.py` permite consulta somente leitura em
  `fertilizantes.importacao.read`, com NCM/UF/mês/ano e relógio as-of.

Resultados possuem `status=ANALISE_MDIC_NAO_HOMOLOGADA`,
`publicavel=false` e `enviar_whatsapp=false`.
O campo UF é FISCAL; não identifica porto ou origem/consumo da mercadoria.
A inexistência de linhas em um recorte não é volume zero.
FOB unitário calculado não corresponde a CFR/CIF, varejo, preço spot
ou cotação de negociação. Data exata de publicação MDIC não verificada,
portanto a análise é as-of COLETA, não as-of PUBLICAÇÃO.

Para promover um indicador MDIC, precisa de verificação de total contra
fonte oficial e suas retificações, licenças, data de publicação,
cobertura dos NCMs, critérios de agregação, reconciliação por período,
controle de unidades e revisão editorial independente.

## Barreiras para automatização

- Executor autenticado, seguro e observável implantado em nuvem;
  testes de contrato Hermes não provam implantação.
- Fonte e licença reais auditadas para cada conjunto de dados.
- Snapshot bruto/arquivo de origem imutável, SHA calculado do conteúdo,
  log de aquisição com data e reprocessamento determinístico.
- Backtesting quantitativo somente quando existem vintages verdadeiras.
- Geração do briefing completo com CBOT, câmbio, mercado físico,
  pecuária, energia, fertilizantes, fretes, logística e notícias <=24h
  conforme disponibilidade/contrato aprovado.
- Envio automático de WhatsApp exige opt-in, template/preço aprovados,
  confirmação de entrega e monitoramento/retentativa controlada.

Este PR não faz deploy, não cria contas, não consulta fonte paga,
não ativa web scraping nem realiza transmissão. Testes são sintéticos.
