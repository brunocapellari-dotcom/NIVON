# NIVON — Auditoria de interoperabilidade Fretes PR #18 × Quant PR #20

**Referência:** 21/10/2026, fixture offline, sem dados reais.

## Histórico e corte de integração

- Branch Quant PR #20: `feat/quantitativo-validacao-asof-probabilidades-20261020`.
- HEAD Quant antes da integração: `734a4140bd1494e0ca09fc4004cb5c58749d9ea8`.
- HEAD da PR #18 incorporado: `d78e5618e81b28b4f1d17a5815775bea20b167bd`.
- HEAD Mercados da PR #21 incorporado no mesmo corte:
  `01aa3d6f14f14112af7d5efd10cee52ee869989e`.
- Merge de **três pais**: `f654d30bc1fa37d19ce8a76dbb33ddca0ee1584e`.
- Comparação de SHA dos blobs sobre os ancestrais apontou **18 arquivos
  alterados em Fretes**, **3 arquivos alterados em Mercados**, **zero
  conflitos de caminhos** e zero deleções. Os blobs vieram inalterados.
- Não foi feito merge em `main`, nem alteradas as branches PR #18 e PR #21.

[CI do merge f654d30 — #39698630683](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698630683):
**1.604 testes executados, zero falhas, cinco skipped**, teste principal
`validar-nucleo` SUCCESS.

## Verificação cross-module de código executado

`tests/test_fretes_quant_integracao_e2e.py` integra **funções reais**
de três módulos, com objetos `OfertaFrete` sintéticos:

1. `fretes_registros.consolidar_ofertas` recebe 26 anúncios de dois
   estabelecimentos/transportadoras em 13 dias; preserva os registros
   individuais, preço em `Decimal`, referência, lote e entidade; não cria
   média de frete por município.
2. `integracao_frete_quant.preparar_serie_frete_anunciado` exige
   identidade econômica completa. Os 26 registros misturados são
   recusados (não soma nem calcula mediana municipal). Selecionar a série
   da mesma entidade é operação **explícita** do fixture.
3. O schema consolidado da PR #18 **não fornece**
   `edicao_sha256` proveniente do RAW por registro; o Quant retorna
   `BLOQUEADO_SHA_EDICAO_AUSENTE`, 13 edições faltantes, série vazia,
   `asof_pronto=False`, `uso_preditivo_real_autorizado=False`.
4. O painel PR #18 que porta o método pareado da PR #30 gera um SHA
   **derivado da linha**, marcado `DIGEST_DERIVADO_NAO_PROVA_RAW`.
   Esse digest não pode ser promovido a autenticidade da origem.
5. `fretes_integracao_r01.tendencia_ofertas_pareadas` produz sinal
   **descritivo** dos mesmos pares e condições, com
   `publicavel=False`, `probabilidades_calibradas=None` e
   `direitos_publicacao_verificados=False`.
6. Alterar apenas `regime` PF/PJ ou `descarga_entity_id` bloqueia
   simultaneamente painel comercial e ponte Quant.
7. Teste separado injeta um SHA **de fixture, não autenticado** só para
   habilitar um ensaio sintético `rolling_origin` em 5 origens, com
   baseline persistência; comprova as métricas técnicas com
   `ganho_mae_baseline=0`, preservando `asof_pronto=False`,
   `prova_integridade_externa_pendente=True` e `publicavel=False`.

[CI do E2E — #39698943838](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698943838):
**1.610 testes executados, zero falhas, cinco skipped**.

## Contratos e bloqueios reais

**P0 — proveniência:** campo de hash SHA do RAW original ainda não flui de
um coletor autorizado por atestação independente até a linha `OfertaFrete`
e seu `consolidar_ofertas`. Nunca fabricar o SHA pelo preço, por JSON
pós-normalização ou pelo painel pareado. A checagem de formato não prova
origem, direito, veracidade ou disponibilidade point-in-time.

**P0 — PR #30:** seu `tendencia_frete_anunciado` ainda usa apenas
`(pickup_entity_id, transportadora_id)` no pareamento por dia, sem
`descarga_entity_id`/regime na chave. A PR #18 contém portas de painel
isolado com verificação conservadora por descarga, regime, pedágio,
produto/equipamento, **mas a PR #30 não foi reconciliada**. Issue #25
continua aberta. A árvore Quant importou código da PR #18, **não** o
código de PR #30.

**P0/P1 — dados e autorização:** fontes WhatsApp/integradores exigem acesso
lícito, evidência de direitos, resolução de entidades, atestação, captura
RAW, armazenamento/restore durável e avaliação histórica temporal sem
look-ahead. Os testes de CI são 100% sintéticos e **não autorizam** criação
de APIs, coleta real, publicação editorial, preços contratados ou
previsões calibradas.

A equipe integradora deve preservar os bloqueios ao conciliar PRs #18,
#20, #21, #30 e executar nova regressão integrada num SHA congelado.
