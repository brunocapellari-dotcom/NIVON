# NIVON — Mapa mestre de motores e inteligência

**Data de corte da auditoria:** 19/10/2026  
**Base:** PR #1 do NIVON, sem merge/deploy.  
**Estado:** implementação de funções determinísticas offline e testes sintéticos; nenhuma frente deve ser rotulada como operacional ou preditiva homologada.

## Escopo completo: 28 frentes

| Frente | Motores presentes no código | Principais integrações ou modelos reais pendentes |
|---|---|---|
| Soja | Safra/comercialização, decomposição área × produtividade, CBOT, balanço do esmagamento, cenário sazonal | Plantio/colheita real, basis, preço físico, estoques, renda, previsão agroclimática |
| Milho | Três safras sem dupla contagem, ração/indústria, CBOT, etanol/DDG, progresso | Consumo efetivo, demanda por usina e ração, projeção da segunda safra |
| Algodão | Beneficiamento massa pluma/caroço, área/produtividade | Qualidade e prêmio de pluma, ICE, paridade, margens industriais |
| Boi | Carcaça, arroba e valor bruto por animal em cenário | Ciclo do rebanho, escalas, confinamento, preço físico, exportações convertidas |
| Bezerro | Relação de troca bruta | Cria-recria, disponibilidade futura e custo de reposição |
| Açúcar | ICE 11 convertido e mix ATR sob hipóteses | Basis, paridade real, estoque e atratividade açúcar × etanol |
| Trigo | Oferta agrícola e import parity FOB→CIF→destino | Qualidade, moagem, estoques e balanços oficiais |
| Sorgo | Substituição econômica hipotética na ração | Formulação nutricional validada por espécie e safra |
| Fertilizantes | Ureia/MAP/DAP/KCl, CIF e dose/área declarada | Entregas, capacidade de descarga, estoques, fórmulas NPK específicas |
| Diesel | Diesel A USD/t→R$/L, mistura B e preço revenda, custo por rota | Preço internacional de especificação comparável, tributos/densidade/biodiesel datados, série contínua |
| Etanol e DDG | Conversão industrial declarada + checagem de matéria seca | Rendimento físico real por fábrica, processamento e margem |
| Cana | Área/produtividade, ATR, moagem, mix hipotético | Competência de safra, ATR oficial, qualidade e custo de processamento |
| Gergelim | Produtividade, FOB USD/t, paridade e exposição por mercados | Parser XLS CONAB homologado, NCM com vigência, preço físico e clima de segunda safra |
| Frango | Peso médio carcaça, ração/margem, exportação comparável e risco sanitário | Dados SIDRA reais, produção, consumo, ciclo e sanidade |
| Suíno | Peso médio carcaça, ração/margem, exportação comparável e risco sanitário | Rebanho, abate real, ciclo, preços e sanidade |
| Logística intermodal | Comparação rodovia/ferrovia, destinos ANTT amostrais | Capacidade comprovada, custo por corredor, integração ferroviária/hidroviária |
| Marítimo | Escalas, programação e pressão teórica portuária | Line-up nacional validado, AIS com direitos, fila/fundeio/throughput reais |
| Clima e hidrologia (legado) | Fachada compartilhada dos dois motores especializados | Sem duplicação de dados ou pipelines |
| Mercado macro | Sensibilidades, decomposição câmbio/preço e PTAX | Elasticidades calibradas, volatilidade, relações empíricas |
| Briefing diário | Notícias <=24 h, deduplicação e texto offline | Pipeline de feeds, CBOT e indicadores datados, disparo automático autorizado |
| Meteorologia | Chuva/anomalia, graus-dia, balanço hídrico de solo, janela chuvosa | Dados espaciais e estações reais, ET0/Kc, modelo de produtividade com clima |
| Hidrologia | Cota e vazão, anomalias, folga de calado hipotética | Séries ANA, batimetria, datum, níveis de referência, navegação oficial |
| Armazenagem | Produção/capacidade e ocupação apenas se estoque informado | Base CONAB validada, acessibilidade, giro e sazonalidade |
| Comércio exterior | NCM exportação/importação, FOB/CIF, destinos e HHI | Dicionário NCM versionado, histórico completo, dados reais |
| Petróleo e energia | Exposição cambial, paridade diesel e custo transporte | Brent não substitui Diesel A; importação, refino, oferta e choques energéticos |
| Frete rodoviário | Custo por viagem/tonelada, diesel por rota, alternativas modais | Divulgações deduplicadas, lotes únicos, capacidade, fretes realizados se disponíveis |
| Risco geopolítico | Eventos com evidência, cadeias expostas e mecanismos hipotéticos | Monitor de sanções, evidências contraditórias, impactos quantitativos calibrados |
| Indústria e processamento | Balanços de massa, coeficientes e margens hipotéticas | Processamento real, capacidades autorizadas, custo completo e vendas |

