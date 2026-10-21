# NIVON: Hermes ProjectAdapter + backtesting por vintages

Data: 20/10/2026. Estado: código e testes no PR #3, não homologado para produção.

## Integração de IA
Arquivo: src/nivon/hermes_adapter.py.

Este adaptador implementa a interface assíncrona do contrato
hermes.contracts.ProjectAdapter, no repositório Hermes-AI-Platform,
sem presumir que o runtime Hermes esteja instalado ou implantado.

Capacidades de consulta:
- safra.progress.read: percentuais CONAB por safra/cultura/UF e edição histórica.
- portos.lineup.read: somente navios programados, sem afirmar realizado.
- briefing.preview: consolidado condicionado a direitos, frescor e auditoria.
- health/status/capabilities/search/alerts: metadados de estado read-only.

O método execute nega qualquer ação: não compra, envia WhatsApp,
altera licença, implanta serviços, modifica registros canônicos ou executa SQL.
Todas as consultas exigem um autorizador externo que valide a identidade
e o escopo; o adaptador NÃO cria tokens, não autentica um serviço remoto
e não configura um modelo generativo.

O mapa de direitos é copiado na criação do adaptador e os argumentos
de consulta são filtrados por chaves, tamanhos e tipos JSON. O backend
continua sendo determinístico, sem confiar em instruções de fontes externas.

## Avaliação de modelos sem look-ahead
Arquivo: src/nivon/avaliacao_vintages.py.

O avaliador recebe competências mensais, valor observado, fonte,
evidência e datas de publicação e coleta.
Reconstrói, para cada origem, apenas as vintages já publicadas E
coletadas até aquela data. Exige histórico contínuo e que o mês previsto
comece após a origem; mede o alvo somente em data posterior ao mês.

Calcula MAE do modelo e do benchmark sazonal do mesmo mês no ano
anterior. Bloqueia vazamento temporal, revisão futura, duplicidade,
fonte mista, atraso de divulgação e observação não finita.

Mesmo se superar o benchmark, o resultado permanece
VALIDACAO_VINTAGE_EXECUTADA_NAO_HOMOLOGADA.
publicar_previsao permanece false até homologação independente, com
dados reais, licença aplicável, múltiplas safras e incerteza documentada.

Bibliotecas StatsForecast, Pandas, agrobr, DuckDB, Polars, Pydantic e
pdfplumber são extras opcionais. Integração instalável não equivale
a coleta autorizada, previsão validada ou operação real em nuvem.

## Critérios restantes
1. Hermes: runtime, identidade OIDC, armazenamento e telemetria reais.
2. CONAB: histórico retrospectivo, autorização por operação, hashes e backup.
3. Portos: 3 capturas reais por porto, reconciliação e validação do layout.
4. Mercados: licença de CBOT/ICE, cotações, direitos de publicação.
5. Modelos: backtests em vintages de dados reais, validação empírica e auditoria.
6. Briefing: fontes completas, janela de notícias de 24h, auditoria e envio
   pela Meta com custo e template aprovados.
7. Infraestrutura: volume persistente, restore testado, alertas e logs.

Execução de testes sem dados reais:
PYTHONPATH=src python -m unittest discover -s tests -v

Esta entrega não autoriza merge, deploy, custo ou envio WhatsApp.
