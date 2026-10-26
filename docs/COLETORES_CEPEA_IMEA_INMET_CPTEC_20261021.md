# NIVON — conectores CEPEA/IMEA, INMET, CPTEC e CEMADEN (21/10/2026)

Branch de integração sobre `integration/nivon-acessos-core-convergencia-20261021`. Os cinco blobs de drivers e testes de INMET, CPTEC e CEMADEN foram reaproveitados da PR #87 (`feat/meteo-publica-inmet-cptec-20261021`) por SHA, sem reimplementação.

## Importação CEPEA e IMEA (offline)
Não foi confirmada API pública oficial/licença de captura automática de indicadores. O novo `src/nivon/importacao_cotacoes_autorizadas.py` recebe *somente arquivos já fornecidos por via autorizada*, convertidos pelo operador para CSV UTF-8 separado por `;` com cabeçalho:

```text
serie_id;produto;localidade;competencia;referencia;preco;unidade
SOJA_SORRISO_MT;Soja;Sorriso - MT;2026-10;2026-10-20;125,50;BRL/SC60KG
```

**Exemplo sintético**, não cotação observada. Nenhum layout CEPEA/IMEA foi alegado. Dados reais exigem documentação externa de licença, proveniência e exportação, com uso **não comercial** conforme escopo NIVON.

Metadados da chamada: `fonte_id` CEPEA/IMEA, `fonte_url` em HTTPS oficial, `edicao_id`, `coletado_em` com timezone e datas `publicado_em`/`disponivel_em` quando comprovadas. O parser rejeita série/data duplicadas, datas contraditórias, unidades desconhecidas, CSV malformado, host inseguro e preços ambíguos. Aceita várias datas da mesma série em cada mês sem colisão de chave de edição. Preserva SHA do bruto e as quatro dimensões temporais em `ArmazemVintages`. Mesmo com datas declaradas, `disponibilidade_verificada=False`, sem acesso ao as-of, backtest, briefing ou publicação. Importação local opt-in idempotente e atômica por lote no SQLite; checksum do pacote detecta alterações acidentais entre normalização e persistência, mas não comprova autenticidade de origem.

## APIs aproveitadas
- INMET: `https://apitempo.inmet.gov.br/estacoes/T` ou `/M`, *catálogo de estações*, não dado meteorológico horário.
- CPTEC via BrasilAPI: `https://brasilapi.com.br/api/cptec/v1/clima/previsao/{codigo_cptec}/{dias}`, com janela 1–6 dias; não confundir código CPTEC com IBGE e previsão `PROJETADO` com observado.
- CEMADEN PED: `https://sws.cemaden.gov.br/PED/api/ui/swagger.json`. Leitura de acumulados recentes por município requer token autorizado, não configurado nesta integração.

**Nada disso está ativado para cron, banco em nuvem, publicação ou rede contínua.** Testes de transportes são sintéticos. HTTPS real, MIME, limites, frescor, licenças por operação e controles de runtime precisam homologação antes de habilitar.

## Evidências e prioridade
- IMEA: `https://www.imea.com.br/imea-site/indicadores`, portal de indicadores não equivale a contrato de API.
- CONAB: `https://portaldeinformacoes.conab.gov.br/`, reaproveitar parsers existentes; não contornar CAPTCHA em `https://sisdep.conab.gov.br/precosiagroweb/`.
- CEPEA: `https://www.cepea.esalq.usp.br/`, aguardar autorização para uso do arquivo/indicador.

Próximas ações: arquivos reais licenciados CEPEA/IMEA; confirmação de direito de armazenamento/derivação e horários de divulgação; resposta do IMEA sobre API; verificação HTTP das três APIs públicas em executor isolado; reconciliação de indicadores sem merge automático.
