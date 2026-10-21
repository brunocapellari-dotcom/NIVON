# NIVON — Auditoria técnica da Inteligência Agrícola

**Corte:** 2026-10-20. **Escopo:** revisão de código nas branches PR #1, #9, #13 e repositório AgroLogMT/main; conferência documental com fontes oficiais; nenhuma coleta, treinamento em bases reais, merge ou deploy.

## Evidência de implementação

- `main` do NIVON tem somente `README.md`. Código permanece em PRs draft.
- PR #1 contém `motores_agro_estrategicos.py`, `conab_agrobr.py`, `progresso_conab_historico.py`, `sidra_pam.py`, `inteligencia_temporal.py`, cenários econômicos e cobertura para 28 frentes.
- PR #9, sobre o ramo PR #3, acrescenta `agregacao_pam_ibge.py`, `composicao_pam_sidra.py`, `auditoria_safra_preditiva.py`, `analogos_historicos.py`, `verificacao_probabilistica.py` e governança de vintages. Estes são componentes OFFLINE; testes sintéticos não validam previsão real.
- AgroLogMT/main tem `collector/conab_safra_history.py`, `collector/conab_safra.py`, `collector/ibge_pam.py`, `models/baselines.py`, `models/analog_years.py`, `models/training_dataset.py` e testes de calibração de soja. Aproveitar algoritmos e contratos conforme licença, **não** importar um sistema concorrente nem presumir que o código é homologado.
- Esta branch acrescenta `inteligencia_agricola_safras.py`: baseline pontual no tempo de rendimento histórico para **área prevista para colher ainda remanescente**, com isolamento de cultura/segmento/produto/região, conservação de massa, seleção somente de vintages disponíveis até a emissão e bloqueio explícito de publicação.

## Matriz de maturidade — 7 culturas

| Cultura | Componentes existentes inspecionados | Maturidade comprovada | Lacuna agronômica / previsão |
|---|---|---|---|
| Soja | área, produção, comercialização, esmagamento, CONAB progresso, PAM, auditoria de yield, análogos | Contratos e simulações; nenhum treinamento real homologado | datas reais de safra, fenologia, clima por fase, solo, cultivares, yield municipal e comparação OOS |
| Milho | primeira/segunda/terceira safras, demanda, etanol, progresso CONAB, PAM | Contratos e simulações; não confundir milho total com safrinha | previsões por safra comercial e calendário regional, estresse térmico/hídrico por fase, colheita e oferta logística |
| Algodão | produção em caroço, pluma, beneficiamento, fontes CONAB/IMEA | Contratos e simulações industriais | separar rendimento agrícola em caroço de rendimento pluma; fenologia, risco chuva na colheita e atributos de qualidade |
| Trigo | série de grãos, import parity, PAM | Contratos e cenários econômicos | frio, geada, excesso hídrico, risco na colheita, zoneamento e previsão de área/rendimento |
| Sorgo | substituição em ração, série CONAB, PAM | Contratos e cenários econômicos | área, genótipo/ciclo, resposta hídrica e termo de oferta por microrregião |
| Cana | ATR e mix açúcar/etanol, produção industrial, série cana CONAB | Simulação técnica, não motor agronômico calibrado | distinguir área de plantio, corte, renovação e soqueira; TCH, ATR/t, cortes e previsão quadrimestral |
| Gergelim | paridade exportação, série CONAB, PAM | Contrato e cenários; histórico municipal PAM curto | séries de produção pré-PAM, calendário efetivo, escala amostral, rendimento e risco na colheita |

**Regra:** mais funções cadastradas não significam maior poder preditivo. Para todas: `inputs_reais_homologados=false`, `previsao_homologada=false`, `operational_enabled=false`.

## Referências primárias e política de integração

