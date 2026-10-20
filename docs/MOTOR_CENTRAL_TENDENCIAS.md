# NIVON — Motor Central de Tendências v0.1

**Estado:** código offline, demonstrável em dados sintéticos, NÃO HOMOLOGADO com históricos reais. Nenhuma coleta, publicação, automação ou inferência de probabilidade foi ativada.

## Missão

Classificar **ALTA**, **BAIXA**, **ESTABILIDADE** e **INDETERMINADA** em variáveis quantitativas das cadeias agrícolas, pecuárias, industriais, de preços, hidrometeorológicas e logísticas. O motor NÃO substitui modelos específicos e NÃO interpreta causas sem evidências. São duas APIs independentes:

1. `tendencia_observada`: calcula a direção **histórica** em janela regular, sob corte temporal, sem previsão.
2. `tendencia_projetada`: resume consenso entre **cenários futuros já produzidos por modelos externos**. Percentuais de pesos são participações de cenários, **nunca probabilidades estatisticamente calibradas**.

As duas rotinas retornam `publicavel=false` e `probabilidades_calibradas=null`. Uma classe `INDETERMINADA` não é sinônimo de estabilidade.

## Contrato de dados obrigatório

Cada observação: `{periodo: "AAAA-MM-DD", valor: 0.0, fonte_id: "ID", publicacao: "AAAA-MM-DD", coleta: "AAAA-MM-DD", edicao_sha256: "<64 hex>"}`. O processamento exige referência <= publicação <= coleta <= corte `as_of`, sem fonte mista, revisões/edições duplicadas, lacunas nas frequências regulares, NaN, infinito ou bool. Uma edição de dado precisa ser selecionada conforme disponibilidade histórica **antes** de chamar o motor.

Frequências aceitas: `DIARIA` (dias consecutivos), `SEMANAL` (passo de 7 dias), `MENSAL` (primeiro dia de meses consecutivos), `ANUAL` (primeiro dia de anos consecutivos), `SESSOES` (datas estritamente crescentes, com lacunas de até 10 dias por feriados/fins de semana). `SESSOES` exige validação adicional do calendário de pregões na ingestão: não trata dias de mercado ausentes como fechamento válido.

**Limiar:** sempre fornecer `tolerancia_absoluta` e/ou `tolerancia_relativa` com pelo menos um valor positivo por *indicador/unidade/janela*. O motor recusa limiar zero. Não há limiar universal de alta/baixa. Séries que naturalmente podem ser negativas, como anomalias de temperatura, exigem `nao_negativo=False`.

## Estatística e interpretação

### Observações

- Padrão: inclinação mediana de todas as inclinações entre pares (Theil–Sen); `deslocamento_descritivo` = inclinação × (tamanho da janela - 1). Trata-se de movimento no intervalo **passado**, não extrapolação.
- Movimento supera banda definida pelo indicador: classificar alta/baixa só se pelo menos 65% das inclinações entre pares corroborarem o sinal; caso contrário, **INDETERMINADA**.
- Dentro da banda: estabilidade apenas se amplitude amostral não excede duas bandas; caso contrário, **INDETERMINADA** por ruído elevado.
- Com `MENSAL + sazonalidade=12`, método muda para mediana das diferenças interanuais dos últimos meses; o resultado é **diferença ano contra ano**, não inclinação mensal nem dessazonalização estatística completa. Requer pelo menos janela + 12 meses e comparabilidade das edições.
- Intensidade `LEVE/MODERADA/FORTE` descreve múltiplos da banda configurada (1–2, 2–4, >=4) e **não** é significância, confiança ou qualidade preditiva.

### Cenários futuros

`tendencia_projetada(base, cenarios, as_of, ...)` exige pelo menos três cenários independentes em identificador; emissão até o corte; mesma data futura de alvo; pesos não negativos somando 1. Rotula direção quando a maior participação é >=60% e vantagem sobre a segunda é >=20 pontos percentuais. Caso contrário retorna **INDETERMINADA**.

- Os pesos podem ser subjetivos e os modelos altamente correlacionados. Logo, consenso não equivale à probabilidade de alta/baixa.
- Futuras probabilidades reais deverão ser emitidas por um calibrador treinado fora da amostra, com backtests temporais point-in-time, log de versão, métricas por horizonte e incerteza confiável.
- O motor v0.1 **não** gera previsão por conta própria; lê projeções fornecidas pelos motores setoriais.

## Horizontes a conectar (configuração por indicador, não valores universais)

