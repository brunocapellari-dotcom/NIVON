# NIVON — Ciclo 04: convergência Maritime PR #6 + coletores/line-up PR #40

**Referência de auditoria:** 21/10/2026. **Escopo:** branch isolada de integração, sem merge, deploy, coleta, API externa, aquisição de AIS ou envio.

## Estado e proveniência
- **Base:** PR #40, HEAD congelado `7e55ea1707d7b95833d9519ac573537240c3cc39`.
- **Origem:** PR #6, HEAD `016981641839d433a450c375df8cc46e1b416799`. Delta extraído em relação ao ancestral `69edc2b6e0569ebd955a8f06a146e3f6fe4ecdfe`, não por overwrite de 135 datasets.
- **75 arquivos adicionados** foram migrados com seu SHA de blob original (motores AIS, qualidade, port calls, fila, previsões, gateway, documentos, cockpit web e testes).
- Três arquivos compartilhados reconciliados:
  1. `config/motores_inteligencia.v1.json`: preservou as duas funções de tendências MARITIMO da integração #30 e incorporou 16 entrypoints marítimos, totalizando 24 nessa frente, com todos os quatro gates OFF.
  2. `src/nivon/registro_motores.py`: allowlist passou de 57 para 72 módulos, incorporando 15 submódulos marítimos sem perder estatística, meteo e agro.
  3. `config/rotas_coleta.v1.json`: manteve 139 rotas e o bloqueio `REAL_ZIP_ACCESS_RIGHTS_AND_LAYOUT_VALIDATION`; acrescentou apenas informação de adaptador ANTAQ histórico/offline e requisitos de SHA-256, competência e direitos.

## Semântica comercial e operacional
- Os cinco portos piloto do gateway são **Santos, Paranaguá, Barcarena/Vila do Conde, Santarém e Itaqui**. Cadastros dos 45 portos nacionais não significam 45 conexões AIS ou line-ups ativos.
- AIS exige autorização por operação (coleta, armazenamento, exibição comercial), validade e contrato. Chave API isolada não confere licença; se não há direitos aprovados não iniciar conexão.
- Programação/line-up informado é **PROGRAMADO_NAO_REALIZADO**. Não representa atracação, operação, toneladas movimentadas ou navio observado. Dados históricos ANTAQ tampouco são feed AIS ou escala atual.
- O gateway do cockpit é **read-only**, de staging, local; `publication_allowed=false`; nenhuma fonte padrão gera contagens de navios ativos, fila, ocupação ou indicadores ETA em falta de dados.
- Não se deve chamar cenário/forecast de previsão homologada antes de validação fora de amostra, rastreabilidade temporal, calibração e avaliação dos intervalos.
- A presença de código e UI não implica port calls reais, AIS com histórico, fila reproduzível, certificação de 95% de eventos ou aceite de 7 dias E2E.

## Testes e rastreabilidade
- Novo `tests/test_integracao_maritime_pr6_pr40.py` adicionou 5 verificações específicas: 139 datasets/45 portos/rotas AIS OFF, entrypoints quantitativos e marítimos coexistentes, bloqueio de AIS por falta de direitos, programação normalizada transitando do coletor oficial para gateway sem virar operação, e readiness bloqueado sem evidências.
- GitHub Actions [39598697674](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39598697674) no commit `bd2080f7f26318dc8ab21949e3c9071249cc26b6`: **1.726 testes, 0 falhas, OK**.
- GitHub Actions [39598697614](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39598697614): Vite 8.2.2, `npm ci --ignore-scripts`, build concluído com artefato `dist/index.html` não vazio. **Não houve deploy**.
- **Alerta de supply chain**: npm emitiu avisos de conflito de peer dependencies entre `@loaders.gl/tiles@4.5.1` e `@loaders.gl/core@4.4.5` (`~4.5.0-alpha.2` esperado). Compilação bem-sucedida NÃO elimina conflito/runtime ou vulnerabilidades; resolver com teste real de renderização e análise de licença/lockfile, sem upgrades cegos.

## Correção P0 de janela temporal após integração

- Auditoria de `src/nivon/maritime/maritime_gateway.py`: o endpoint de line-up validava `past_hours` e `future_hours`, mas não filtrava `eta`; a contagem do resumo também não respeitava a janela. Isso poderia apresentar programação antiga/fora da janela na interface shadow.
- Na branch de integração, `MaritimeReadAPI._lineup_window` passa a filtrar as linhas com ETA válido dentro dos limites especificados. O endpoint `/v1/maritime/lineup` e a contagem `lineup_calls` de `/v1/maritime/summary` usam o mesmo recorte; ETAs ausentes ou malformados são excluídos das visões de fontes programadas/internas.
- As fixtures sintéticas continuam explicitamente marcadas como `SYNTHETIC_TEST_ONLY`, sem se passarem por observações reais. Testes com calendário dinâmico evitam que fixtures fixas envelheçam artificialmente.
- Evidência [CI Python 39599571951](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39599571951) no HEAD `3035c76870057f7e598cb1030b73b12ecf59c466`: **1.727 testes, 0 falhas, OK**. Novo teste adversarial `test_filtro_eta_por_janela_e_contagem_resumo_coerente` aprovado.
- Evidência [CI cockpit 39599572076](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39599572076): build Vite de staging OK, sem deploy.
- **Limitação:** este filtro não certifica frescor da fonte, direitos de publicação, cumprimento das janelas de operação real, atraso AIS, timezone cadastrado em cada autoridade ou calibração de ETA. Esses gates seguem bloqueados.

## Bloqueios antes de homologação
1. **AIS**: autorização comercial e de armazenamento confirmada por contrato, auditoria da conexão real e histórico autorizado, idempotência e limites de custo.
2. **Portos piloto**: homologar geofences/berços e origem/identidade dos navios, validar ao menos 95% das chegadas/atracações/saídas contra dados independentes.
3. **Line-up e ANTAQ**: verificar acesso real permitido, layouts e 3 snapshots por porto, duplicação, janelas de publicação, timezone, direitos.
4. **Estatística**: backtest point-in-time de ETA/filas e erro por estação/porto; não publicar conclusões derivadas de amostra sintética.
5. **Cockpit**: revisar warning de dependências JS, controles de CSP/egress, teste de navegação e build reproduzível; sem hospedagem pública.
6. **Operação**: backups/restauração, observabilidade, segurança, custos, autenticação e teste ponta a ponta por 7 dias.
7. **Orquestração**: integrar IVO AI (#7) somente por contratos controlados, sem poder reclassificar as evidências de dados para 'observado'.

**Próximo ciclo técnico:** PR #7 IVO AI — auditar dependências, memoria/automação, contratos de tomada de decisão e links seguros com logística/market/Maritime; reconciliar em branch isolada com esta PR e rodar suíte conjunta. **Main inalterada** até homologação.
