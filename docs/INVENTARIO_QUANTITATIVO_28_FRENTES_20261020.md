# Inventário Quantitativo NIVON — rastreio em 20/10/2026

**Manifesto canônico:** `config/motores_inteligencia.v1.json`, observado na branch `feat/motor-tendencias-transversal-20261020`; manter contagens derivadas do manifesto, não duplicar registry.  
**Estado geral:** código com testes sintéticos; sem treino/entrada real homologados, sem operação e sem publicação autorizada.

- **28 frentes de domínio** (não confundir com os 14 chats/frentes de execução e coordenação).
- **270 vínculos** de função entre frentes, **120 entrypoints distintos**, **54 módulos Python distintos** vinculados e **288 indicadores planejados**.
- Cada vínculo é uma interface no registro, **não um modelo preditivo treinado**, nem um dataset ingerido.
- Todos os manifestos declaram `CODE_TESTED_SYNTHETIC_ONLY`, `inputs_reais_homologados=false`, `previsao_homologada=false`, `operational_enabled=false`.

## Cobertura de todas as frentes

| Frente de domínio | Funções vinculadas | Módulos vinculados | Indicadores previstos | Validação quantitativa / hipótese de risco prioritária |
|---|---:|---:|---:|---|
| SOJA | 19 | 12 | 18 | Safra e balanço, CBOT por vencimento, preços por praça, leakage e baseline sazonal |
| MILHO | 18 | 12 | 16 | Separar safras; balanço físico e feed; CBOT, preços e vintage |
| ALGODAO | 11 | 8 | 11 | Grão/pluma/caroço, conversão ICE, unidades e qualidade |
| BOI | 5 | 4 | 7 | Carcaça, arroba, preços, ciclos e dado sanitário point-in-time |
| BEZERRO | 4 | 3 | 3 | Relação de troca, preço de reposição e defasagens |
| ACUCAR | 5 | 4 | 8 | ICE, ATR/mix, rendimentos, paridade e base econômica |
| TRIGO | 11 | 8 | 9 | Import parity FOB/CIF, unidades e contrato CBOT |
| SORGO | 7 | 5 | 5 | Substituição nutricional, elasticidade e incerteza |
| FERTILIZANTES | 6 | 4 | 9 | CIF, conversões, preço/unidade, vigência e relação de troca |
| DIESEL | 9 | 6 | 10 | Diesel A/B, densidade, mistura, FX, tributos e timing |
| ETANOL_DDG | 5 | 3 | 6 | Balanço de massa, rendimento e matéria seca |
| LOGISTICA_INTERMODAL | 5 | 4 | 9 | Custos, capacidade e comparabilidade da rota |
| MARITIMO | 8 | 6 | 8 | Escala/DUV sem dupla contagem, previsto versus realizado |
| CLIMA_HIDRO | 23 | 15 | 7 | Fachada: evitar duplicação e vincular gate dos motores setoriais |
| MERCADO_MACRO | 8 | 6 | 8 | Câmbio, basis, correlação espúria, liquidez e calendário |
| BRIEFING_DIARIO | 7 | 6 | 6 | Corte de notícias 24h, fechamento e vigência da fonte |
| CANA | 8 | 6 | 12 | Safra, ATR, teor, moagem e modelo de produtividade |
| GERGELIM | 8 | 6 | 11 | Série curta, amostragem, comércio exterior e unidades |
| FRANGO | 6 | 3 | 13 | Conversão carcaça, preço da ração, sazonalidade e defasagens |
| SUINO | 6 | 3 | 13 | Peso de carcaça, conversão ração, preços e ciclo |
| METEOROLOGIA | 35 | 19 | 19 | Previsão ensemble, calibração, estações, escala e tempo de corte |
| HIDROLOGIA | 21 | 13 | 21 | Cota versus vazão, chuva–vazão, NSE/KGE, extremos e restrições |
| ARMAZENAGEM | 5 | 4 | 9 | Capacidade versus estoque, ocupação sem fabricação de estoques |
| COMERCIO_EXTERIOR | 8 | 6 | 10 | NCM temporal, quantidade/valor, deflator e revisões |
| PETROLEO_ENERGIA | 6 | 5 | 10 | Brent versus derivados, FX, cotações e transmissões |
| FRETE_RODOVIARIO | 6 | 4 | 11 | P0: mesmo embarque/transportadora/regime; issue #25; evitar agregação municipal |
| RISCO_GEOPOLITICO | 4 | 3 | 10 | Evidência e cenário ≠ atribuição causal/variação estimada |
| INDUSTRIA_PROCESSAMENTO | 6 | 5 | 9 | Balanço físico, coeficientes, margens e incerteza |

As descrições de risco acima são **gates para auditoria futura**, não alegação de erro concreto em cada fórmula. A falha de comparabilidade de fretes é a exceção documentada, ver [issue #25](https://github.com/brunocapellari-dotcom/NIVON/issues/25).

## Matriz de criticidade comum e responsabilidade

| Tipo de risco | Regra de validação quantitativa | Responsável pelo dado/modelo |
|---|---|---|
| Vazamento e revisão | edição por corte de publicação/coleta, emissões horárias, holdout real | Eng. de Dados + domínio |
| Unidades e comparabilidade | mesmo produto, praça, vencimento, frete em BRL/T com condições homogêneas | Domínio + Quantitativo |
| Modelo sem ganho real | benchmark simples, rolling-origin, MAE/RMSE/Brier/intervalos e incerteza | Quantitativo valida, domínio treina |
| Confusão entre tendência observada e previsão | classes + horizonte explícito; consenso de cenários não é probabilidade | Quantitativo |
| Dados raros / regimes | efetivo N, dependência temporal, estabilidade/regime, sensibilidade | Domínio + Quantitativo |
| Comunicação indevida | nenhum score sintético publica previsão, sem direito/licença e homologação | Editorial + Governança |

## Primeiro backlog executável

1. **P0, feito nesta PR:** folds por vintages as-of, métricas OOS, previsões por resíduos históricos rotuladas não calibradas, regressões.
2. **P0, atribuído à frente de Fretes:** corrigir identidade de embarque e transportadora, evitar média municipal/corredor e comparar apenas condições equivalentes — issue #25.
3. **P0, dados/mercado:** fornecer calendários CME por vencimento, fechamentos originais com fuso, direitos de uso, preço físico por praça e histórico de ofertas identificadas, com vintage verificável.
4. **P1, motor setorial:** ligar os adaptadores PR #12 ao contrato `quant_core` sem acoplamento de dados reais nem habilitar operações.
5. **P1, validação científica:** executar rolling-origin com refit real e holdout temporal, calibração separada, robustez por regime, comparação contra baselines e travas de publicação.
6. **Gate integração:** levar PR #20 depois de PR #12 à PR #13; rodar CI no SHA reconciliado e não fazer merge/deploy até aceite formal.

Este inventário é uma **auditoria de cobertura do manifesto**, não uma leitura linha a linha de todas as 120 funções nem prova de qualidade estatística dos 288 indicadores.