1. **CONAB Séries Históricas – Grãos:** https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos — principal série por cultura e UF; cada arquivo e revisão têm identidade própria.
2. **CONAB Progresso de Safra:** https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra — base semanal publicada para soja, milho, trigo, arroz e feijão, com condições e fenologia. **Não** atribuir cobertura semanal equivalente a algodão, cana, sorgo ou gergelim sem evidência.
3. **CONAB Acompanhamento da Safra:** https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras — grãos/fibras em divulgação mensal; cana possui divulgação quadrimestral. Diferenciar publicação de referência e revisão.
4. **IBGE PAM/SIDRA:** https://sidra.ibge.gov.br/ — uso municipal/estadual ANUAL, variáveis de área e produção com unidades certificadas; separar milho total (1612) de safras (839) e algodão caroço/pluma. Não reconstituir conhecimento passado a partir do download atual.
5. **MAPA ZARC (Tábua de Risco):** https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f — janelas de plantio por cultura/município/solo/grupo de cultivar e decêndio; não se confunde com plantio efetivamente executado.
6. **USDA PSD/WASDE e NASS Quick Stats:** https://www.nass.usda.gov/Quick_Stats/ — cenários internacionais e referência de metodologia, nunca substitutos automáticos de observação de lavoura municipal brasileira.
7. **INMET/ANA/CHIRPS/NASA POWER:** séries climáticas e hídricas somente após QA de unidade, grade, estação e risco de data leakage; agregar por recorte agrícola real e estádio fenológico, não por média estadual arbitrária.

**Licenças:** fonte pública ou consulta sem login não significam automaticamente redistribuição irrestrita. Homologar acesso, uso, armazenamento e publicação por dataset.

## Contrato matemático de desenvolvimento

- **Físico:** produção efetiva (t) = área efetivamente colhida (ha) × rendimento efetivo (kg/ha) / 1.000. Para cenário de produção final, somar `producao_colhida_t` aos rendimentos *condicionais* aplicados apenas à `area_alvo_colheita_ha - area_colhida_ha`.
- **Áreas distintas:** área plantada não equivale à área colhida ou à área projetada para colheita. Para cana, a área anual plantada não deve ser usada como denominador dos cortes de soqueiras.
- **Rastreabilidade:** preservar `competencia`, `data_referencia`, `data_publicacao`, `data_coleta`, `disponivel_em`, `fonte_id`, `edicao_id`, hash dos bytes RAW e código IBGE; registrar incerteza e revisões sem sobrescrever vintages.
- **Comparabilidade:** mesma cultura, ano/safra, produto físico, região, calendário, nível geográfico e condição de agregação. Não somar milho total às safras 1/2/3 ou algodão em caroço à pluma.
- **Quantis históricos:** Q10/Q50/Q90 obtidos de safra passada são **cenários de benchmark**, não intervalo preditivo nem probabilidade 10/50/90. Seu uso comercial requer primeiro diagnóstico de viés, dados reais, vintages históricas e cobertura.
- **Skill real:** treino por safra passada somente; replays com cutoff `as-of`, baseline ingênuo, walk-forward por safra, holdout temporal e espacial, CRPS/WIS ou Pinball para quantis, MAE/RMSE, cobertura, calibração e intervalos por cultura/UF.

## Próximos gates agrícolas (ordenados)

- **AG-01 — P0:** carregar, versionar e reconciliar CONAB séries históricas e progresso semanal com edição, fonte, publicação e hash RAW. Validar 1 cultura × 1 UF × anos retrospectivos antes do lote nacional.
- **AG-02 — P0:** fechar dicionário de cultura/safra comercial/produto físico, inclusive milho 1/2/3 vs total, algodão caroço vs pluma, safra de cana e gergelim.
- **AG-03 — P0:** integrar IBGE PAM municipal e comparar cobertura e rendimento ponderado sem suposição de completude da UF; registrar vintage real.
- **AG-04 — P1:** histórico meteorológico e agroclimático espacial por época do cultivo + ZARC, solo, cultivar, NDVI/ET0/chuva, preservando medições e erros.
- **AG-05 — P1:** modelos por cultura e região: baseline sazonal; produtividade; área; ritmo semanal; balanço e oferta. Intervalos condicionais antes de alegar probabilidades.
- **AG-06 — P1:** replays com anos, regimes climáticos, choque hídrico, holdout municipal, contra benchmarks independentes; travar modelos com skill nulo ou negativo.
- **AG-07 — P2:** contratos para commodities, armazéns, frete, portos e IVO AI via motor integrado; liberar apenas após evidência de fonte e licença, sem envio ao WhatsApp nesta fase.

