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
