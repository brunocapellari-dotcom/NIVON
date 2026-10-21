# PTAX do Banco Central — Integração oficial NIVON

**Estado 21/10/2026:** USD e EUR com coleta real validada em GitHub Actions, em SQLite temporário. Sem armazenamento permanente, sem integração à base canônica, sem série histórica completa baixada.

## Evidências

- Página canônica do conjunto: https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios
- OData da fonte: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao
- Documentação técnica do BCB para todos os boletins: https://www.bcb.gov.br/conteudo/dadosabertos/BCBDepin/gnastportal-dados-abertostaxas-de-cambio---todos-os-boletins-diarios.pdf
- Licença do catálogo: Open Data Commons Open Database License (ODbL); atribuição e condições de compartilhamento de base derivada devem ser preservadas.
- Widget Notícias Agrícolas: ID 232 é somente uma referência de apresentação. O coletor usa diretamente o BCB.

## Cobertura de API e semântica

- **USD**: \`CotacaoDolarPeriodo\`, com compra, venda e horário de cotação. Este endpoint **NÃO** fornece \`tipoBoletim\`; o valor é rotulado \`COTACAO_DOLAR_DIARIA\` para não inventar categoria.
- **EUR**: \`CotacaoMoedaPeriodo\`, com quatro possíveis tipos de boletim (Abertura, Intermediário, Fechamento Interbancário, Fechamento); preservar todos, sem somar ou misturar amostras.
- Datas da consulta OData: MM-DD-AAAA; \`data_referencia\` é a data da cotação; \`data_hora_cotacao_origem\` mantém o timestamp original, sem atribuir um fuso não publicado.
- A API **não oferece hora de publicação** nesses recursos; \`data_publicacao = NULL\`. \`data_coleta\` é timestamp UTC real, não publicação da fonte.
- \`competencia\` é AAAA-MM derivada da data da cotação. \`cotacaoCompra\` e \`cotacaoVenda\` são preços distintos, em BRL/USD ou BRL/EUR.
- Intervalos em páginas de 31 dias, \`$top=5000\`, rejeição de resposta paginada ou parcial desconhecida.
- Idempotência por chave natural + hash dos preços; valores corrigidos preservados como versões. A primeira execução incremental coleta 31 dias; execuções com banco persistente consultam desde três dias anteriores à última referência e avançam em blocos até 180 dias.
- Histórico oficial indicado no catálogo: dólar desde 28/11/1984, euro desde 02/01/2002. A rotina aceita períodos históricos informados em linha de comando, mas não alega que eles já foram baixados.

## Operação manual

\`\`\`sh
python -m unittest discover -s tests -v
python -m nivon.ptax_bcb --banco /caminho/privado/ptax.sqlite3 --moeda AMBAS
python -m nivon.ptax_bcb --banco /caminho/privado/ptax.sqlite3 --moeda USD --inicio 2026-01-01 --fim 2026-10-20
\`\`\`

Para carga maior que 366 dias, executar conscientemente com \`--permitir-periodo-longo\`, verificando antes limites/termos da API. Não rodar backfill intensivo sem planejamento de taxa e controle de integridade.

## Automação e limites

- \`.github/workflows/ptax-integracao.yml\`: teste real de integração na branch, grava SQLite apenas temporário.
- \`.github/workflows/ptax-monitoramento.yml\`: **preparado** para programação diária após merge na **branch padrão** (01:30 UTC terça a sábado, próximo do fim do dia útil brasileiro anterior); gera resumo agregado com idade desde a referência e artefato de 30 dias.
- Workflow diário **não mantém série histórica contínua** entre execuções; cada execução cria SQLite temporário de ~31 dias. O artefato contém somente resumo, e não dados de terceiros.
- Para produção: configurar banco persistente privado e logs independentes do ciclo de vida do GitHub Actions, proteção contra atrasos, feriados, falhas, auditoria e retenção.
- Datas de referência envelhecidas devem ser marcadas \`SOURCE_LAG\`, nunca apresentadas como observação do dia.

## Fontes a seguir: soja e milho

- IMEA: verificar termos, inscrição/licença, histórico, periodicidade, acesso direto; evitar deduzir permissão de incorporação visual.
- CEPEA: verificar licença e termos específicos para uso não comercial e armazenamento estruturado; acesso técnico de bibliotecas de terceiros não é concessão de direitos.
- \`agrobr\` (https://github.com/bruno-portfolio/agrobr) é candidato de interoperabilidade para estudar, não fonte de autorização nem coletor habilitado.
- B3/CME/ICE e agregadores: licenciar por tipo de dado e operação antes de ingestão.