## Regras metodológicas permanentes

1. Dado observado, informado, estimado, inferido, simulado e projetado devem permanecer distinguíveis.
2. Competência, referência, publicação e coleta são datas distintas, com SHA, vintage e versão de fonte.
3. Todo motor pode ser testado offline sem Internet, segredo, serviço pago, deploy ou publicação.
4. Balanço de massa exige unidades compatíveis: grão não se soma a farelo/óleo; algodão em caroço não se soma à pluma; carne em cortes não é automaticamente equivalente-carcaça; ATR não é massa de açúcar; litros não se somam a toneladas.
5. Meteorologia: desvio pluviométrico simples não é SPI; chuva prevista não é observada; graus-dia não é rendimento; balanço hídrico simplificado não é modelo agronômico calibrado.
6. Hidrologia: cota de régua não equivale vazão, profundidade de canal ou navegabilidade. Folga geométrica não dispensa sondagem, datum, segurança e confirmação de autoridade.
7. Diesel: cotação de petróleo bruto não equivale preço do diesel importado. Diesel A versus Diesel B requer densidade, câmbio, mistura de biodiesel, impostos, custos e margens.
8. Transporte: divulgações de transportadoras não são cotações negociadas nem operações. MDF-e com NCM é amostra; porto programado não é embarque realizado.
9. Análise de variações, sazonalidade, HHI e cenários de elasticidade não constitui atribuição causal.
10. Notícias do briefing exigem publicação nas últimas 24 horas. Cotações e indicadores têm datas de competência próprias.
11. Direitos são avaliados por operação: leitura, coleta, armazenamento, transformação, redistribuição e envio. Tudo pendente permanece desligado.
12. Nivon produz o briefing; WhatsApp AI atua somente como interface de entrega autorizada, independente.

## Contratos técnicos

- Fontes: config/fontes_nivon_master.v1.json.
- Rotas: config/rotas_coleta.v1.json.
- Indicadores por frente: config/matriz_produtos_indicadores.v1.json.
- Manifesto de funções: config/motores_inteligencia.v1.json.
- Verificação de todas as frentes, presença de função, dados relacionados e bloqueio de execução: src/nivon/registro_motores.py.
- Motores especializados: src/nivon/motores_agro_estrategicos.py, src/nivon/motores_meteo_hidro.py, src/nivon/motores_integracao_estrategica.py e src/nivon/inteligencia_temporal.py, além dos módulos preexistentes.
- Testes de regressão e bloqueios: tests/test_motores_integracao_completa.py, tests/test_inteligencia_temporal.py e tests/test_registro_motores.py.

## Gates ainda necessários antes de homologar cada indicador

1. Resolver fonte primária, série/código da commodity, direitos e API/arquivo ou página oficial.
2. Adquirir amostra real lícita, validar schema/unidade, registrar todas as datas, hash, vintage e localização canônica.
3. Recuperar histórico mais antigo disponível legal e tecnicamente; agendar coleta incremental idempotente.
4. Reconciliar física e economicamente com fonte independente; registrar lacunas e revisões.
5. Testar cenários extremos e verificar modelos contra baseline e holdout temporal sem look-ahead.
6. Implantar persistência durável em nuvem, backup/restore, métricas, alertas e defesa contra prompt injection.
7. Homologar direitos, qualidade, publicação e custos **antes** de habilitar qualquer operação.
8. Só então conectar relatórios e envio automatizado. Não utilizar merge/deploy sem autorização/homologação.

**Indicadores planejados não são indicadores já alimentados.** Uma frente com motor vinculado ainda pode depender inteiramente de dados reais, calibração e teste operacional.
