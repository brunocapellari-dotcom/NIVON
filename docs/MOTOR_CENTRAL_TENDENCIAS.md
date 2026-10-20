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
