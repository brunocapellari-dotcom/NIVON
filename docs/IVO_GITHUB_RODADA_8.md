# IVO — Rodada 8: governança de resultados e treinamento temporal

**Data-base:** 20/10/2026. **Status:** PR #7 em desenvolvimento; sem merge,
deploy, coleta de rede, custo novo, dados reais homologados ou permissão de
treinamento concedida.

## Constatação verificada sobre fontes oficiais

- A CONAB publica levantamentos e avaliações de safras com atualizações
  mensais, estimativas e revisões, não um fluxo de medições industriais
  individuais e imutáveis:
  https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras
- O IBGE LSPA apresenta estimativas para o ano civil completo e tem
  revisões mensais, que **não são volume produzido em cada mês**:
  https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9201-levantamento-sistematico-da-producao-agricola.html

Consequência: uma planilha chamada histórica ou final não basta para dizer
que seu valor é medição definitiva de produção. É necessário estabelecer
a política de verdade por cultura, ano, localidade, documento, método,
período de referência e versão publicada.

## Código introduzido

1. `ivo_elegibilidade_rotulos.py`:
   - `AtestacaoResultado` vincula uma `historico.Observacao` ao SHA da
     edição, hash exato da linha, documento de parecer, dois revisores
     distintos, autor do modelo, natureza, finalidade de treinamento,
     licença por operação e instante de aprovação.
   - Valida datas de referência, publicação, captura e aprovação; não
     aceita observações declaradas `ESTIMADO`, `INFORMADO`,
     `PROJETADO` ou inferências como verdade observada.
   - No caso de dados reais exige: dataset e source_id do catálogo,
     `enabled`, `collection_authorized` e
     `training_authorized` EXPLÍCITOS, e correspondente exato no
     `registro_snapshots`, com mesma fonte, SHA, data de publicação,
     data de coleta, prova declarada dos direitos e classe real.
   - Mesmo após passar esses checks, o estado é
     `CANDIDATO_REAL_COM_APROVACOES_DECLARADAS`, **não**
     `HOMOLOGADO`. Não comprova a autenticidade das assinaturas,
     a autorização jurídica do dataset ou a verdade material das
     afirmações. Não executa treino real.
   - Em laboratório somente `TESTE_*` com dados marcados `SINTETICO`,
     confirmação explícita e revisão declarada pode liberar a série.
   - **Vintages não são reduzidas ao último snapshot**: a sequência
     preserva cada versão histórica autorizada para reconstrução
     walk-forward na data de cada previsão. Um snapshot único
     atualizado introduziria look-ahead em revisões publicadas depois.

2. `ivo_benchmark_atestado.py`:
   - Requer pacote de labels sintéticos atestados e a autorização
     explícita do experimento antes de chamar
     `ivo_benchmark_ml.benchmark_ml_asof`.
   - Retorna hash do pacote, MAE/baseline e folds reconstruídos;
     proíbe entrada real, estimativa, projeção e autopromoção.
   - É prova de integração matemática e temporal, não prova de
     qualidade preditiva real ou de autorização de licença.

3. `config/ivo_politicas_rotulos.v1.json`:
   - Catálogo canônico de 11 fontes, cobrindo séries/levantamentos e
     progresso semanal CONAB, IBGE LSPA/PAM, INMET, ANA, ANP Diesel,
     MDIC e indicadores de abate de aves e suínos do IBGE.
   - Distingue projeção de safra, percentuais informados de plantio,
     dados por estação, pesquisas amostrais de revenda, indicadores
     de exportação e estatísticas pecuárias.
   - Todas as fontes mantidas `PENDENTE/BLOQUEADO` para rótulos
     homologados. Nenhuma permissão de coleta ou treino foi ativada.

4. `ivo_politicas_rotulos.py`:
   - Confere o catálogo acima contra os IDs e source_ids do
     `fontes_nivon_master.v1.json`, produz lista detalhada dos
     bloqueadores e garante `fontes_prontas_para_treino_real=0`
     até que exista um mecanismo externo de homologação.

5. Testes: `test_ivo_elegibilidade_rotulos.py`,
   `test_ivo_benchmark_atestado.py` e `test_ivo_politicas_rotulos.py`:
   fontes ausentes, direitos insuficientes, hash adulterado,
   revisores duplicados, consulta do ledger, revisão publicada
   posteriormente, safra/competência, mistura real/sintético,
   incompatibilidade de fonte e catálogo, proteção contra
   autopromoção e reconstrução temporal.

## Pendências executáveis em seguida

1. Investigar concretamente **quais datasets agrícolas fornecerão
   resultados de referência por safra/ano/região**, e documentar
   metodologia, finalização, revisões, atraso de publicação, licença e
   diferenças entre estimativa, medição e estatística consolidada.
2. Homologar e carregar pelo menos um histórico **REAL_AUTORIZADO** em
   ambiente de testes isolado, com hashes dos bytes, direitos por
   operação, registro de coleta e restauração do banco.
3. Criar o adaptador de truth por cadeia (ex.: safra agrícola,
   preços físicos, fretes anunciados, hidrologia), sem reutilizar
   automaticamente o mesmo rótulo ou a mesma frequência.
4. Executar o primeiro walk-forward real, mantendo os quatro eixos
   temporais e baseline independentemente validado.
5. Comprovar confiança em assinaturas externas do fluxo de revisão,
   segregação de poderes, custo cloud, observabilidade, backup e
   reversão. Somente depois considerar homologação e produção.

**Não realizado:** treino real, backfill, verificação criptográfica das
assinaturas de pessoas externas, testes dos extras opcionais instalados,
go-live ou qualquer cobrança.
