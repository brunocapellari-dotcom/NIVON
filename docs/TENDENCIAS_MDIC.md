# Tendências descritivas MDIC — sem previsão automática

`tendencias_mdic.classificar_tendencia_mdic` usa as séries por NCM8 ou SH4/UF do módulo `series_mdic_modelos`. Compara os últimos 12 meses com os mesmos 12 meses do ano anterior (controle sazonal básico). A classificação é `ALTA`, `BAIXA`, `ESTABILIDADE` ou `INDETERMINADA` por mediana das variações YoY e concordância direcional mínima de 75% sobre limiar de 5% (configurável). Mede dispersão pela mediana dos desvios absolutos (MAD).

Mês ausente não é zero; se um denominador anual for zero, não se calcula percentagem e o resultado é inconclusivo. Não há probabilidade de movimento futuro, inferência de frete, movimentação efetiva portuária ou origem física da carga. Foco é **sinal estatístico descritivo histórico**, não previsão, nem recomendação comercial.

A execução com séries sintéticas exige `permitir_sinteticos_para_teste=True`, e `publicavel=False` e `homologado=False` são fixos até que as fontes, os valores e as versões estejam validados com dados oficiais reais. Sem coleta, deploy, merge, credenciais ou serviço pago.
