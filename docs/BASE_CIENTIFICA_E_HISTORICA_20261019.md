# NIVON — Catálogo histórico-científico e motores preditivos (19/10/2026)

**Escopo:** agricultura, pecuária, hidrologia, meteorologia, mercados/bolsas e impactos cruzados. **Status:** pesquisa, cadastro e planejamento de homologação; SEM coleta recorrente, SEM licença presumida, SEM deploy. Base de trabalho: branch `feat/agrobr-portos-motores-agentes-20261019` no commit `3329bbcfda4aadf4f08ea77b64d2abdffe292157`.

## Integração real ao Nivon

- `config/fontes_nivon_master.v1.json` continua **única fonte canônica** de fontes/datasets, com 96 → 100 fontes e 131 → 138 datasets.
- `config/rotas_coleta.v1.json` continua fonte única de localização técnica, controles de licença e implementação. 138 rotas, **todas desativadas**.
- `config/matriz_produtos_indicadores.v1.json` associa as novas bases aos sistemas que as consumirão.
- `config/motores_inteligencia.v1.json` espelha dependências da matriz sem declarar homologação.
- `config/catalogo_tecnico_historico.v1.json` registra **metadados de pesquisa/evidência** por dataset já canônico; não duplica cadastro operacional.
- `config/bibliotecas_cientificas.v1.json` registra código do AgroLog e bibliotecas externas com licença/decisão, sem instalação automática.

## Bases históricas prioritárias verificadas

| Dataset NIVON | Histórico comprovado ou condicionante | Tipo de evidência | Uso científico |
|---|---|---|---|
| NASA_POWER_AGRO_DAILY | Diário desde 1981, grade original por parâmetro | modelo/reanálise | baseline regional clima e radiação |
| COPERNICUS_ERA5_LAND | 1950+, horário, 0,1° | reanálise | histórico coerente do clima/solo |
| UCSB_CHIRPS_V3 | 1981+, chuva 0,05°, prévia e final | satélite+estações | seca, chuva e risco por região |
| NOAA_ENSO_RONI | 1950+, sazonal móvel | índice climático | ENSO e anos análogos; não misturar RONI e ONI |
| USDA_WASDE_RELEASE_VINTAGES | edições desde 1973; CSV consolidado 2010+ | estimativas e revisões | erro de previsão em vintage real |
| MDIC_COMEX_NCM (existente) | 1997+, mensal por NCM; NBM 1989-96 separado | comércio exterior reportado | demanda/fluxos e balanços |
| ANA_HIDRO (existente) | varia por estação; exige solicitação de API | cota/vazão observadas/adotadas | estações e hidrologia por bacia |
| IBGE_PAM / IBGE_PPM (existentes) | por tabela, variável, município e revisão | estatística oficial | agricultura, rebanho e produção |
| CFTC_COT_WEEKLY | histórico varia por tipo de relatório | posições reportadas | posicionamento especulativo/comercial, não preço |
| CME_FUTUROS / B3_FUTUROS (existentes) | por contrato/dia, direitos restritos | negociação/ajuste | curva futura, spreads, basis; não automatizar sem licença |

**Outras fontes já canônicas preservadas**: CONAB semanal e séries/armazenagem, INMET, CPTEC/MERGE, USDA PSD/NASS, CEPEA/IMEA, MAPA, FAO, ANP, World Bank, CFTC agora cadastrado; sem duplicar IDs existentes.

### Restrições encontradas e documentadas

