# NIVON — padrão cartográfico para o relatório semanal de plantio e colheita

**Status:** especificação editorial aprovada em conversa de 26/10/2026. **Não equivale a implantação operacional ou homologação de dados.** Este arquivo complementa `PADRAO_EDITORIAL.md`, sem alterar o Resumo Estratégico diário, que continua sendo outra publicação.

## Periodicidade e formato

- Publicação **toda terça-feira de manhã**, em separado do Resumo Estratégico do Agronegócio.
- Checar as divulgações de segunda-feira da **CONAB** e do **IMEA**: competência, safra, cultura, operação, abrangência territorial, cronograma e histórico.
- Uma combinação **cultura + operação** por mapa. Exemplo meramente estrutural: `SOJA — COLHEITA`, `MILHO — PLANTIO`, `ALGODÃO — PLANTIO`. Gerar tantos mapas quantas combinações tiverem dados válidos; **não supor que essas três operações ocorram todas na mesma semana**.
- A identidade visual segue o boletim aprovado: fundo claro, verde escuro, dourado, cartões, títulos concisos e leitura confortável no celular. Não acrescentar blocos não solicitados.

## Geografia e cores — regra obrigatória

1. Mapas estaduais reais, a partir da **malha IBGE das 27 UFs**, preservando limites e siglas. Geometria cartográfica não deve ser improvisada ou gerada livremente por IA.
2. Definir **uma única cor fixa por cultura**. **Todos** os estados com dado de plantio/colheita elegível no período possuem exatamente a mesma tonalidade de preenchimento daquela cultura.
3. Estados sem dado verificável para a combinação cultura/operação/safra devem ficar **cinza**; cinza **não** significa taxa de 0%.
4. **Jamais usar gradientes, saturação, mapas de calor ou tons distintos nos estados para indicar o percentual.**
5. Para cada estado elegível, apresentar sigla e **dois números de avanço**, com fonte e comparabilidade conferidas:
   - percentual da **safra atual 2026/27** em **verde-escuro**;
   - percentual da **safra passada 2025/26** em **laranja**, referente à mesma operação e a período comparável.
6. **A legenda inferior esquerda identifica somente a cor dos dois NÚMEROS**, não a cor de preenchimento dos estados. Não duplicar o total Brasil ou MT nessa posição.
7. Se uma das duas safras não tiver percentual estadual conferido, exibir `—` somente naquele campo ou omitir a comparação. Nunca completar o percentual com interpolação, outra cultura ou dado gerado por imagem.
8. O conjunto de estados coloridos é determinado **somente** por dados válidos da publicação; não usar listas fixas fictícias em produção.

## Quadros à direita

- Brasil (CONAB) e Mato Grosso (IMEA) somente quando os indicadores estiverem disponíveis na cobertura declarada.
- Em cada quadro: avanço **atual 2026/27**, **semana anterior da mesma safra**, **variação semanal em pontos percentuais**. Isso não deve ser confundido com o percentual da safra anterior (2025/26) que aparece no mapa.
- Preservar e distinguir datas de referência, publicação e coleta e a fonte de cada número.
- Quando comparar históricos por estado, parear mesma cultura, operação, unidade e janela da temporada agrícola.

## Aceite

- Conferir contornos das **27 UFs** e as respectivas siglas por malha vetorial IBGE, de maneira programática.
- Conferir que UFs elegíveis usam uma mesma cor **exata** em cada mapa; UFs ausentes cinza.
- Conferir que a legenda do mapa referencia **apenas** os dois percentuais/safras.
- Reprovar a publicação se percentuais, estágio agrícola ou estados coloridos não forem justificáveis por dados oficiais.
- Validar visualmente PDF e imagem, inclusive legibilidade no celular, antes de publicar.

**Exemplos de layout não são fonte de dados.** Nenhum valor ou agrupamento de UF de arte demonstrativa poderá alimentar a edição semanal.
