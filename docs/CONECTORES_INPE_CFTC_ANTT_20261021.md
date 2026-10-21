# NIVON — conectores INPE, CFTC e ANTT (21/10/2026)

## O que esta entrega executa

1. INPE Programa Queimadas: consulta pontual de CSV diário brasileiro no diretório oficial `dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/`. Parser confere data UTC da detecção, posição geográfica, satélite, bioma, FRP e índice de risco quando presentes. Um foco de satélite não é um incêndio individual e não equivale ao ROI do SISFOGO. Arquivos publicados durante o dia podem ser parciais; o programa não promete consolidação definitiva.
2. CFTC Commitments of Traders: consulta JSON Socrata do dataset oficial `72hh-3qpy` (Disaggregated Futures Only), recorte por data exata e mercado permitido (soja, milho, trigo, óleo, farelo, algodão). Normalizador mantém contratos e posições, sem inventar data/hora de publicação. Dados são posições semanais, NÃO preços de CBOT e NÃO antecipam relatórios.
3. ANTT: consulta de metadados CKAN no catálogo aberto `dados.antt.gov.br/api/3/action/package_search`, limitada a uma página pequena. Retorna apenas links *candidatos* oficiais para validação posterior, não volume de tráfego já coletado nem frete efetivamente negociado.

Módulos: `src/nivon/cftc_cot_publico.py`, `src/nivon/inpe_queimadas_csv.py`, `src/nivon/consultas_fontes_publicas.py`, `scripts/smoke_inpe_cftc_antt.py`.

## Chamadas pontuais que o operador pode executar em ambiente com rede

```bash
PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte inpe --data 2026-10-20 --executar
PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte cftc --data 2026-10-20 --mercado SOYBEANS --executar
PYTHONPATH=src python scripts/smoke_inpe_cftc_antt.py --fonte antt --executar
```

Sem `--executar`, nenhuma rede é consultada. Cada chamada é uma única requisição HTTPS, com host/path whitelist, status 200, MIME, limite de bytes, bloqueio de redirect, 20 s de timeout, SHA256 e horário de coleta UTC. Sem tentativa automática repetida, sem varredura em massa e sem custos contratados.

**Atenção a CFTC:** a data de posição (terça-feira) é diferente da data de publicação (normalmente sexta-feira). A ausência de campo de publicação no JSON implica `publicacao=null`; backtest *as-of* não pode usar posições antes da divulgação pública confirmada. Só será possível gerar motor de tendência após normalizar vintages e confirmar calendário de divulgação.

**Atenção a INPE:** documento CSV diário pode ter alteração durante o próprio dia e a coluna do satélite informa sensor. Área queimada, número de eventos e prejuízo não podem ser inferidos de contagem bruta de focos. Evitar somar detecções de satélites distintos como incêndios independentes.

**Atenção a ANTT:** CKAN apresenta metadados e arquivos listados, não garante granularidade de veículos pesados, origem-destino ou frete; cada recurso deverá ser homologado individualmente antes da persistência.

## Pesquisa complementar — fontes que não exigem compra de dados

- **ANTT volume de tráfego nas praças e contadores SATs:** https://dados.antt.gov.br/dataset — formatos CSV/JSON disponíveis em conjuntos de rodovias concessionadas. Confirmar período, denominador, revisões e direitos por recurso.
- **Banco Central Expectativas de Mercado / Focus:** https://dadosabertos.bcb.gov.br/dataset/expectativas-mercado — OData pública de estatísticas por indicador e horizonte; já existe cadastro agregado BCB_SGS_FOCUS, carece de subcontrato e coleta histórica sem *look-ahead*.
- **ANP preços de combustíveis:** https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis — CSVs semanais e mensais com histórico longo e atualização observada em outubro/2026; aproveitar `anp_diesel.py` e `anp_manifesto.py` existentes.
- **CFTC arquivos históricos compactados:** https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm — backfill oficial por ano, mais eficiente que chamadas de milhares de páginas.
- **INPE histórico anual/mensal e dados por 10 min:** https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/ — para carga em lote/indicadores, diferenciar arquivo provisório, sensor e satélite referência.
- **USDA FAS ESR / PSD / GATS:** https://apps.fas.usda.gov/opendatawebv2/ — APIs com **chave gratuita api.data.gov**, que deve ficar fora do repositório. Não é necessário contratar serviço pago, mas o usuário precisa fornecer/configurar sua própria chave se não existir credencial conectada.
- **USDA NASS Quick Stats:** exige chave gratuita específica e tem grande histórico agrícola dos EUA; serviço paralelo ao FAS, com credenciais independentes.

## Estado auditável

Catálogo mantém coletas e agendamento OFF (sem licença, persistência e smoke real). Código de consulta existente **não é comprovação de resposta operacional**. O acesso a arquivos CSV/JSON direto não pôde ser executado a partir do ambiente de pesquisa por falha de DNS, mas índices oficiais e documentação pública foram verificados. Apenas testes determinísticos via GitHub Actions foram planejados para a PR.

Acesso à infraestrutura de produção, configuração de chaves gratuitas e autorização por operação seguem gates separados; não enviar valores reais a git ou relatórios de produção antes de validá-los.
