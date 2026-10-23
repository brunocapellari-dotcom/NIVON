# NIVON — dinâmica histórica de fretes em painel pareado R01

**Estado:** implementado em branch de revisão, sem dados reais homologados, sem previsão, sem cobrança, automação ou publicação.

## Motivação

O frete rodoviário é a prioridade P0 do Motor de Tendências. Série municipal de ofertas, embora pareça subir, pode refletir apenas entrada de novas fazendas, trocas de transportadoras, veículos, terminais de descarga ou pedágio. O **painel pareado R01** da integração logística (#42, metodologias #18/#30) corrige esse viés de composição.

## Pipeline estritamente offline

`OfertaFrete` → `preparar_painel_pr30` → `tendencia_frete_anunciado(janela=2N, incluir_serie_pareada=True)` → `comparar_forca_tendencia` → `dinamica_ofertas_pareadas`.

- Todas as ofertas de uma execução conservam origem/destino IBGE, terminal de descarga, produto, equipamento, regime PF/PJ, regra de pedágio e base em BRL/t.
- Para cada sessão, deduplicação por (data, ponto de embarque, transportadora), com conflito de preço recusado. Reenvios idênticos não geram novos pares.
- O painel de participantes é a interseção das **2N sessões**; mesma população nas janelas anterior e atual. Se restarem menos de dois pares, `PAINEL_INCOMPARAVEL` e dinâmica `INDETERMINADA`.
- Cada série é a mediana das **variações da mesma identidade** comparadas ao primeiro dia do painel inteiro. Não calcular mediana de preços de diferentes estabelecimentos/transportadoras nem chamar o resultado de cotação municipal.
- As duas janelas sem sobreposição têm N observações; cálculo de inclinação Theil–Sen e comparação da amplitude em múltiplos de uma banda comercial absoluta (BRL/t) declarada. Permite dados negativos **apenas para a variação**, nunca para o preço base anunciado.
- Classes de dinâmica: `AUMENTO_DE_FORCA`, `PERDA_DE_FORCA`, `FORCA_SEM_ALTERACAO_RELEVANTE`, `REVERSAO_OBSERVADA`, `SAIDA_DA_ESTABILIDADE`, `ENTRADA_EM_ESTABILIDADE`, `ESTABILIDADE_PERSISTENTE` e `INDETERMINADA`.
- `as_of` timestamp com timezone; o dia comercial é determinado por `America/Cuiaba`, sem recuperar automaticamente uma oferta antiga como recente.
- Os SHA de evidência neste caminho são **derivados** de registros fornecidos. Não são prova de acesso a RAW do WhatsApp, consentimento, autenticidade da fonte ou de contratação realizada.

## Contrato de execução

`nivon.fretes_dinamica_r01:dinamica_ofertas_pareadas` recebe ofertas `OfertaFrete` já admitidas por pipeline confiável, origem/destino, descarga, produto, equipamento, regime, pedágio, `as_of`, `janela=6`, `minimo_pares=2`, `tolerancia_absoluta=2.0`, `mudanca_minima_forca_em_limiares=1.0`.

A comparação precisa de **12 sessões válidas para N=6**. O intervalo não representa, por si, "12 dias corridos"; a classe `SESSOES` requer validação de calendário comercial externo. Faltas, feriados e cobertura devem ser tratados antes de projeções. Nenhuma extrapolação para 7/30/90 dias é feita.

O retorno guarda `tendencia_atual`, `dinamica`, força antiga e atual, pares comparáveis, cobertura, datas e metodologia, com `publicavel=false`, `probabilidades_calibradas=null`, `direitos_publicacao_verificados=false` e `homologacao_origem=PENDENTE`.

## Evidência e gates

Regressões em `tests/test_fretes_dinamica_r01.py` cobrem janelas disjuntas, aceleração descritiva, perda de força, reversão, rota/pedágio, composição variável, repetição de anúncios, conflito de valores e corte intradiário. São dados estritamente artificiais.

Falta: histórico de ofertas realmente autorizado com resolução e prova RAW verificadas; séries longas por rota/estabelecimento/transportadora; calendário e limites dimensionados por corredor; backtesting por data de emissão; avaliação de performance contra baseline; validação de licença e integração controlada com painel/IVO/briefing.

**Regra de produto:** tendência observada não é previsão; peso de cenários não é probabilidade de alta. Nenhuma habilitação automática de coleta ou publicação.
