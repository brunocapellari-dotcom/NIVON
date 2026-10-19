# NIVON — Mapa de Coletores e APIs (escopo integral)\n\n> **Atualização 19/10/2026 — Escopo nacional de line-up**: o inventário oficial é agora `config/lineup_escopo_nacional.v1.json`, com **35 portos organizados ANTAQ e 10 terminais/complexos privados candidatos**. A matriz `MARITIMO` foi ampliada, o catálogo mestre e as rotas técnicas passaram a conter **126 datasets** (45 line-ups) com `runtime_enabled=false`/`scheduled_enabled=false`. Isto **não** é 45 coletores ativos: portos e TUPs exigem identificação e homologação da fonte exata. O cadastro legado de 10 portos foi depreciado. Documento-base original abaixo mantém referências à versão anterior para rastreabilidade.\n\n

**Data-base:** 19/10/2026 · **Etapa:** desenvolvimento, sem go-live.

## Registro canônico — não criar planilhas paralelas

1. `config/fontes_nivon_master.v1.json` é o cadastro único de fornecedores, datasets, produtos, prioridades, periodicidades, maturidade e direitos.
2. `config/rotas_coleta.v1.json` é a extensão **1:1 dos 86 datasets** que identifica API/arquivo/página, URL específica apenas se comprovada, bloqueios e etapa necessária. Não duplica fonte/periodicidade/produto.
3. `config/matriz_produtos_indicadores.v1.json` é a matriz que liga cada commodity ou frente aos indicadores e seus datasets.
4. `src/nivon/rotas_coleta.py` valida identidade, bijeção 78/78, URL, permissões, backfill e não ativação de bases restritas. `src/nivon/catalogo_fontes.py` valida a fonte. `src/nivon/orquestrador_fontes.py` é dry-run, não coletor agendado.

**Limite de evidência:** um registro no catálogo não confirma API, scraping permitido, dados no banco ou periodicidade de atualização cumprida. O endpoint do produtor de dados e a licença sobre o próprio conteúdo são verificados individualmente.

## Estratégia de aquisição

**Ordem padrão:** API oficial com documentação → CSV/JSON/XLS estruturado oficial → página de catálogo e arquivo oficial HTML/PDF → exportação manual de painel autorizada → fonte restrita OFF.

Cada coletor, independente do formato, precisa:
- `source_id/dataset_id`, recurso específico (não apenas home), direito por consulta/coleta/armazenamento/transformação/publicação, hash e versão do parser;
- quatro datas (competência, referência, publicação, coleta) e null quando a fonte não informar alguma;
- unidade e granularidade explícitas (cidade/UF/região, produto/NCM, safra/ano civil, fluxo físico ou preço de mercado);
- histórico retrospectivo **até a data mais antiga tecnicamente acessível e permitida**, depois delta incremental, versionamento de edições, revisão e consulta as-of;
- classificação OBSERVADO / INFORMADO / ESTIMADO / PROJETADO / INFERIDO, nunca transformando previsão em realizado;
- schema, reconciliação, nulos, duplicação, controle de cobertura, hash, métricas de qualidade, backoff/rate limit, falha segura, observabilidade;
- armazenamento durável e backup/restauração testados para operação com notebook desligado;
- cadência associada à publicação efetiva, não à hora desejada pelo operador.

Todas as rotas estão `runtime_enabled=false` e `scheduled_enabled=false` até a homologação por dataset.

## 15 grupos: via de coleta e primeiro produto útil

| Grupo | Fontes / modalidade preferida | Primeira aplicação NIVON | Gate que resta |
|---|---|---|---|
| SAFRA | CONAB XLS, IBGE SIDRA API, USDA PSD | soja, milho, algodão, trigo, sorgo: produção, área, produtividade, safra | validar cada layout real, vintages e revisão |
| BALANCO | CONAB, USDA, ABIOVE | oferta, demanda, estoques e saldo exportável | conciliar fluxos e evitar dupla contagem |
| INDUSTRIA | ABIOVE relatórios, Sindirações, ANP, UNICA | esmagamento, farelo, ração, etanol, DDG, açúcar | coeficientes de rota, datas, direitos |
| PECUARIA | IBGE PPM/abate, consultorias sob licença | boi e bezerro, rebanho, abate, preços | não inferir preço licenciado de dados públicos ausentes |
| LOGISTICA | ANTT MDF-e dashboard, SIADE arquivos, CIOT, ONTL | MT→outras UFs, terminais, consumo potencial, TU/TKU | export legítimo, NCM parcial, transbordo ambíguo |
| PORTOS | ANTAQ movimentação CSV, 10 autoridades HTML/PDF, AIS opcional | porto→produto: programado, atracado, realizado | validar cada porto e não confundir AIS com carga |
| ENERGIA | ANP CSV semanal/mensal, BCB PTAX API, EIA | diesel S10/S500, diesel A/B, biodiesel, petróleo, paridade | revisão tributária/física, combustível correto, direitos |
| FERTILIZANTES | MDIC CSV NCM, ANDA relatórios, MAPA | importação, entrega, polos industriais, descargas | vigência NCM, origem/destino e unidades |
| COMEX | MDIC CSV bulk, Comex Stat, UN Comtrade API | soja/milho/algodão, farelo, fertilizantes, diesel | NCM x SH4/município e revisões |
| PRECOS | BCB OData; CEPEA/IMEA/B3/CME/ICE condicionados | cotações, mercado físico, Chicago, câmbio, bases | direitos de market data, fontes abertas alternativas |
| CLIMA | INMET, CPTEC, NOAA, ECMWF | observado, chuva, previsão, risco safra | grade espacial, cobertura e tipo de previsão |
| HIDRO | ANA SNIRH/hidrotelemetria | níveis e vazões de hidrovias/corredores | localização, interpolação e atualização |
| MACRO | Banco Central/SGS, EIA, WB/IMF | câmbio, juros, energia internacional, macrodrivers | série e unidade canônicas, frequência |
| GEO | MapBiomas, ZARC, cadastros oficiais | mudanças de área e aptidão/riscos agrícolas | licença geoespacial, versão de mapa, resolução |
| RADAR | comunicados oficiais, notícias autorizadas, Agroclima | briefing NIVON com notícias <=24h | timestamp verificado, direitos, deduplicação, WhatsApp apenas interface de envio |

