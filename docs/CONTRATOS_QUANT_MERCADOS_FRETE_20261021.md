# Contratos Quantitativos — Interoperabilidade Mercados/Logística (21/10/2026)

**Escopo:** duas bibliotecas puras de auditoria, isoladas em PR #20. **Não integra branch de terceiros, não certifica dados reais, não autoriza publicação.**

## Mercados ↔ Quant
`integracao_contratos_quant.py` valida e normaliza relatório **já calculado** por `validacao_tendencias_mercado.py` da PR #21. O Brier multiclasse das três classes aparece em duas convenções matematicamente equivalentes:
- **Mercados:** `sum_c (p_c - y_c)^2` — para classificação mutuamente exclusiva, intervalo [0,2].
- **Quant:** `sum_c (p_c - y_c)^2 / 3` — [0,2/3].
- Conversão de relatório e seu benchmark: **ambos divididos por 3**. O skill `1-Brier_modelo/Brier_baseline` permanece numericamente igual, quando definido. Sem baseline positivo, skill é indefinido.
- `ece_confianca` da PR #21 mede acurácia da classe de confiança máxima; não representa os bins one-vs-rest de `quant_core`. Não apresentar os dois como métrica equivalente.
- A ponte confere aritmeticamente ECE contra as faixas e rejeita bins sobrepostos, além de score incoerente, relatório sem gate `publicavel=False`, classe calibrada alegada, bins inconsistentes, amostra insuficiente, NaN ou infinito. Não executa prequential nem duplica o calibrador da PR #21.

## Fretes ↔ Quant
`integracao_frete_quant.py` aceita as linhas de `consolidar_ofertas(...)["registros"]` da PR #18, com a coluna adicional **`edicao_sha256` obtida do arquivo original**, quando a fonte autorizar. Uma série só pode representar:
`municipio_ibge + pickup_entity_id + transportadora_id + destino_ibge + descarga_entity_id + produto + equipamento + regime + fonte_id + tipo_valor(BASE|CHEIO) + condição de pedágio homogênea`.

- Lotes com identidades divergentes são rejeitados; **município jamais é unidade de agregação de preço**.
- Usa Decimal para validar `base`, `pedagio`, `cheio`, datas e fonte antes de converter para entrada quantitativa, **rejeitando conversões float que percam precisão decimal**. `CHEIO` precisa reconciliar `base + pedagio`. Não inventar pedágio ou frete cheio.
- Reutilização de `registro_id` para edições conflitantes é rejeitada, assim como números de frete irrepresentáveis em ponto flutuante; dados homogêneos com SHA declarado foram exercitados em um teste E2E sintético com `rolling_origin`.
- Correções de preço no mesmo dia são vintages distintas, com publicação/coleta e SHA próprios, quando disponíveis; seleção retrospectiva só ocorre por `preparar_folds_asof`.
- O formato atual da PR #18 **não tem `edicao_sha256` no registro consolidado**. Nesse caso, **`BLOQUEADO_SHA_EDICAO_AUSENTE`** e **nenhuma série quantitativa gerada**. Não fabricar SHA usando preço/município ou deduzir prova de vintage por data do WhatsApp.
- Classificação comercial constante `FRETE_ANUNCIADO_NAO_CONTRATADO`. Nenhum contrato efetivamente negociado, frete médio municipal, viagem, tonelada realizada, extrapolação probabilística ou preço de mercado criado por este adaptador.

## Dependências e gates
- Harmonizar localmente com PRs #18/#21/#30 **após testes integrados com schemas reais de cada frente**; a ponte é um contrato isolado, não prova E2E entre branches.
- Corrigir [issue #25](https://github.com/brunocapellari-dotcom/NIVON/issues/25) no SHA reconciliado (incluindo descarga, regime e deduplicação).
- Conseguir vintages RAW autênticos, timestamps verificáveis, licenças e calendário oficial, incluindo lote/mercado/vencimento corretos.
- CI no HEAD da PR #20; backtest com treino/calibração separados por cortes e avaliação independente antes de uso de probabilidades ou publicação.

## Resultados e limitação de integração

A suíte `tests/test_integracao_quant_mercados_frete.py` cobre o caminho
`registros de ofertas` → `observacoes_asof` → `executar_rolling_origin_asof`
sobre dados **sintéticos do contrato PR #18**, inclusive comparação apenas da
mesma identidade econômica, timestamps com fuso, cinco folds e benchmark
PERSISTENCIA_ASOF. A suíte não exercita classes da PR #18 em runtime (branch
diferente), não comprova ingestão real e não substitui testes no SHA integrado.

Na versão auditada de `tendencias_mercados.py` da PR #30, as chaves do
pareamento são apenas `pickup_entity_id + transportadora_id`. A ausência
de `descarga_entity_id` e `regime` no pareamento pode permitir comparações
com condições comerciais distintas. Exigir o conjunto completo de identidade
econômica e regressões no SHA reconciliado antes do aceite R01.

**Próxima ação executável:** negociar contrato do `edicao_sha256` a partir
do RAW de origem com a frente Logística, harmonizar a classificação dos termos
comerciais e executar backtest em dados licenciados, historizados e verificados.

## Continuidade — política de data comercial e republicações (21/10/2026)

A ponte quantitativa agora exige `data_referencia == data_publicacao` **no dia
local `America/Cuiaba`**, e não em UTC. A igualdade bloqueia republicação
de anúncio antigo em dia atual mesmo quando o campo `edicao_sha256` foi
preenchido; preserva corretamente publicações próximas de 00:00 UTC cujo
dia comercial em Mato Grosso ainda é o anterior.

**Limite importante:** igualdade de datas é condição necessária, não prova
que o texto original oferece frete atual. Prova de atualidade comercial no
RAW, direitos, origem e atestações independentes continuam sob
`fretes_adapter_whatsapp.py`/`fretes_atestacoes.py` da PR #18. Não transformar
o SHA arbitrário em atestação nem permitir publicações com base apenas nas
datas declaradas pelo emissor. O runner quantitativo permanece offline e
`publicavel=False`.
