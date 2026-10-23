# NIVON — Auditoria e plano executivo da Inteligencia Pecuaria

Data de corte: 2026-10-20. Base: feat/fontes-historicas-motores-cientificos-20261019 (PR #9 empilhada sobre PRs #3/#1). Branch: feat/pecuaria-inteligencia-20261020.

## Evidencia e maturidade

- Bovinos: frentes existentes BOI e BEZERRO registram rendimento de carcaca, relacao de troca e identidade contábil de rebanho; nenhum ciclo completo ou preco previsto homologado.
- Aves e suinos: normalizador offline para SIDRA 1094 / 1093 em cadeias_adicionais.py; peso medio de carcaca, simulacoes de custo/margem, alertas qualitativos, backtest CAGR genérico. Nenhuma serie oficial de abate foi persistida e versionada para estas frentes por esta branch.
- Todas as tres cadeias: direitos, esquema historico da fonte e validacao de dados reais nao concluidos; nenhum scheduler, distribuicao comercial ou sinal probabilistico autorizado.
- A infraestrutura catalogada nao constitui captura de dados efetiva. Revisoes anteriores a uma primeira coleta nao podem ser reconstruidas como vintages de publicacao sem edicoes historicas autenticas.

## Entregas desta branch

- pecuaria_ciclos.py: simulador bovino por arroba de CARCACA, custo de reposicao e ciclo de engorda; simulador frango por ave alojada; simulador suino em terminacao; ração por formulacao explicitamente identificada.
- pecuaria_mercados.py: series separadas para BOI_GORDO (BRL_ARROBA_CARCACA), BEZERRO (BRL_CABECA), FRANGO_VIVO e SUINO_VIVO (BRL_KG_VIVO); timestamp com fuso, fonte, praça, hash, publicacao e coleta; resolucao de revisoes por ultimo vintage disponivel no corte.
- Tendencia OBSERVADA: mediana de tres variacoes homomes interanuais exigindo 15 meses contiguos. Nao confundir com PREVISAO.
- Baselines para futuro: walk-forward mensal comparando naive sazonal anual contra persistencia mensal; exigir >=12 folds, availability em cada cutoff e erro mensurado. Continuam nao homologados: nenhum intervalo de confianca, probabilidade, ensemble ou receita projetada.
- Nenhum modulo reimplementa coleta ou altera o contrato editorial do briefing.

## Plano de dados — fontes canonicas, sem nova fonte da verdade duplicada

Catalogos de operacao a preservar: config/fontes_nivon_master.v1.json, config/rotas_coleta.v1.json e config/matriz_produtos_indicadores.v1.json. Identificadores abaixo devem ser reutilizados e corrigidos, NAO duplicados.

| Prioridade | Fonte/dataset | Uso por cadeia | Trabalho objetivo | Gate |
| --- | --- | --- | --- | --- |
| P0 | IBGE SIDRA 1092 / IBGE_ABATE | bovino: cabecas, carcaças, sexo e tipo por recorte disponivel | confirmar API variaveis/periodos e amostras reais; normalizar por BR/UF, civil/trimestre | publicar/armazenar permitido por operacao |
| P0 | IBGE SIDRA 1093 / IBGE_ABATE_SUINO_1093 | suinos: abate inspecionado e carcaça | confrontar API, variaveis, unidades e revisoes | parser OFFLINE nao significa conector |
| P0 | IBGE SIDRA 1094 / IBGE_ABATE_FRANGO_1094 | frango: abate inspecionado e carcaça | mesmo processo, unidades KG/T explícitas | nao extrapolar a plantel |
| P0 | IBGE PPM / IBGE_PPM | rebanho bovino/suino e galinaceos | registrar estoque em referencia anual, especie/categoria/UF/municipio quando suporte | PPM nao e fluxo de abate; galinaceos nao sao so frangos de corte |
| P0 | MAPA PGA-SIGSIF / catalogo existente | tres especies: abates SIF e categorias | mapear relatorios CSV, modalidade publica, diferenciar cobertura MAPA do IBGE | nao somar SIF e IBGE |
| P0 | MDIC Comex Stat / MDIC_COMEX_NCM | carne bovina, aves, suina e cortes | NCM versionada por ano, sentido, destino, volume, FOB, revisoes | peso liquido de produto != equivalente carcaca |
| P1 | CEPEA_BOI / CEPEA_FISICO, SCOT_PECUARIA | boi, bezerro, aves e suinos quando licenciados | obter direitos e metadados de series, praca, regime e periodicidade | uso comercial/redistribuicao bloqueado ate aprovacao |
| P1 | EMBRAPA CIAS, ABPA_FRANGO_SETOR, ABPA_SUINO_SETOR | dietas, conversao, custos e balancos setoriais | integrar metodologias, datas e autorizacoes de cada publicacao | sem tratar indicadores como registro individual |
| P1 | USDA PSD / FAO FAOSTAT | comparacao de oferta, demanda e comercio internacional | normalizar unidades, ano comercial e series por revisao | coerencia temporal, metodologia |
| P1 | MAPA/WOAH sanidade | febre aftosa, influenza aviaria, PSC/PSA e restricoes | registrar evento, confirmacao, incidencia, geografia, medida oficial e revogacao | alerta nao vira embargo ou perda quantificada |
| P1 | milho, farelo soja, diesel, frete do nucleo NIVON | custos variaveis das tres cadeias | alinhar mesma praca, referencia, qualidade, unidade, prazo | nao converter cotacao em compra executada |

Fontes oficiais para verificacao:
- https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ (1092 / 1093 / 1094)
- https://dados.agricultura.gov.br/pt_BR/dataset/servico-de-inspecao-federal-sif
- https://www.gov.br/agricultura/pt-br/assuntos/inspecao/produtos-animal/sif
- https://www.embrapa.br/en/web/suinos-e-aves/cias/custos/icpsuino
- https://comexstat.mdic.gov.br/
- https://apps.fas.usda.gov/psdonline/

## Modelos futuros, SEM prometer resultados sem series reais

1. **BOVINO**: coortes vaca-matriz/cria/recria/engorda, nascimentos, mortalidade, retencao/descarte de femeas, oferta futura por lag biologico e cenarios de confinamento/pasto. Exigir fontes reais para pesos e eventos sanitarios; evitar transformar PPM anual em rebanho mensal ficticio. Precos boi/bezerro por praca, B3 e spread/reposicao.
2. **FRANGO**: alojamento de pintos, ciclo curto e idade de abate, mortalidade, peso medio, conversao por fase, milho/farelo e capacidade frigorifica. Validar dados primarios de alojamento ou usar somente cenario condicional, nunca estimar plantel com abate de forma determinista.
3. **SUINO**: matrizes/coberturas, partos, desmamados, creche/terminacao, perdas e defasagens especificas, indices tecnicos e exportacoes. Rebanho anual nao e animais disponiveis imediatamente.
4. **MERCADO**: modelos por especie, unidade e praca; sazonal naive, persistencia, regressao com insumos e mercado externo, quantis e classificacao ALTA/BAIXA/ESTAVEL/INDETERMINADA somente apos walk-forward com datas de disponibilidade e dados suficientemente longos. Relatar MAE/RMSE, ganho sobre baseline, cobertura e calibracao; vetar probabilidades sem calibracao externa.
5. **INTEGRACAO**: contratos consumiveis pelo IVO, comercio, mercado e logistica com direitos, fonte, 4 datas (competencia, referencia, publicacao, coleta), unidade, UF/praca, vintage, hash, status observado/inferido/estimado/projetado. Editorial agricola nao deve receber pecuaria automaticamente.

## Gatilhos de homologacao

- Prova de direitos para leitura/coleta/armazenamento/transformacao/redistribuicao por dataset.
- Fixture real com metadados e layout legitimamente permitido, backfill e comprovacao de revisoes.
- Tres extracoes em datas de atualizacao diferentes, persistencia e backup/restauracao, idempotencia, logs.
- Residuos fisicos/biologicos explicados; previsao walk-forward com baseline e nao-leakage.
- Revisor independente e checks CI; sem CI verde e amostra real => CODE_TESTED_SYNTHETIC_ONLY.
- Sem deploy, agendamento, merge, envio WhatsApp, custo ou novos direitos presumidos.

Reproduzir testes sinteticos: PYTHONPATH=src python -m unittest tests.test_pecuaria_ciclos tests.test_pecuaria_mercados


## Continuidade 20/10/2026 — contrato JSON SIDRA offline

### Evidências públicas de metodologia (sem confirmação de API de valores)
- Página de tabelas IBGE: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ — 1092 bovinos, 1093 suínos, 1094 frangos; dados mensais **dentro** da pesquisa trimestral, não somar total de trimestre e meses.
- Metodologia IBGE: https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html — universo do abate **formal** sob inspeção federal, estadual ou municipal; abate informal não é estimado nessa pesquisa.
- Norma pública MAPA sobre SIDRA 1092: https://www.gov.br/agricultura/pt-br/assuntos/sustentabilidade/planoabc-abcmais/abc/sinabc/plataforma-abc/capitulos-portugues-metodologia/capitulo-02-informacoes-sobre-a-metodologia-do-painel-de-terminacao-intensiva-ti.pdf — diferencia animais/carcaças, mês 1/2/3, sexo/categoria e inspeção; este contrato **não** substitui missing/censura por zero.
- Errata histórica IBGE referente ao SIDRA 1094, 05/05/2023, revisões 2008–2022: https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9203-pesquisas-trimestrais-do-abate-de-animais.html — snapshot atual não é evidência de vintages retroativos.

### Artefatos
- \`src/nivon/pecuaria_sidra_abate.py\` — parser de bytes JSON salvo localmente, sem rede. Exige mapeamento EXPLÍCITO de DnC para territorio/periodo/variavel/referencia_temporal/inspecao e rebanho apenas em bovinos, mapa de IDs de variáveis e IDs de categorias TOTAL. Detecta dimensão não declarada, variável porcentual, unidade incompatível, soma indevida de categorias, períodos não trimestrais e duplicata; censuras são separadas, nunca zero. Retorna observações canônicas, pares incompletos, SHA256 real do bruto, edição declarada e status não homologado.
- \`tests/test_pecuaria_sidra_snapshot.py\` — cenários totalmente sintéticos. IDs 9999/8888 e códigos 0 de total são INVENTADOS para prova de contrato; **não representam códigos oficiais do IBGE**.
- \`config/motores_inteligencia.v1.json\` e \`registro_motores.py\` — parser incluído nas frentes BOI, FRANGO e SUINO, com execução operacional ainda desligada.
- Dataset existente \`IBGE_ABATE\` corresponde à tabela bovina 1092 em escopo genérico; **não criar dataset 1092 duplicado** antes de reconciliação pelo diretor da plataforma. \`IBGE_ABATE_FRANGO_1094\` e \`IBGE_ABATE_SUINO_1093\` são os IDs canônicos preexistentes.

### Validação REAL ainda pendente — limite material
- As URLs \`apisidra.ibge.gov.br/values/t/1092\`, 1093 e 1094, e o serviço v3 de metadados, não puderam ter resposta aberta/verificada neste ambiente. Não se atribuir IDs verdadeiros de variáveis/categorias, ordenação D1C...DnC ou unidade MN exata sem capturar ao menos uma amostra autêntica.
- Para homologar: resolver endpoint HTTPS real e direitos; arquivar somente material autorizado fora do repositório público; registrar prova de download e datas de publicação/coleta, inclusive horário e fuso; confirmar layout/códigos e unidade por espécie; adicionar fixture de estrutura real saneada sem dados sensíveis; executar parser no arquivo real; reconciliar totais nacionais por trimestre com PDF/publicação IBGE; executar retrospectivas e análise de revisões históricas.
- Não somar N1 (Brasil) com N3 (UF) nem subcategorias com totais. Não tratar código de missing como zero. O total físico brasileiro e o total das UFs podem divergir por confidencialidade e revisões: diagnosticar, não corrigir sem fonte.
- A assinatura \`status_fonte\`/\`operacoes_autorizadas\` é um gate explícito, não atestado de licença. PENDENTE e falta de direito bloqueiam leitura/armazenamento. Nenhuma fonte, cron ou publicação habilitada.

**Próxima tarefa executável:** verificar resposta de metadados/valores oficiais SIDRA e direitos aplicáveis, mapeando IDs e categorias por tabela/edição; usar arquivo autêntico autorizado para teste e guardar hash/vintage. Depois ligar observações verificadas a séries revisáveis com corte de publicação e modelos por espécie. Sem essa prova, o parser fica CODE_TESTED_SYNTHETIC_ONLY.

## Continuidade 21/10/2026 — correção crítica de cobertura territorial SIDRA

### Evidência pública e limite de confiança
- Fontes oficiais: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ e https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html — 1092 bovino, 1093 suíno, 1094 frango e resultados do 2º trimestre de 2026.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1092/numero-informantes-quantidade-peso-total-carcacas-bovinos-abatidos-mes-trimestre-tipo-rebanho-tipo-i — mostra 27 localidades UF para 1092.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1093/numero-informantes-quantidade-peso-total-carcacas-suinos-abatidos-mes-trimestre-tipo-inspecao — mostra 26 localidades UF para 1093.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1094/numero-informantes-quantidade-peso-total-carcacas-frangos-abatidos-mes-trimestre-tipo-inspecao — mostra 26 localidades UF para 1094.
- Não foi identificada oficialmente a UF ausente em 1093 e 1094, nem sua cobertura ao longo do histórico. Não interpretar ausência como zero ou tratar contagem do catálogo como lista homologada.

### Correção executada
- Auditar por 27 UFs invariáveis era incorreto. O algoritmo de auditoria BR x UF agora exige contrato explícito por competência com especie, tabela, lista nominal de UFs, fonte de evidência e SHA256 de metadados.
- Sem cobertura explícita, retornar COBERTURA_NAO_VERIFICADA, sem soma e sem resíduo.
- Com lista válida, comparar apenas cobertura exatamente coincidente; nenhuma ausência ou excedente é ajustada; inconsistência retorna INCOMPLETO_SEM_IMPUTACAO ou COBERTURA_DIVERGENTE_SEM_IMPUTACAO.
- Cobertura declarada pode ser diferente a cada competência; comparação não garante homologação, que permanece falsa. As fixtures 25/26/27 UFs são artificiais, sem supor qual UF real faltaria.

### Bloqueio técnico
- Tentativas diretas de acessar os serviços oficiais servicodados.ibge.gov.br/api/v3/agregados/{id}/metadados e apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y não conseguiram recuperar JSON. O ambiente de execução local também não resolveu os hosts oficiais via DNS.
- Não foram confirmados IDs oficiais de variáveis/categorias nem a estrutura exata DnC dos resultados de API, tampouco direitos para coleta operacional. Não declarar histórico real ou previsão homologada.

**Próxima ação:** obter uma amostra oficial autêntica e permitida por espécie, validar metadados e listas de localidades por referência, executar parser, reconciliar totais e arquivar SHA e datas antes de backfill/agendamento.

## Continuidade 21/10/2026 — histórico 1997–1999 e vintages bitemporais

### Correção de alcance histórico
- O SIDRA 1092, 1093 e 1094 começa no 1º trimestre de 1997 (consultar https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ ). Os parsers novos rejeitavam erroneamente anos anteriores a 2000.
- Corrigidos o formato TRIMESTRE em src/nivon/cadeias_adicionais.py e o parser em src/nivon/pecuaria_sidra_abate.py para aceitar os anos de 1997 a 1999 sem liberar períodos anteriores à origem da pesquisa.
- Testes sintéticos de 1997-T1 e 1999-T4, além de bloqueio de 1996.

### Motor novo: vintage SIDRA
- Adicionado src/nivon/pecuaria_sidra_vintages.py, consumindo APENAS snapshots do parser offline e reconstruindo a série conhecida conforme o corte temporal (publicação e coleta).
- Coleta retrospectiva realizada agora não cria conhecimento no passado: dados não entram em um corte anterior ao momento real de coleta.
- Observações de abate são mantidas por espécie, tabela, UF, competência e indicador; revisão mais recente exige data de publicação posterior, com SHA e diferenças registradas.
- Censuras explícitas do snapshot funcionam como tombstones, impedindo que valor anterior continue como atual após ser censurado. Ausência em extrato parcial não é interpretada como zero ou censura.
- Impede duplicações, mudança de valor sem nova publicação, hash inconsistente, mistura de espécies, fuso ausente, excesso de linhas e status artificial de homologação.
- A saída permanece HISTORICO_OFFLINE_VINTAGES_NAO_HOMOLOGADO, com amostra_real_homologada=false, metadados_publicacao_verificados=false e previsao_homologada=false.
- Registro de motor incluído nas frentes BOI, FRANGO e SUINO em config/motores_inteligencia.v1.json e na allowlist de src/nivon/registro_motores.py. Sem coleta, armazenamento físico, cron, deploy ou comunicação WhatsApp.

### Evidências
- Testes 100% sintéticos: tests/test_pecuaria_sidra_snapshot.py e tests/test_pecuaria_sidra_vintages.py; também permanecem os testes de qualidade territorial.
- GitHub Actions https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39593598730: 1.226 testes, zero falhas, 5 ignorados, gates compileall, validação de catálogo e registro de motores aprovados.
- A documentação da API oficial permanece em https://servicodados.ibge.gov.br/api/docs/agregados?versao=3, mas endpoints de valores e metadados 1092/1093/1094 continuam não acessíveis neste ambiente. Não transformar inferências do catálogo secundário em IDs oficiais.

### Próximas prioridades
1. Obter amostra REAL e autorizada da API v3 para cada espécie e validar IDs oficiais, unidades, classificações, cobertura territorial e datas; confrontar com SIDRA e publicações do IBGE.
2. Registrar comprovante de proveniência, modificações oficiais e revisões (vintage autêntico); somente então permitir REAL_SAMPLE_TESTED em avaliação independente.
3. Definir persistência histórica append-only a partir do contrato já testado e começar análises de ciclo bovino/aves/suínos com validação temporal. Nenhuma probabilidade ou preço sem evidência.

## Continuidade 21/10/2026 — cronologia fail-closed SIDRA

- Auditoria da branch confirmou parser SIDRA e motor bitemporal offline com CI anterior verde. A API IBGE v3 de metadados e a API de valores SIDRA não responderam no navegador de pesquisa e na rede do container (DNS): nenhum JSON real foi obtido.
- Evidência externa, NÃO HOMOLOGADA de metadados: https://quantilica.com/fish/variaveis/284 e https://quantilica.com/fish/tabelas/1092/numero-informantes-quantidade-peso-total-carcacas-bovinos-abatidos-mes-trimestre-tipo-rebanho-tipo-i indicam 284 como animais abatidos nas tabelas 1092/1093/1094, mas não autorizam preencher mapas oficiais automaticamente nem inferir unidades e categorias de extrato real.
- Vulnerabilidade corrigida em src/nivon/pecuaria_sidra_vintages.py: anteriormente observação manual com referência arbitrária ou publicação anterior ao encerramento de um trimestre poderia atravessar a seleção as-of; o motor agora exige fim de trimestre canônico, origem >= 1997, publicação posterior ao encerramento para valores e censuras.
- Validação temporal harmonizada em src/nivon/pecuaria_sidra_abate.py: a publicação precisa ser >= 00:00 UTC do dia posterior ao fim da competência. Este gate não autentica o timestamp, apenas barra um intervalo objetivamente impossível.
- Testes adversariais novos em tests/test_pecuaria_sidra_vintages.py e tests/test_pecuaria_sidra_snapshot.py: referência 2026-T2 registrada em setembro, registro de 1996, publicação em junho antes do fim do trimestre, censura antecipada e controles positivos de 1997.
- Quatro datas canônicas preservadas nos resultados ou objetos: competência, referência, publicação e coleta. Publicação/coleta são DECLARADAS por operador, ainda não comprovadas com divulgação oficial histórica; não promover vintages nem classificação para observado sem evidência.

**Pendências em ordem:** (P0) amostras autênticas API v3/values das 3 tabelas e mapeamento por documentação oficial; (P0) homologação de licença/proveniência de aquisição e publicação, comparando o período do extrato à divulgação original; (P1) reprodução real BR x UFs por cobertura efetiva e revisão; (P1) persistência append-only e backtesting PIT por espécie. Sem merge, deploy, cron, envio ou preço real.

## Continuidade 21/10/2026 — sinais especiais da API SIDRA

### Evidência técnica e correção
- A documentação CRAN do sidrar (https://cran.r-project.org/web/packages/sidrar/vignettes/Introduction_to_sidrar.html) distingue: `-` = ZERO ABSOLUTO; `X` = dado INIBIDO; `..` = NÃO APLICÁVEL; `...` = NÃO DISPONÍVEL. Não usar pacotes que convertem todos automaticamente em NA sem preservar token original.
- O antigo parser de abate confundia `-` com NA e o eliminava da série de observações; isso é erro de classificação, não apenas limitação de cobertura.
- Corrigida src/nivon/pecuaria_sidra_abate.py: `-` convertido explicitamente em zero observacional, SEM imputação; X/../... seguem sem valor e NÃO viram zero. O retorno preserva `marcadores_sidra` com símbolo e significado por UF, trimestre e indicador, sob o SHA256 do bruto.
- Compatibilidade preservada com `linhas_indisponiveis` e `pecuaria_sidra_vintages`; teste ponta a ponta prova que zero absoluto continua valor zero e X mantém censura, sempre respeitando o corte de coleta.
- Testes adicionais em tests/test_pecuaria_sidra_snapshot.py para `-`, `X`, `..`, `...`, mistura de valor zero e censura e trânsito para consulta temporal.

### Limites de evidência
- A semântica dos símbolos foi verificada com referência técnica externa CRAN, não com uma amostra autenticada das tabelas 1092/1093/1094; a homologação oficial ainda precisa de resposta real e validação por tabela.
- Nenhum coletor/cron, persistência, reclassificação editorial ou série real foi ativado. O estado dos motores continua CODE_TESTED_SYNTHETIC_ONLY.
- Próximo gate P0: capturar um response real autorizado SIDRA ou Agregados v3 para cada espécie, conferir dimensões, códigos, unidade, sinais especiais, direitos e datas de publicação; registrar hash e validar as revisões por vintage.

## Continuidade 21/10/2026 — arquivo local append-only de evidencias SIDRA

### Decisão técnica
- Documentação oficial de Agregados IBGE v3: https://servicodados.ibge.gov.br/api/docs/agregados?versao=3 distingue endpoints de metadados, periodos, localidades e valores. Esses quatro conjuntos sao provas independentes a registrar antes de homologar dados.
- Tabelas SIDRA 1092 (bovinos), 1093 (suinos) e 1094 (frangos) e abrangencia formal de inspecao constam na documentacao do IBGE: https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html.
- O IBGE comunicou em 05/05/2023 a revisao historica da 1094 referente a 2008-2022. Sem vintages coletados ANTES dessa revisao, nao se deve simular retrospectivamente a primeira edicao.

### Código e isolamento
- Novo src/nivon/pecuaria_sidra_arquivo.py: somente recebe bytes previamente obtidos; NAO realiza HTTP, downloads, cron, deploy ou distribuicao.
- Arquivo SQLite LOCAL selecionado pelo operador; guarda payloads binarios de valores e metadata, URLs HTTPS estritamente vinculadas ao ID de tabela, datas declaradas, SHA-256 de cada payload e status ARQUIVADO_NAO_HOMOLOGADO.
- O ID do objeto de metadados deve coincidir com a tabela no URL de metadados, na URL de valores e na especie selecionada. Um ID divergente falha fechado.
- Duas triggers SQLite impedem UPDATE e DELETE pelas operacoes normais da aplicacao; INSERT OR IGNORE com UNIQUE fornece idempotencia. Administrador com acesso ao SQLite pode modificar banco e triggers: NAO qualificar como WORM ou armazenamento criptograficamente imutavel.
- Recuperacao verifica novamente os hashes dos dois blobs e sinaliza corrompimento, mas SHA-256 e host declarado NAO comprovam origem HTTP real.
- LEITURA e ARMAZENAMENTO requerem permissoes explicitas de status_fonte. Ausencia ou status pendente bloqueiam escrita. Nao criar banco sob o repositorio publico nem inserir respostas restritas em CI.
- Testes sinteticos em tests/test_pecuaria_sidra_arquivo.py cobrem roundtrip, idempotencia, edicoes por coleta, 3 especies, triggers, alteracao maliciosa, direitos, URLs host/tabela, JSON, cronologia e limites. Dados e metadados sao MOCKS, nao capturas IBGE reais.

### Contrato de maturidade
- O arquivo nao faz prova de autenticidade de datas de publicacao nem coleta. Exibe dados_reais_verificados=false, timestamps_autenticados=false e previsao_homologada=false. O motor de vintages continua independente e nao recebe nenhum registro automaticamente.
- Para passar a amostra real: obter HTTP 200 autentico via fonte oficial, guardar URL exata, response headers e timestamp de captura auditavel fora deste componente, validar metadados, categoria TOTAL, unidade, variavel e cobertura, obter licenca/proveniencia e executar os testes reais. Gravar apenas material permitido.
- P0 ainda bloqueado: acesso a payload oficial 1092/1093/1094. P1 avancou somente no mecanismo LOCAL de armazenamento de evidencias; sem persistencia operacional, sem backfill historico e sem simulacao de vintages anteriores.

## Continuidade 21/10/2026 — unicidade e conflito de capturas

### Falha corrigida
- O arquivo SQLite anteriormente indexava (especie,tabela,url_valores,url_metadados,coleta,hash_valores,hash_metadados) e aplicava INSERT OR IGNORE. Duas capturas com mesmo instante declaradamente coletado mas diferentes hashes ou datas de publicacao podiam coexistir e causar ambiguidade ou falsa idempotencia.
- src/nivon/pecuaria_sidra_arquivo.py agora usa indice unico de identidade (especie,tabela,url_valores,url_metadados,coleta_declarada), valida previamente publicacao e ambos hashes em repeticoes, e recusa colisao divergente com DadoInvalido. Capturas de outro instante continuam podendo representar novas edicoes. Isto nao comprova autenticidade de timestamp.
- O arquivo existente criado com o esquema antigo agora é detectado via PRAGMA index_list/index_info, falhando fechado. Migracao auditada (backup, reconciliacao de chaves, verificacao de hashes, plano de rollback) e requisito explicito antes de usar banco legado; nao alterar tabelas historicas automaticamente.
- Novos testes sinteticos em tests/test_pecuaria_sidra_arquivo.py demonstram idempotencia estrita, conflito de publicacao, conflito de ambos payloads, novas coletas legitimas, indice UNIQUE e bloqueio de esquema legado.

### Pesquisa de fonte — controle de proveniencia
- Retentativas nesta rodada de GET metadados https://servicodados.ibge.gov.br/api/v3/agregados/1092/metadados e valores https://apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y falharam na rede local com Temporary failure in name resolution; o navegador web tambem informou endpoints inacessiveis. Nao existe payload oficial verificado.
- Fontes secundarias (nao homologadas) identificam variaveis candidatas 284 (Animais abatidos) e 285 (Peso total das carcacas): https://quantilica.com/fish/variaveis/284 e https://dbfloja.com.br/ferramentas/radar-abate. Nunca aplicar esses IDs como mapeamento aprovado sem metadados oficiais da tabela, unidade e periodo.
- O arquivo local permanece sem captura oficial, sem prova de publicacao historica e sem ativacao de coleta, backfill ou previsao. IDs, categorias e layout sao pendencias P0.

**Proxima acao P0:** obter response oficial autenticavel, aferir hash, timestamps, layout DnC, categoria TOTAL, unidades e direitos por especie; entao validar normalizador contra fixture real e anotar divergencias. **Proxima acao P1:** documentar migracao controlada de banco local legado se houver material efetivamente armazenado. Sem merge/deploy/cron/custo.

## Continuidade 21/10/2026 — ponte offline arquivo → parser → vintage

### Avanço implementado e verificável
- Os endpoints públicos de metadados Agregados v3 para 1092, 1093, 1094 e o endpoint apisidra /values/t/1092 continuaram inacessíveis ao ambiente web nesta rodada; isto não prova indisponibilidade da API na origem.
- Falha preexistente: `recuperar_pacote_sidra_offline` só retornava bytes/hash/espécie, não URLs nem publicacao/coleta declaradas. Consumidores teriam de reintroduzir timestamps manualmente, enfraquecendo a cadeia de custódia e o corte as-of.
- Em `src/nivon/pecuaria_sidra_arquivo.py`, a recuperação agora devolve URLs declaradas, datas de publicação/coleta, ID da captura e blobs, sempre conferidos contra espécie/tabela, HTTPS e SHA-256 antes da interpretação do JSON. A escrita continua não operacional.
- Defeito adicional corrigido: abrir um banco SQLite com schema legado anteriormente executava CREATE TRIGGER IF NOT EXISTS antes de recusar a migração. O novo fluxo verifica o índice legado **antes** de qualquer DDL. Requer migração humana auditada do banco legado; não altera nem destrói registros.
- Novo `src/nivon/pecuaria_sidra_pacote.py`: `normalizar_captura_arquivada_sidra` usa bytes e timestamps recuperados do próprio arquivo, exigindo direitos e contratos DnC/variáveis/totais explícitos. Confere novamente hash do parser com hash dos bytes arquivados; recusa mistura de espécie e tabela.
- A ponte é registrada para BOI, FRANGO e SUINO em `config/motores_inteligencia.v1.json` e na allowlist de `registro_motores.py`; os estados de ativação/agendamento continuam todos false.
- `tests/test_pecuaria_sidra_pacote.py` usa SOMENTE payloads fictícios e cobre recuperação de horários, hashes e URLs, fluxo completo SQLite→parser→vintage, corte temporal, espécie cruzada, direitos, variáveis não verificadas, tampering e legado sem efeitos de DDL.

### Distinção de estados e próximos gates
- SHA-256 comprova integridade dos bytes **desde sua captura/arquivamento**, não a autenticidade HTTP ou proveniência externa. O campo `identidade_arquivo_verificada=true` significa apenas integridade/identidade LOCAL; `amostra_real_homologada=false`, `mapa_dimensional_homologado=false`, `resposta_http_autenticada=false`, `timestamps_autenticados=false`, `coleta_real_executada=false` e `previsao_homologada=false` permanecem falsos.
- Para homologar são necessárias respostas oficiais autênticas com headers/horário de aquisição, verificação de schema e variáveis/categorias, regras de direito de acesso e armazenamento, comparação oficial BR/UF e aferição independente de revisões históricas. Nenhuma API real foi conectada ou ativada.
- P0 pendente: acesso e teste da resposta real 1092/1093/1094. P1 entregue somente em código/testes de armazenamento e integração local. Sem merge, deploy, custos ou envios.

## Continuidade 21/10/2026 — recuperação estritamente read-only do arquivo SIDRA

### Falha corrigida no arquivo SQLite
- O módulo src/nivon/pecuaria_sidra_arquivo.py usava `_abrir` com `sqlite3.connect` e `executescript(_SCHEMA)` mesmo em `recuperar_pacote_sidra_offline`. Isso poderia criar o arquivo caso estivesse ausente e reconstruir triggers durante uma consulta, introduzindo efeitos colaterais em uma operação destinada apenas à leitura.
- A abertura passa a distinguir explicitamente somente_leitura. Em leitura, exige arquivo preexistente e índice canônico; usa URI `file:/...?...mode=ro`, sem executar DDL nem CREATE TRIGGER. Em escrita, conserva o fluxo transacional, validação de legado e idempotência existentes.
- O suporte a URI é construído com pathlib Path.resolve().as_uri(), sem interpolar parâmetros do usuário em SQL, e continua rejeitando arquivo/parent symlink e diretórios inválidos. Não representa proteção absoluta contra acesso externo de administrador ou alteração de arquivos.
- Os testes test_leitura_inexistente_nao_cria_banco, test_leitura_nao_reconstroi_trigger_ausente, test_leitura_banco_legado_nao_executa_ddl e test_leitura_id_ausente_nao_cria_ou_edita verificam inexistência, versionamento do schema e ausência de efeitos colaterais da leitura.
- CI comprovado https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698730650: 1.265 testes executados, 0 falhas, 5 ignorados. Fixtures são 100% sintéticas.

### Estado das fontes e próxima prioridade
- Consultas diretas nesta rodada a https://servicodados.ibge.gov.br/api/v3/agregados/1092/metadados, /1093/metadados, /1094/metadados e ao serviço https://apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y não retornaram JSON utilizável no navegador. Não provar indisponibilidade da API na origem.
- Os serviços metadados, períodos, localidades e variáveis são contratos distintos da API Agregados v3, segundo estudo técnico: https://www.scielo.br/j/eb/a/yzWLzKTbKMkxgsZ9vYypPCv/?lang=pt. A primeira validação com payload oficial continua P0.
- Próximo passo técnico: captura limitada e autorizada de dados reais fora do runner restrito, com verificação da resposta HTTPS, identificadores, categorias, unidades, períodos, localidades e direito de armazenamento; só depois processar arquivo e produzir série real. Nenhuma coleta automática, registro operacional ou promoção de maturidade foi ativada.

## Lote consolidado 22/10/2026 — implementação multi-etapas sem microcomandos

**Prioridade definida:** P0.1 sondagem HTTPS; P0.2 fluxo de normalização de arquivos locais; P0.3 lote das três cadeias; P1.4 transações e vintages; P1.5 auditoria de qualidade; P1.6 interface de execução, documentação e CI. O runbook completo é `docs/RUNBOOK_SIDRA_PECUARIA_LOTES_20261022.md`.

- `pecuaria_sidra_sondagem.py`: sondagem opt-in apenas dos hosts oficiais IBGE, sem redirects/proxy, timeouts e limites de bytes; modo sem rede gera plano; HTTP real segue PENDENTE.
- `pecuaria_sidra_lote.py`: pré-valida 1-24 capturas, IDs de tabela, formatos, datas e variáveis explicitamente mapeadas, gera observações por espécie e vintage temporal, audita qualidade e emite resumo JSON; todas as evidências permanecem NÃO HOMOLOGADAS.
- `pecuaria_sidra_arquivo.py`: `arquivar_lote_sidra_atomico` faz INSERT transacional no SQLite local, recusa divergências no mesmo instante de coleta e reverte todas as inserções do lote no erro; replay idêntico é idempotente. Direitos seguem declarativos e devem ser homologados fora do software.
- `pecuaria_sidra_operacao.py`: CLI com manifesto 1.0 e referências a JSON locais, base-dir e corte timestamp, `--confirmar-direitos` obrigatório; dry-run padrão; `--gravar --banco` explícitos. Proibição de path traversal/symlink e contrato malformado.
- Testes novos `test_pecuaria_sidra_lote_integrado.py` e `test_pecuaria_sidra_operacao_cli.py`: E2E 3 espécies, 2 vintages, priorização da data real de coleta, dry-run, commit e rollback SQLite, reprocessamento, schema e direitos, sondagem simulada, JSON/HTTP inválidos e execução da CLI em processo separado.
- Módulos de processamento offline incluídos no registro de BOI/FRANGO/SUINO; `scheduled_enabled=false`, `operational_enabled=false`, `inputs_reais_homologados=false` e `previsao_homologada=false`.
- CI final https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891228332 : 1.285 testes, zero falhas, cinco ignorados; validação de registro, compilação e conjunto integrado passaram.

**Não realizado/bloqueado:** a API oficial de metadados e valores de 1092/1093/1094 não pôde ser acessada neste ambiente. Não existem amostras autênticas, licença validada, coleta automática, histórico real, previsão calibrada nem publicação. Não classificar simulações de transporte/arquivamento como ingestão real. Necessária uma execução HTTPS em ambiente autorizado e checagem de contrato oficial por tabela e trimestre.

**Próxima rodada:** substituir o material sintético de teste por três capturas oficiais verificadas (somente com permissão), homologar IDs/unidades/classificações e aferir revisão/presença de UFs; executar o mesmo pipeline e validar o histórico. Não repetir implementação offline que já passou no CI. Nenhum merge/deploy/cron ou gasto foi ativado.

## Continuidade autônoma 23/10/2026 — desbloqueio parcial do IBGE e nova quarentena

- Código oficialmente observado a partir das respostas HTTPS do `apisidra.ibge.gov.br` no runner GitHub Actions: `v/284,285`, classificações totais `992` (rebanho bovino), `118225` (inspeção) e `115236` (referência do total trimestral), com D1/D2/D3 comuns, D4/D5/D6 no bovino e D4/D5 em suíno/frango. Fontes: CI #39945191701. Campo de metadados v3 permanece sem resposta.
- O normalizador estrito processou **seis extratos IBGE reais sem persistência**, três nacionais e três de UFs, em 2026-T2, no CI #39945474689. Evidências foram SHA-256 e contagem de registros, não cópia integral dos dados para o repositório.
- Reconciliação territorial diagnóstica (CI #39945756036): BOVINO 25 UFs numéricas + AP/DF censuradas = 27; SUINO 21 UFs numéricas, AC/AM/PA/RR/SE censuradas, AP não retornada = 26; FRANGO 19 UFs numéricas, AC/AL/AM/DF/RN/RR/SE censuradas, AP não retornada = 26. Esses resultados valem estritamente para 2026-T2 e para esta extração.
- Implementados `pecuaria_sidra_mapa_observado.py` (códigos reais, classificados não homologados), `pecuaria_sidra_metadados.py` (análise/contraste com variáveis e classificações), `pecuaria_sidra_reconciliacao.py` (censura x ausência sem cálculos BR-UF) e `pecuaria_sidra_quarentena.py` (seis consultas, prévia, armazenamento local opcional somente de values, sem JSON falso de metadados). As funções de análise foram adicionadas ao registro de BOI, FRANGO e SUINO sem ativação operacional.
- O coletor de quarentena foi executado em modo **real e sem gravação** no runner CI #39946527270: seis respostas processadas, hashes idênticos aos da sondagem anterior, preservação de censuras e `publicacao_historica_confirmada=false`. Naquela execução o teste de adulteração sintética falhou porque uma proteção de schema nova impediu atingir a proteção SHA-256; o cenário foi corrigido, mantendo ambos os controles independentes.
- A quarentena só aceita competência `202602`, cujas classificações foram observadas; rejeita qualquer trimestre com mapa não validado. O horário da coleta é usado conservadoramente como primeiro momento de conhecimento em memória, e NÃO como data de publicação histórica do IBGE. Não há backfill retroativo de vintages anteriores.
- Gravação SQLite ainda testada **apenas com bytes sintéticos**. O acesso HTTPS real não foi usado para criar DB persistente e não houve transmissão para Google Cloud/Drive/WhatsApp.
- O teste de rede pontual foi retirado de `tests/` após demonstrar conectividade, códigos e processamento. Nenhuma sondagem é executada automaticamente pela suíte permanente.

**Próximos gates necessários:** (P0) validar metadados oficiais v3 e direitos de armazenamento; (P0) testar e registrar controles semânticos por espécie/território/período e obter proveniência de publicação; (P1) ativar capturas reais na quarentena em ambiente autorizado e persistente, SEM promoção para produção; (P1) revisão editorial independente e regras de liberação de séries. CI permanente deve permanecer verde.

## Lote concluído 23/10/2026 — backfill multi-trimestre e as-of

- Limitação removida: quarentena antes aceitava apenas 2026-T2. Agora exige trimestre encerrado desde 1997, identificadores 284/285, headers DnC SEM correspondência parcial de texto, presença de D3N compatível e códigos totais corretos em cada resposta. Qualquer divergência falha antes de escrita.
- Criado src/nivon/pecuaria_sidra_backfill.py: recebe 1-4 trimestres, executa 6-24 consultas explícitas, prepara todas antes de gravar, preserva bytes/URL/hash e insere conjunto inteiro em transação única; importações idênticas reaproveitam hash e versões diferentes não sobrescrevem edições anteriores.
- Nova consulta as-of read-only por espécie e períodos: somente a última captura conhecida até o corte, jamais antecipar um backfill baixado depois. A data da primeira coleta substitui publicacao APENAS como piso conservador para consulta, sem afirmar data de divulgação no IBGE. Rejeita consultas potencialmente truncadas acima de 500 linhas.
- CLI permite --consultar --especie --periodo --corte --banco, sem --rede/--gravar. Mantém dry-run sem rede como padrão; armazenamento de bytes reais não foi autorizado/executado neste lote.
- Testes integrados de 12 extratos, rollback se a última resposta falha ou trigger SQL rejeita inserção, replay idempotente, variável/dimensão alterada, trimestre divergente, captura anterior ao corte, revisão posterior e CLI read-only.
- Evidência real IBGE: GitHub Actions #39983108842 verificou 2025-T2 (6 extratos, 132 numéricos, 32 indisponíveis) e 2026-T1 (6 extratos, 134 numéricos, 30 indisponíveis). Eram respostas HTTP oficiais obtidas no runner, não bytes persistidos. O teste temporário de rede foi removido do CI permanente após a inspeção.
- Evidência CI com teste de revisão as-of: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983435093 com 1.319 testes, 0 falhas, 5 ignorados (inclui o teste HTTPS temporário removido depois). Runbook atualizado: docs/RUNBOOK_SIDRA_PECUARIA_LOTES_20261022.md.

**Bloqueios remanescentes:** obter metadados oficiais completos, garantir direitos específicos de retenção/redistribuição, datas reais de publicação e eventual contrato de armazenamento Google Cloud; sem merge/deploy/cron/agendamento, sem dados reais em banco persistente e sem previsões operacionalmente homologadas.

## Continuidade 23/10/2026 — correção do histórico real de revisões e exportação de quarentena

**Problema P0 resolvido em código:** a reconstrução anterior retinha apenas a versão mais recente por território/trimestre antes de chamar o motor de revisões. Isso eliminava evidência de revisões intermediárias. Além disso, linhas que desapareciam de um novo extrato podiam herdar indevidamente o valor antigo quando snapshots eram mesclados por chave.

### Implementações
- `src/nivon/pecuaria_sidra_revisoes.py`: novo motor para comparar edições completas no mesmo escopo BR ou UFs, por trimestre. Os estados são `VALOR`, `CENSURADO` e `AUSENTE_NO_EXTRATO`. Ausência não é zero nem censura criada artificialmente. Cada mudança preserva IDs, hashes, primeiras coletas e status antigo/novo.
- `src/nivon/pecuaria_sidra_backfill.py`: a consulta temporal lê todas as capturas existentes no corte (limite de 300 versões; acima disso falha fechado), reconstrói revisões e, separadamente, escolhe última edição de cada escopo para o diagnóstico territorial vigente. A saída distingue capturas históricas, vigentes e superadas, sem confundir primeira coleta com publicação do IBGE.
- `src/nivon/pecuaria_sidra_quarentena.py`: a gravação transacional rejeita duas capturas diferentes do mesmo escopo e horário declarado; rollback de toda a transação em conflito.
- `src/nivon/pecuaria_sidra_exportacao.py`: exportador de estágio para uso futuro em nuvem, sem rede. Exige direitos declarados de transferência, verifica hashes/recorte/corte temporal e escreve arquivos originais e manifesto SHA-256 num novo diretório por renomeação, sem sobrescrever pacotes existentes. Nenhum upload Google Cloud foi feito.
- `config/motores_inteligencia.v1.json` e `src/nivon/registro_motores.py`: consulta as-of e auditoria de edições registradas em BOI, SUINO e FRANGO; gates operational_enabled=false e scheduled_enabled=false preservados.

### Testes e evidências
- Testes E2E `tests/test_pecuaria_sidra_backfill_integrado.py`: revisão numérica conserva valor anterior/novo; linha MT ausente em edição posterior deixa de compor estado vigente e SP passa a constar; colisão de mesmo instante rejeitada; duas versões não antecipam resultados; exportação 12 JSONs em manifesto com hashes, replay, cutoff, direitos, tampering e CLI read-only.
- GitHub Actions https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001123587 — 1.325 testes executados, 0 falhas e 5 ignorados, incluindo os cenários novos.
- Toda validação desta rodada usa capturas sintéticas já persistidas em SQLite de testes. A evidência anterior de 12 respostas HTTPS SIDRA reais (2025-T2 e 2026-T1) permanece em https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983108842, mas nenhuma captura real foi armazenada nesta rodada.

### Prioridades de liberação
- P0: autenticar metadados agregados v3 e publicação original de cada edição, comprovando direitos específicos de retenção e transferência antes da carga real.
- P1: integrar pacote de quarentena a armazenamento Google Cloud somente após identificar projeto, credenciais, budget/limite e permissões; a implementação atual não ativa serviços nem faturamento.
- P1: ensaiar revisões efetivamente observadas em datas distintas e avaliar qualidade por UF/indicador, sem tratar histórico baixado agora como vintage autêntico.
- P2: só então liberar motores de tendência e relatórios pecuários, mantendo os estados estimado/observado/inferido e fontes auditadas.