| Cadeia | Curto | Médio | Longo | Nota de interpretação |
|---|---|---|---|---|
| Preço físico, CME/ICE, dólar, diesel | 5 sessões | 20 sessões | 60–120 sessões | contratos, moeda, rolamento, feriados e base comparáveis |
| Frete rodoviário | 7 dias | 30 dias | 90 dias | preço de oferta ≠ preço efetivamente contratado; amostras deduplicadas |
| Plantio/colheita | 4 semanas | 8 semanas | 12 semanas | usar **ritmo de avanço**, não percentual acumulado monotonicamente crescente |
| Meteorologia | 7 dias | 30 dias | estação/safra | separar chuva observada, anomalia e probabilidade futura |
| Hidrologia | 7 dias | 30 dias | sazonal | cota não prova vazão, calado ou navegabilidade |
| Portos/line-up | 7 dias | 30 dias | 90 dias | escalas programadas vs realizadas e cobertura por porto/terminal |
| Produção, consumo, exportação, estoques | mensal | trimestre | ano/safra | sazonalidade, balanço físico e revisões point-in-time |
| Pecuária, açúcar/etanol, fertilizantes, agroindústria | mensal | trimestre | ciclo/safra | unidades físicas, defasagens e regimes setoriais |

Os horizontes precisam ser **avaliados e ajustados com dados históricos reais** por modelo, região e série. Queda de estoque pode indicar pressão altista de preços, mas o motor não converte automaticamente o sinal de estoque em sinal de preço.

## Integração e gates de produção

- Módulo: `src/nivon/motor_tendencias.py`.
- Registro: `config/motores_inteligencia.v1.json` com vínculo **offline** a 26 frentes quantitativas; `src/nivon/registro_motores.py` mantém importação sob allowlist. BRIEFING_DIARIO e RISCO_GEOPOLITICO não ganham série numérica artificial.
- Entrada futura: séries bitemporais selecionadas de CONAB, ANP, ANTT, MDIC, ANA, INMET, CME/ICE com direitos por operação e QA; eventos do WhatsApp AI só mediante autorização e deduplicação.
- Saída futura: painel de tendências, explicações por fonte e horizonte, IVO como intérprete supervisionado, briefing NIVON somente depois de liberação de publicação. WhatsApp AI permanece apenas transportador.
- Próximos gates: validar licença de dados e histórico real; QC calendário, unidade e frequência; parametrizar bandas com dados de treinamento; comparar com baselines; walk-forward por data de emissão/publicação/coleta; descrever métricas de acerto por horizonte e mudanças de regime; homologar incerteza e direitos; implantar armazenamento auditável, monitorar degradação, autorizar release/deploy **separadamente**.
- Bibliotecas candidatas, **não instaladas nesta PR**: StatsForecast (baselines e backtests), ruptures (quebras estruturais offline), River/ADWIN (monitorar drift online). Avaliar manutenção, licença e custo de processamento antes de introduzir dependência.