1. ANA HidroWebService possui Swagger com séries, mas **o acesso automatizado é sujeito a solicitação de credenciais à ANA** (https://www.snirh.gov.br/hidroweb/acesso-api). Não criar chaves nem contornar autenticação.
2. B3 proíbe explicitamente **coleta automatizada, incluindo IA**, na página de pesquisa por pregão (https://b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/boletins-diarios/pesquisa-por-pregao/pesquisa-por-pregao/). CME requer tratamento de licença de market data/histórico/redistribuição.
3. CHIRPS **preliminary/final**, CONAB e USDA/WASDE **vintages**, INMET estação e ERA5 grade/reanálise **não são sinônimos**.
4. O software open source não transfere direito de acessar, armazenar ou redistribuir dados externos. Verificar licença por biblioteca, dependência transitiva e finalidade comercial.

## Núcleo matemático obrigatório — não admitir números sem sentido

### 1. Identidades físicas e unidades

- **Produção agrícola**: produção (t) = área colhida (ha) × produtividade (kg/ha) / 1000. Tolerância **derivada do arredondamento e precisão das fontes**, não tolerância arbitrária universal.
- **Oferta/uso**: estoque inicial + produção + importações = consumo interno + exportação + perdas + estoque final + ajuste estatístico **explícito e auditável**. Não corrigir erro escondendo-o em consumo.
- **Animal**: peso carcaça (kg) = peso vivo (kg) × rendimento, com base e definição equivalentes. Não somar cabeças, kg vivo, cortes e carcaça.
- **Água**: armazenamento final = armazenamento inicial + precipitação − evapotranspiração real − escoamento/percolação; respeitar limites físicos e unidades. ETo (FAO-56) e Kc por cultura/fase, nunca inventados.
- **Energia e preço**: futures US¢/lb, USD/bu, USD/t, R$/sc60kg, R$/arroba exigem dicionário de contratos, densidades, especificação e conversores auditados. Preço futuro ≠ preço produtor.
- **Hidro**: nível observado em régua (cm) ≠ profundidade/canal/carga transportável. Vazão e cota dependem de curva-chave local, batimetria e datum.

### 2. Regras estatísticas contra previsões enganosas

- Dados **as-of**: usar apenas informações que existiam na data de decisão; armazenar competência, referência, publicação, coleta e, quando disponível, instante de liberação efetiva.
- Backtest walk-forward, folds por **safra, geografia e regime**, sem treino no futuro, sem vazamento por revisão do histórico ou normalização ajustada no conjunto de teste.
- Comparar com baselines de última safra, sazonal ingênuo, média histórica e modelos científicos simples; medir MAE, RMSE, MASE/sMAPE onde adequados; evitar MAPE em série zero/próxima de zero.
- Previsão probabilística: cobertura empírica de intervalos, pinball/CRPS e Brier para eventos quando aplicável, calibração e verificação da frequência real.
- Testar resíduos, sazonalidade, quebras estruturais, multicolinearidade, tamanhos amostrais, agregação regional, dependência espacial e mudanças de fonte.
- Sob desempenho inferior aos baselines, evidência insuficiente ou dados vencidos, **degradar para cenário não homologado**, não publicar como previsão confiável.
- Toda previsão terá unidade, fonte, vintage, horizonte, faixa de incerteza, hipótese e limite de interpretação. Não usar o LLM para inventar parâmetro, elasticidade ou probabilidade.

### 3. Especificidade dos motores

| Motor | Teoria/método necessário | Prova quantitativa |
|---|---|---|
| Agricultura | balanço hídrico, graus-dia, fenologia, FAO AquaCrop/DSSAT quando aplicável, regressão hierárquica e yield-forecast | backtest por município/UF/safra; predição física plausível |
| Pecuária | estrutura por coortes, ciclo, reprodução, ganho de peso, abate, alimentação, preços e elasticidade | conservações de rebanho, pesos, defasagem biológica e margem por sistema |
| Meteorologia | análise espacial, correção de viés, ensambles, verificação de precipitação/temperatura, anos análogos | skill por horizonte/região/estação e cobertura probabilística |
| Hidrologia | curva-chave, balanço hídrico de bacia, chuva-vazão, extremos e hidrogramas | NSE/KGE + viés/erro por estação e condição; não declarar navegabilidade |
| Bolsas | especificação do contrato, rolagem, term structure, basis, carry, hedge, volatilidade, regimes e risco | backtest por regime/contrato, custos de transação, janela as-of; direitos resolvidos |

**Pesquisa científica base**: FAO-56 evapotranspiração (https://www.fao.org/4/X0490E/X0490E00.htm); AquaCrop FAO (https://www.fao.org/aquacrop); DSSAT open source (https://dssat.net/development/open-source/). São referências e frameworks a avaliar, **não modelos calibrados já implementados**.

## Reuso identificado no AgroLogMT

Priorizar estas peças (testar API, integridade e licença antes de copiar/importar):
- **Dados e história:** `collector/conab_safra_history.py`, `collector/conab_safra.py`, `collector/nasa_power.py`, `collector/ana_hidrowebservice.py`, `collector/usda_wasde.py`, `collector/nass_quickstats.py`, `collector/inmet_daily.py`, `cftc_cot/client.py`.
- **Métodos físicos:** `models/agroclimate.py` com Hargreaves-Samani, graus-dia e balde hídrico; `models/hydrology.py` com climatologia e tendências; `models/weather_multimodel.py` com consenso por execução e quantis.
- **Validação:** `models/analog_years.py`, `models/backtest.py`, `models/point_in_time.py`, `models/promotion.py` para análogos, backtests, prevenção de look-ahead e promoção de modelos.
- **Não incorporar automaticamente:** workers GCP, dependências BigQuery, schedulers, credenciais, integrações custosas, backfill sem direitos, serviços de mercado restrito ou qualquer deploy legado.

## Sequência única de homologação sem expansão avulsa

1. Confirmar diretos por operação e endpoints; amostras reais autorizadas, hashes, parser e reconciliação. Corrigir metadados datados, sem inferir data de publicação.
2. Retrocarga mais antiga **tecnicamente e juridicamente acessível**, separada por série e preservando RAW fora do GitHub, revisões e datas as-of.
3. Conferir identidade física, versão de unidade, cobertura e estatística descritiva; identificar impossibilidades, lacunas e quebras.
4. Reutilizar os motores AgroLog selecionados após revisão de código/dependências, traduzindo para contratos NIVON e testes de regressão.
5. Backtest walk-forward real com baseline e relatório de erros por região/cultura; auditor independente.
6. Somente então habilitar indicadores ou IA narrativa; a produção e WhatsApp continuam fora deste PR.

### Critério de aceite científico

Sem evidência de dados reais históricos, cobertura, licença, erros de previsão e testes de invariantes, o estado é **CANDIDATE / NÃO HOMOLOGADO**. Permite pesquisa e cenário explicitamente rotulado; não permite alegar previsão validada nem go-live.

## Política de integração concorrente / gate de revisão

Este PR foi preparado a partir do commit `3329bbcfda4aadf4f08ea77b64d2abdffe292157` da linha `feat/agrobr-portos-motores-agentes-20261019`.
Durante a auditoria, a linha de desenvolvimento recebeu commits simultâneos de outros módulos; testes que mesclam a branch mais recente podem apresentar falhas de terceiros. O alvo `review/nivon-ciencia-base-20261019` congela **somente a base de verificação científica** para permitir avaliação repetível, sem afirmar compatibilidade final com a branch em movimento.

**Antes do merge de produção**, deve ser realizado merge/rebase limpo contra a branch-integrada vigente, auditoria de conflitos sem perda de novas fontes/contratos, regressão completa e validação independente dos datasets. O sucesso de testes desta revisão congelada NÃO constitui go-live nem liberação de coleta.