## Limites deste incremento

Novo algoritmo puro, offline e sem dependências; não coleta dados reais, não ajusta parâmetros por cultura nem infere fenologia/solo. A amostra histórica declarada ainda deve ser auditada externamente; hash declarado comprova formato de integridade, não autenticidade de origem. Ausência de 5 safras anteriores utilizáveis bloqueia todo resultado numérico. Todas as saídas são NÃO PUBLICÁVEIS e não equivalem a capacidade preditiva instalada. Sem merge, deploy, cron, serviços pagos ou alteração de credenciais.

## Continuidade 20/10/2026 — conciliação CONAB × PAM (AG-02 / AG-03)

**Diagnóstico:** a branch científica PR #9 avançou desde a criação da PR #23 e corrigiu identidade C81 (soja 2713, feijão 2702) e leitura ambígua de valores decimais SIDRA. A frente de Dados PR #16 já possui descoberta de índices históricos de progresso semanal CONAB; nenhuma das duas atividades deve ser duplicada na agrícola.

**Incremento nesta PR:**
- `src/nivon/auditoria_conab_pam.py`: etapa de **staging e conciliação descritiva** da tripla CONAB `AREA`, `PRODUTIVIDADE` e `PRODUCAO` normalizada por `conab_series.py`, com validação de unidade HA/KG_HA/T, identidade do arquivo, UF, cultura, primeira/segunda/terceira safra, edição e SHA.
- `AREA` CONAB é **area_informada_conab_ha**, não `area_colhida_ha` PAM. Produtividade e produção são **informadas/projetadas**, nunca chamadas de realização.
- O confronto PAM exige correspondência explícita entre safra comercial e ano civil via prova documental (sem mapear automaticamente safra 2024/25 para 2025); restringe milho PAM 1612 ao TOTAL, valida produto em grão e UF. Deliberadamente não oferece algodão (caroço/pluma), cana ou gergelim sem contrato metodológico específico.
- Com ausência de histórico as-of declarado, edição/documento de disponibilidade, cobertura integral da PAM ou arredondamentos consistentes, devolve status com **diferença de produção nula**. Mesmo quando todas as provas são declaradas, a comparação segue **descritiva**, não treino de modelo nem avaliação de acurácia.
- A primeira versão restringia a ponte a dez UFs; esta revisão expande a 27 UFs, com códigos IBGE de dois dígitos, verificação contra o dicionário de UFs aceito pelo agregador e cenários sintéticos por UF. Isto NÃO comprova cobertura real municipal.
- `tests/test_auditoria_conab_pam.py`: testes sintéticos de conservação, safras de milho, rastreabilidade, cortes, sigilo sem extrapolação, provas, geografia, unidades, integridade e ausência de publicação.

**Crítico:** os hashes e flags `disponibilidade_verificada` introduzidos por fixtures são declarações, e não autenticação automática dos bytes oficiais. Não existe regra que permita alimentar automaticamente `inteligencia_agricola_safras.estimar_oferta_remanescente`: `area_informada_conab_ha` e `area_colhida_ha` não são intercambiáveis. Depende de inspecionar o significado da área no arquivo e encontrar observação **real** da área colhida, incluindo data de corte da colheita.