## Execução local

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_motor_tendencias.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.registro_motores
```

Fixtures sintéticas não provam valor preditivo nem autorizam go-live.


## PRIORIDADE OPERACIONAL (20/10/2026): FRETES, CBOT E PREÇO FÍSICO

Este é o recorte **P0** do motor de tendências; os demais 26 domínios quantitativos são capacidades secundárias. O código específico reside em `src/nivon/tendencias_mercados.py` e possui regressões em `tests/test_tendencias_mercados.py`.

### 1. FRETE ANUNCIADO — por corredor (prioridade 1)

**Método R01 (integração PR #30): variação pareada de ofertas comerciais**, não mediana diária de níveis de preço por município. A versão anterior estava sujeita ao efeito-composição quando saíam fazendas com preços mais baixos e entravam outras mais caras, mesmo sem qualquer aumento individual.

- Chave da série: `origem_ibge + destino_ibge + produto + veiculo + pedagio + natureza(OFERTA) + unidade(BRL/T)`. A chave econômica da comparação temporal é `pickup_entity_id + transportadora_id`, ambos obrigatórios e previamente resolvidos. `lote_id` permanece como referência de anúncio/proveniência, não substitui o estabelecimento.
- Em cada dia, registros repetidos da mesma combinação ponto de embarque + transportadora com preço idêntico contam uma vez. Preços conflitantes da mesma combinação no mesmo dia bloqueiam a análise; a revisão comercial precisa ser reconciliada por procedimento próprio.
- Apenas combinações econômicas presentes em **todos os dias da janela** entram no painel. O motor calcula a variação R$/t de cada combinação em relação à sua própria primeira observação, e analisa a mediana **das variações pareadas**, nunca o nível ou média de frete municipal. Troca de composição sem dois pares estáveis retorna `PAINEL_INCOMPARAVEL / INDETERMINADA`.
- Não calcular, armazenar, exibir ou exportar **média de frete por município**. Município é referência geográfica, não unidade comercial agregada. Tampouco interpretar a variação pareada como preço médio do corredor.
- Exigir ao menos dois pares por dia, mínimo de dois pares comuns, séries ordenadas e datas disponíveis até o corte. Limiar **absoluto R$/t** pode ser aplicado à diferença; tolerância relativa fica bloqueada nesta versão, pois não pode ser calculada contra mediana de diferenças ancoradas em zero sem normalização específica.
- Produto, equipamento e pedágio devem permanecer iguais em todo o recorte; `INCLUSO`, `ADICIONAL` e `NAO_INFORMADO` são modalidades diferentes. Regime PF/PJ, local de descarga, frete base, pedágio, frete cheio, distância, R$/TKU e proveniência devem ser preservados nos registros de origem quando disponíveis; comparabilidade adicional deve ser auditada pelo coletor.
- Prioridade inicial: Sorriso–Rondonópolis, Sorriso–Dom Aquino, Sinop–Miritituba/Itaituba (com distinção do município e distrito); também destinos Paranaguá, Santos e Uberaba. Não presumir equivalência automática entre terminal e cidade.
- O sinal é **descritivo e não publicável**: frete anunciado não é contrato, embarque efetivo, volume t/dia nem preço de mercado representativo. Reposts não geram novos lotes ou toneladas. Direitos, amostras reais, calendários, backtest point-in-time e processo editorial ainda bloqueiam publicação.

### 2. CBOT — preço e vencimento homogêneos (prioridade 2)

Chave: `mercado=CME + produto(SOJA/MILHO/TRIGO) + contrato(AAAA-MM) + tipo(FECHAMENTO/AJUSTE) + unidade(USC/BU)`.

- Nunca comparar soja NOV/26 com MAR/27 como se fosse movimento de um ativo estável; `tendencia_cbot` rejeita misturas.
- Séries contínuas e roll devem ter política explícita de continuidade, datas de rolagem e ajuste retrospectivo, construídos e validados separadamente, **não** por esta primeira versão.
- Usar fechamento/ajuste datados, calendário de pregões válido e direitos de mercado. Não confundir centavos/bushel com dólares/tonelada. Comparações com preço físico em reais exigem conversão física exata, PTAX do período, praça, prêmio/basis, sazonalidade e custos observados.
- Visões futuras desejadas: 5, 20 e 60 pregões; volatilidade e probabilidade somente após treino histórico e calibração point-in-time.

### 3. PREÇO FÍSICO — por produto e município (prioridade 3)

Chave: `produto + localidade_ibge(7 dígitos) + tipo(INDICADOR_FISICO/OFERTA/NEGOCIADO) + unidade`.

- Soja, milho, trigo e outras cadeias do registro; preço físico pode usar `BRL/SC60KG`, `BRL/T` ou `BRL/ARROBA` quando adequados ao produto. Não misturar praça, produto, categoria de preço ou unidade.
- O preço físico de Sorriso/MT não equivale a preço em Paranaguá. Se um indicador usar metodologia regional agregada, sua identidade geográfica deve ser descrita e um adaptador próprio deverá preservar essa granularidade.
- Fonte observacional, precisão, alterações metodológicas, coleta, publicação, licença e histórico de revisões devem ser rastreados.

### Quadro operacional planejado

| Indicador | Tendência observada | 7 dias | 30 dias | 90 dias | Fonte e data |
|---|---|---|---|---|---|
| Frete Sorriso → Rondonópolis (MILHO/RODOTREM) | calculável com série homologada | futuro modelo | futuro modelo | futuro modelo | obrigatório |
| Frete Sinop → Miritituba (SOJA/RODOTREM) | calculável com série homologada | futuro modelo | futuro modelo | futuro modelo | obrigatório |
| CBOT SOJA NOV/26 (USC/BU) | calculável com série homologada | futuro modelo | futuro modelo | futuro modelo | obrigatório |
| Preço físico SOJA Sorriso/MT (R$/sc) | calculável com série homologada | futuro modelo | futuro modelo | futuro modelo | obrigatório |

**Nenhuma linha acima é uma cotação atual ou previsão já calculada**. Horizontes dependem de conjunto de dados, unidade e calendário; uma tendência observada não pode ser apresentada como projeção para 7/30/90 dias.

### Gate de integração

1. Homologar schema, direitos e proveniência dos históricos dos coletores de fretes autorizados, CME/licenciada, CEPEA/IMEA/mercado físico e BCB/PTAX; nenhum status falso de ativo.
2. Implementar pipeline as-of com revisões e agregação por sessão/corredor, capturando cobertura e correções.
3. Calibrar limiares por produto/corredor/praça em treino sem vazamento, avaliar walk-forward temporal e reportar MAE, acerto de direção, calibração (Brier/reliability) e estabilidade por regime.
4. Somente então habilitar probabilidades, previsão setorial e síntese IVO, com validação de licenças para publicação.
5. Integrar no painel e em uma seção de tendências do briefing, somente após homologação editorial; WhatsApp AI mantém responsabilidade exclusiva pelo transporte de mensagens.

O código nesta PR é **exclusivamente offline com fixtures sintéticas** e não executa coletas, envios, deploy ou publicação.
