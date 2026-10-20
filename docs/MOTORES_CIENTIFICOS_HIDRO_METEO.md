# Núcleos científicos de Hidrologia e Meteorologia — NIVON

**Versão arquitetural:** 2026-10-20, PR #1. **Natureza:** motores determinísticos auditáveis e candidatos de fonte; modelos empíricos NÃO HOMOLOGADOS.

## 1. Catálogo integrado e papel de cada produto

A matriz canônica do NIVON registra 4 bases novas (100 fontes e 135 datasets) sem ativar coleta:
- NASA POWER Daily API — https://power.larc.nasa.gov/docs/services/api/temporal/daily/ — séries meteorológicas e radiação de produto gridded; variação local, limites e timezone precisam ser conciliados.
- CHIRPS v3 — https://www.chc.ucsb.edu/data/chirps3 — chuva 0,05° terrestre 1981–atualidade aproximada, estimativa satélite/estações, não pluviômetro local.
- Copernicus ERA5-Land — https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=documentation — reanálise horária ~0,1° desde 1950 com CC BY e atribuição; distinguir reanálise, horários UTC, acumulados, revisões e versão. O endpoint ARCO específico para séries de ponto tem avisos de uso operacional; não adotá-lo para produção sem homologação.
- NASA GPM/IMERG — https://gpm.nasa.gov/data/imerg — estimativas multissatélite 0,1°, 30 min, versões Early/Late/Final com latência, QC e escalas distintas.

Complementares já presentes: INMET estações/BDMEP; ANA HidroWebService; NOAA GFS; ECMWF; CPTEC/INPE. Nunca duplicar fonte ou tratar previsão GFS como chuva observada.

## 2. Núcleo agrometeorológico

`src/nivon/motores_agrometeorologia_fao56.py`:

- **Penman–Monteith FAO-56 diário:** ET0 = [0,408 Δ(Rn-G)+γ 900/(T+273) u2 (es-ea)]/[Δ+γ(1+0,34u2)]; ET0 em mm/dia, Rn **radiação LÍQUIDA** MJ/m²/dia, vento 2 m, RHmin/RHmax e pressão de altitude. Fontes metodológicas: FAO Irrigation and Drainage Paper 56, capítulo 4 https://www.fao.org/4/x0490e/x0490e08.htm.
- **ETc e balanço hídrico:** ETc=Kc×ET0; simulação conservativa simples do reservatório de água do solo com déficit ET; Kc/água disponível/chuva efetiva precisam ser locais. Não equivale a Ks, irrigação recomendada ou previsão de safra.
- **Anomalia e percentil histórico:** mínimo 30 anos de referência para mesma janela sazonal, sem faltantes nem substituição; percentil empírico de chuva não pode ser apresentado como SPI/SPEI. WMO SPI requer estatística de distribuição e período climático adequados https://library.wmo.int/viewer/39629.

## 3. Núcleo hidrológico

`src/nivon/motores_hidrologia_cientifica.py`:

- **Curva cota–vazão:** interpolação estritamente MONÓTONA em escala logarítmica entre aforos **da mesma estação, datum e versão de curva**; extrapolação proibida. Não é curva calibrada automaticamente nem vazão medida. Referência técnica USGS https://www.usgs.gov/centers/wyoming-montana-water-science-center/creating-rating-curve.
- **Balanço volumétrico de reservatório:** Vfinal=Vinicial+Qentrada Δt+P×A−Qsaída Δt−E×A−vertimento; mm sobre km² multiplicar por 1000 para m³; eventos impossíveis bloqueados; sem operação hidráulica real.
- **Skill de vazão:** MAE, RMSE, viés, Nash–Sutcliffe e comparação com baseline de persistência. Resultados são diagnósticos apenas quando os valores informados são pareados, sem vazamento temporal.

## 4. Validação preditiva transversal

`src/nivon/validacao_previsoes_ambientais.py`:

- Confere timezone nas datas, horizonte constante, emissão anterior ao evento e features publicadas até a emissão; observação publicada após a validade.
- Exige QC aprovado, mínimo de 20 pares para horizonte (limite técnico do motor; uso real exige mais), baseline explícito e comparação de erro.
- Confronta 30+ dias coincidentes de grade meteorológica com estação, QC e distância fonte–grade declarada; não transforma grade em verdade do talhão.
- NÃO garante independência dos features reprocessados, dos folds de treino nem desempenho operacional. Versões/vintages e teste em anos/outros municípios são gates separados.
- O próprio score `homologado` permanece `false` até auditoria independente.

## 5. Bibliotecas open source avaliadas

Componentes **candidatos**, não instalados nem incorporados a repositório nesta etapa:

- [pyet](https://github.com/pyet-org/pyet) — avaliação cruzada FAO-56 e métodos alternativos ET0. Verificar licença, versão, dependências e benchmarks FAO antes de usar em produção.
- [xclim](https://github.com/Ouranosinc/xclim) — índices climáticos e processamento de séries. Exigir baseline, metadados CF e homogeneização temporal.
- [HydroMT](https://github.com/Deltares/hydromt) — estruturação geoespacial de bacias e modelos hídricos (núcleo MIT; plugins podem possuir licenças diferentes).
- [neuralhydrology](https://github.com/neuralhydrology/neuralhydrology) — hidrologia baseada em redes neurais, apenas depois de dados históricos e baselines empíricos com holdout.
- [hydroeval](https://github.com/ThibHlln/hydroeval) — métricas NSE/KGE; código declarado GPL, deve haver revisão jurídica de incorporação/distribuição; metodologia pode ser implementada independentemente sem copiar código.

A versão leve não depende de NumPy/Scipy/GIS para cálculos FAO-56 e verificação primária; integração futura destas bibliotecas exige licença e footprint compatíveis com custo zero.

## 6. Integração com Ivo e operação do Nivon

O Ivo pode propor hipóteses climáticas, relacionar seca, produtividade, fluxos logísticos e preços; não tem poder de alterar séries observadas ou validar probabilidades sem evidência. Cada previsão precisa registrar fonte, município/bacia, unidade, carimbo de emissão, lead-time, corte temporal, modelo/versão, baseline, intervalo de incerteza, publicação e classificação como dado observado, estimado ou projetado.

O briefing WhatsApp receberá sinais somente de coletores homologados e com datas de referência — alertas de chuva ou de navegação não podem ser inventados por LLM.

## 7. Pendências reais para a homologação

Acesso ANA SSO e conteúdo BDMEP foram localizados em Gmail, mas ainda exigem teste autenticado real sem transferir credenciais para o GitHub. Faltam execução/licença por operação, amostra real completa, backfill incremental, benchmark cruzado com medições INMET/ANA, modelo hidrológico por bacia, validação temporal, armazenamento durável, backup na nuvem e observabilidade. **Nenhuma das 135 rotas foi habilitada para coleta automática e nenhum modelo preditivo foi promovido a homologado.**