**Próximas ações objetivas:**
1. Data Engineering (PR #16): materializar RAW autorizado, edições/revisões e evidências de publicação **reais**, com hashes computados dos bytes e sem assumir publicação histórica a partir da edição presente.
2. Research/Science (PR #9): conservar a correção do C81 e auditar junto ao SIDRA convenção de valor `V`/unidades; reconciliar/merge de forma não destrutiva pela integração central.
3. Agricultura (PR #23): provar o dicionário de safra para soja MT e milho 1ª/2ª/3ª; expandir de 10 UFs somente com testes e verificar área colhida vs área declarada. Em seguida, confrontar PAM estadual com CONAB no **mesmo recorte documentado**.
4. Somente após dados e vintages autenticadas: avaliar modelos de área e produtividade por cultura, walk-forward e validação espacial. Não converter confronto entre fontes em ganho preditivo.

**Nenhuma liberação operacional:** `habilita_treino=false`, `habilita_publicacao=false`, sem download, agendamento, serviço, credencial, deploy ou merge.

## Continuidade 21/10/2026 — reconciliação científica e UF nacional

- Inspecionada a evolução da PR científica #9 até `36c064a14b7a05c7701013cf34e8e4ec0fd646b4`. Comparação GitHub identificou **6 arquivos científicos divergentes**: `config/catalogo_tecnico_historico.v1.json`, `docs/BASE_CIENTIFICA_E_HISTORICA_20261019.md`, `agregacao_pam_ibge.py`, `composicao_pam_sidra.py` e seus dois testes.
- Merge não destrutivo `bc0a1251057f7b29c1cf6c1f9cd7b96e6d93a81e` incorporou exatamente os seis blobs científicos com segundo pai apontando para #9. A comparação `#9...#23` comprovou base científica presente (behind=0) e **somente 7 arquivos agrícolas extras**, sem deleção nem modificação dos módulos compartilhados.
- CI no commit de reconciliação: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39590486218 — **1.192 testes, zero falhas, cinco ignorados**. Nenhum teste de aquisição live foi habilitado.
- A ponte CONAB/PAM deixou de duplicar `C81` e nomes canônicos da PAM: importa agora `C81_PAM_POR_CULTURA`, `_PRODUTOS` e `_UFS` do adaptador científico; qualquer desvio de categoria central é automaticamente refletido na conciliação.
- Ampliação explícita da camada de dicionário estadual para **27 UFs** com guarda de unicidade e correspondência ao universo `_UFS`. Testes adicionais percorrem todas as 27 UFs com **fixtures sintéticas**. Projeção e liberação continuam OFF.
- Próximo gate P0 externo: dados reais autorizados do SIDRA/CONAB com RAW e edições/hora comprovadas, mapa de calendário comercial->ano civil por cultura e região, qualidade e cobertura verificadas em amostra MT. Nem URL atual nem SHA sintético recuperam vintage histórica.

Sem merge na `main`, nenhuma execução de rede do código agrícola, ativação de coleta, dados contratados, envio ou deploy.

## Continuidade 21/10/2026 — proteção de RAW e lacunas do histórico CONAB (AG-01 P0)

### Evidência externa, com limite explícito

As páginas oficiais de série histórica de grãos da CONAB indicam que `SojaSerieHist.xls` foi publicado **15/10/2026 09h29**, `Milho1aSerieHist.xls` **15/10/2026 09h26**, `Milho2aSerieHist.xls` **15/10/2026 09h26**, `Milho3aSerieHist.xls` **15/10/2026 09h27** e `MilhoTotalSerieHist.xls` **15/10/2026 09h27**. São **metadados visíveis no portal na consulta de 21/10**, não hashes, comprovantes de disponibilidade histórica anterior nem evidência de que os bytes adquiridos sejam os daquele horário. Fontes:
- https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/soja/
- https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/milho
- https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-graos

**Bloqueio observado:** consulta pública localizou as páginas e a URL de download `/@@download/file`, mas o leitor web recusou os bytes `application/vnd.ms-excel`; a tentativa de transferir o XLS para o contêiner também falhou. Nenhum XLS ou conjunto de resultados SIDRA 1612 real foi adquirido/validado nesta execução. Não registrar suposto SHA real nem afirmar dados alimentados.

### Contrato implementado, offline

- `src/nivon/prova_raw_conab_agricola.py:verificar_raw_conab` recebe HTML UTF-8 e XLS **já capturados por processo licitamente autorizado**, SHA-256 esperado do registro do adquirente, URLs e horários independentes.
- Recalcula SHA-256 sobre os bytes (comparação constante), aplica limite de tamanho, verifica SOMENTE assinatura OLE2 (não parsing do workbook), exige link da planilha na página oficial CONAB reconhecida por `conab_catalogo.py`; vincula `/view` da página ao `/@@download/file` do binário sem confundir os dois.
- A tolerância de dez minutos entre capturas HTML/XLS é apenas guard de consistência pontual, não validação automática de publicação. Mantém `estrutura_xls_validada=false`, `abas_xls_lidas=false`, `edicao_id=DESCONHECIDA`, `publicado_em=null`, `disponivel_em=null`, `disponibilidade_verificada=false`, `vintage_asof_comprovada=false`, `habilita_backtest=false`, `habilita_treino=false` e `habilita_publicacao=false`.
- Ajuste em `auditoria_conab_pam._prova_temporal`: admite **ambas** as datas históricas nulas sem falsear uma data. Metadado sem publicação e disponibilidade devolve bloqueio comparativo, jamais `as-of` positivo; uma só data ou alegação de prova verificada com datas nulas continua erro.
- `tests/test_prova_raw_conab_agricola.py`: regressões sintéticas contra hash adulterado, extensão/formato impróprio, domínio incompatível, URL de download distinta da página, timestamp divergente, metadados nulos e recusa de diferencial físico sem vintage. O OLE2 sintético é intencionalmente incompleto para demonstrar que **assinatura não é validação XLS**.
- Os motores SOJA e MILHO expõem o adaptador sob allowlist, mas mantêm todos os flags de produção **OFF**.

### Próximo gate verificável

(1) Engenharia de Dados: realizar captura real autorizada de **um** XLS de soja MT e do HTML correspondente num único intervalo, salvar RAW em storage não público; (2) verificar hashes calculados, MIME e workbook via parser isolado, planilhas AREA/PRODUTIVIDADE/PRODUCAO; (3) registrar os valores observados e metadados do levantamento, **sem converter a publicação atual em uma série de edições anteriores**; (4) capturar SIDRA 1612 para um município MT com mesma proveniência, sem forçar leitura de separador ambíguo; (5) comparar com fontes e calendários somente quando houver evidências independentes de disponibilidade do corte histórico. Sem coleta recorrente, novos gastos, merges, deploy nem publicação.

## Continuidade 21/10/2026 — inspeção estrutural de XLS CONAB (AG-01)

**O que foi efetivamente implementado:** uma segunda etapa, **sem rede e sem persistência**, para ler planilhas legadas `.xls` já capturadas. Módulo: `src/nivon/inspecao_xls_conab_agricola.py`.

1. Aceita exclusivamente o manifesto produzido por `verificar_raw_conab` e **recalcula** SHA-256 sobre os bytes, comparando com ambos os hashes do manifesto, tamanho, cultura, arquivo, safra comercial e UF. Flags indevidamente promovidos, datas de publicação inventadas ou edição declarada são rejeitados.
2. O decodificador real é `xlrd>=2.0.1,<3` como dependência **opcional** `pip install '.[excel_conab]'`, nunca obrigatória nem instalada automaticamente pela CI. O módulo abre o arquivo em memória, não executa macros, limita abas, linhas (máx. 1.000) e colunas (máx. 130), chama `conab_series.normalizar_livro` e libera recursos.
3. Reusa validações das abas `Área`, `Produtividade`, `Produção`, as unidades HA/KG_HA/T, a tabela de safras e o arquivo distinto de milho 1ª/2ª/3ª/TOTAL. Seleciona exatamente uma tripla por `UF+safra` e chama `preparar_tripla_conab` sob mesmo SHA e timestamp.
4. A saída registra quantidade de observações normalizadas, células originais, cabeçalhos inferidos e um diagnóstico físico. A diferença física é um **resíduo de consistência**, não acurácia de previsão ou dado realizado.
5. **Escopo de segurança:** este código não é sandbox, não limita CPU nem memória do processo; arquivos brutos devem ser processados em worker externo isolado com controles e antivírus. `estrutura_xls_validada=True` indica somente **decodificação e verificação estrutural** da instância processada, não direitos, método agrícola, fonte oficial autenticada ou vintage as-of.
6. `test_inspecao_xls_conab_agricola.py` usa workbook **simulado**, com `_abrir_livro` substituído explicitamente; os bytes OLE2 artificiais não são XLS real. Validam política de rejeição, ciclo de fechamento e contratos, **não** layout oficial de 2026 ou segurança do parser em arquivo real.
7. Entradas nos motores SOJA/MILHO são cadastradas sob allowlist, permanecendo `inputs_reais_homologados=false`, `previsao_homologada=false`, `scheduled_enabled=false` e `operational_enabled=false`.

**Bloqueio P0 permanente:** não foi obtido nesta frente um único XLS oficial com SHA-256 calculado e workbook realmente aberto, nem vintages de levantamentos retrospectivos. Não preencher `data_publicacao`, `data_referencia`, `data_disponibilidade` ou `edicao_id` com horário da consulta atual. Não habilitar backtest, treino, publicação ou presumir que área informada CONAB seja área colhida PAM.

**Próxima execução E2E tecnicamente verificável:** Data Engineering (#16) deve fornecer arquivo RAW autorizado de soja MT + HTML simultâneo + registro de aquisição. Rodar primeiro `verificar_raw_conab`, depois `inspecionar_xls_conab_capturado` em worker isolado, comparar células e arredondamentos a documento primário. Se ambas etapas passarem com dados reais, registrar os hashes de entrada, evidência do parser, janelas temporais, status sem vintage e divergências; só depois avançar a milho e SIDRA.

## Continuidade de 21/10/2026 — defesa contra substituição da proveniência (AG-01)

**Auditoria do último head:** PR #23 em draft, `ef4b12f` com CI verde e nenhum novo commit nas PRs científicas #9 ou de dados #16 que exigisse reconciliação.

**Bloqueio de dados reais reafirmado:** a página oficial da CONAB aponta o `SojaSerieHist.xls` de 15/10/2026 às 09h29. A chamada ao link `/@@download/file` pelo leitor web falhou por `Unsupported content-type: application/vnd.ms-excel`, e a tentativa local de solicitação via HTTPS falhou por indisponibilidade DNS do domínio `www.gov.br`. Não existe novo hash, RAW ou célula oficial validada nesta sessão. Fonte primária: https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/series-historicas/graos/soja/sojaseriehist.xls/view. O horário do portal não deve ser reclassificado como vintage as-of dos levantamentos de safras anteriores.

**Falha eliminada:** a primeira versão de `inspecao_xls_conab_agricola.inspecionar_xls_conab_capturado` recebia apenas `manifesto_raw` e `planilha_raw`, sem os bytes HTML originais, e por isso não recalculava a origem da URL nem o SHA do índice HTML durante o estágio de decodificação.

**Correção:** a função passou a exigir também `pagina_html_raw: bytes`. Após validações locais de contrato, antes de instanciar `xlrd`, reconstrói **integralmente** o manifesto chamando novamente `verificar_raw_conab` com os dois RAWs e compara todas as chaves do resultado com a estrutura declarada. Troca de HTML, URL, horários, hashes ou flags reprova o estágio. A medida impede substituição silenciosa **entre os dois artefatos**, mas não autentica automaticamente um site externo, titularidade, assinatura digital, histórico de publicação ou direito de uso.

**Testes:** quatro regressões adicionais cobrem alteração de HTML sem mudar a URL, mistura HTML milho/manifesto soja, URL falsificada e ausência de HTML impedindo invocar o decoder. A suíte final no commit `e56cdb685f2d60c4312d4bf12c7a168daa072641` concluiu com **1.226 testes, zero falhas, cinco ignorados**, GitHub Actions https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604790112.

**Próximo P0:** a captura autorizada do XLS real e do HTML simultâneo, seguida de `verificar_raw_conab` → `inspecionar_xls_conab_capturado` em worker isolado, gravação do RAW fora do repositório, inspeção do layout e extração de uma safra/UF. Enquanto o acesso a bytes reais não for resolvido, desenvolver/validar evidências de edições históricas por boletins publicados com data verificável. Não ativar publicação, treino, backend, serviço pago, cron, merge em main ou WhatsApp.