Os 15 grupos são **cobertura do inventário existente**, não prova de que todas as perguntas econômicas já podem ser respondidas.

## Áreas para completar o escopo antes da homologação comercial

Comparar a matriz com os requisitos do NIVON em cada release. Foram identificados como candidatos a **datasets canônicos adicionais** (parcialmente cadastrados nos 86: armazenagem CONAB, comercialização IMEA, indústrias UNEM, energia EPE e códigos IBGE; validar o restante):
- **Armazenagem física:** CONAB Armazéns Cadastrados (capacidade estática por município; não igual a estoque disponível). Referência a examinar: `https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt`.
- **Comercialização da safra:** percentuais comercializados em MT e Brasil por produto/safra e versões; verificar fontes setoriais e direitos, não inventar posição remanescente.
- **Mapa de indústria e capacidade:** biorrefinarias de milho, usinas de esmagamento, beneficiadoras, fertilizantes e processamento industrial; distinguir capacidade autorizada, instalada e volume operado.
- **Combustíveis:** infraestrutura de distribuição/refino, importação, disponibilidade regional e transporte; preço de revenda não equivale a abastecimento físico.
- **Frete e infraestrutura:** malha e capacidade de terminais, rodovias, pedágios e fretes ANUNCIADOS por transportadoras sob interface independente WhatsApp AI; não apresentar divulgações como operações realizadas.
- **Mundo:** oferta/demanda de grandes origens/destinos e fluxo marítimo internacional por cobertura disponível; dados estatísticos não são line-up em tempo real.

Esses itens exigem resolução de identificador, fonte e dataset específico antes de serem incorporados formalmente ao catálogo. Não considerar o total de 78 como inventário final imutável.

## Ordem técnica de execução, com critérios de aceite

| Lote | Datasets e entregas | Critério para promover |
|---|---|---|
| **1 — Histórico real estruturado** | CONAB soja/milho e outras culturas, MAPA SIPEAGRO, ANP diesel, MDIC CSV, BCB PTAX | arquivo/endpoint oficial, direitos por operação, parser regressivo, histórico com hash e edição, resultado conciliado |
| **2 — Logística terrestre** | ANTT SIADE, MDF-e por exportação autorizada, terminais ferroviários, polos MAPA | matriz mensal com UF/município/mercadoria/NCM/cobertura, categoria ambígua, sem inferir consumo final |
| **3 — Indústria, demanda e fertilizantes** | ABIOVE, Sindirações, UNICA, ANP etanol, ANDA, MAPA | oferta x uso x estoque coerentes, co-produtos sem erro de massa e unidades explícitas |
| **4 — Operações marítimas** | 10 portos BR + ANTAQ + internacional quando disponível | cada fonte com 3 aquisições em datas distintas, identidade de escala, status físico x programação |
| **5 — Clima e macro** | INMET, NOAA, CPTEC, ANA, IBGE, USDA, PTAX/SGS e custos de transporte | série observada/projetada separada, as-of, baseline e controle de revisões |
| **6 — Radar e entrega** | notícias oficiais autorizadas e briefing próprio NIVON | notícia publicada <=24h, fonte comprovada, sem repetição, envio por contrato independente do WhatsApp AI |

**Não existe bloqueador humano para manter o desenvolvimento offline e testes de formatos públicos.** A ativação de serviços/credenciais, fontes privadas e recursos pagos ou persistência comercial exige gate específico.

## Comandos

```bash
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --prioridade P0
PYTHONPATH=src python -m nivon.rotas_coleta --grupo PORTOS
PYTHONPATH=src python -m unittest discover -s tests -v
```

Comandos somente de leitura; não habilitam agendamentos, não acessam rede e não geram custos externos.
