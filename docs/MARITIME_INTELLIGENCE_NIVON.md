# NIVON Maritime Intelligence — Migração AgroLog + Orquestração

Data de referência: 19/10/2026. Estado: **STAGING / SHADOW / REVISÃO TÉCNICA**, não homologado para uso real ou comercial.

## Componentes migrados
- 17 motores de dominio e auditoria AgroLogMT (qualidade AIS, vessel identity, geofences, physical state, port-call, ETA, fila, forecast fila, reconciliação AIS × line-up × operação, weather, trade flow, anomalias, alertas, source health, prontidão e release gate).
- Adaptadores AISStream, cliente WebSocket opcional e lifecycle oriundos do AgroLog. Nenhum token, endpoint, agendamento ou acesso real foi configurado.
- 16 grupos de testes de unidade do AgroLog adaptados ao namespace do Nivon e contrato completo de aceite maritime.
- Coordenador analítico independente: src/nivon/maritime/intelligence.py. Não faz rede, não escreve dados, não publica e não envia relatórios.
- Histórico local SQLite e replay autorizado: src/nivon/maritime/maritime_store.py, com hash, idempotência, controle de licença por operação, backup e ensaio de restore.
- Interface MapLibre/deck.gl preservada: maritime_ui, sem API privada NIVON ainda. A compilação Node não foi executada nesta operação.

## Pipeline de inteligência
AIS bruto autorizado → validação formato/tempo/identidade/velocidade → deduplicação → geofence com fonte e versão → port calls inferidos → matching IMO/MMSI com line-up → operação realizada apenas por evidencia portuária adequada → fila/ETA/replay → sinais meteo/hidro/comércio/logística com origem demonstrável → anomalia → alertas candidatos → auditoria determinística → relatório somente após homologação.

Orquestrador: MaritimeIntelligenceCoordinator.run(MaritimeAnalysisRequest(...)).
- AIS sem sequência coerente não confirma fundeio, atracação ou qualquer carga.
- Filas vazias por ausência de AIS são nulas, não valor 0 observado.
- Previsões ficam em SHADOW ou DATA_GATED conforme qualidade e histórico.
- Recebimento de line-up não comprova carga movimentada. ANTAQ agrega movimentações por fonte, não transforma cada navio automaticamente em operação realizada.
- Resultados de modelos matemáticos devem preservar classe epistemológica e incerteza.
- Anomalias e alertas são candidatos, nunca disparados por essa função.
- Direitos de AIS, line-up, cartas/geofences, exportação e redistribuição são independentes.

## Motor de inteligência e autoridade
Camada A (dados): coletores e armazenagem, com rights gate e health.
Camada B (físico/matemática): motores portuários e modelos próprios reutilizados.
Camada C (análise): coordenador determinístico combina sinais e hipóteses, sem causar efeitos externos.
Camada D (IA): agente analista pode ler evidências e produzir narrativa com referências; agente auditor determinístico controla publicabilidade e não aceita instrução da fonte como comando. Uma LLM real **ainda não está conectada à camada marítima**.
Camada E (produto): Gateway privado + UI + briefing/WhatsApp são etapas condicionadas a homologação. Não existem nesta migração como go-live.

## Fontes e cobertura
Nivon possui catálogo nacional de 45 portos/complexos, mas **zero autorizações automáticas de execução ou parsers homologados no manifesto**. A primeira validação AIS/line-up real continua focada em Santos, Paranaguá, Santarém, Barcarena/Vila do Conde e Itaqui, sem excluir outros portos/hidrovias do escopo futuro.

## Como reproduzir testes
Python: PYTHONPATH=src python -m unittest discover -s tests -v
Testes marítimos: PYTHONPATH=src python -m unittest discover -s tests -p "test_maritime*.py" -v
UI: cd maritime_ui && npm ci && npm run build

Ainda é necessário executar e atestar a suíte na SHA exata do PR. Testes herdados foram adaptados, não são evidência de teste em condições reais. Os testes sintéticos novos cobrem ausência de dados, duplicatas, geofences sem origem, timestamps sem fuso, segregação de direitos, backup e restauração.

## Requisitos antes da produção
1. Executar regressão completa (Python, Node build, supply chain/license/security) com resultados e SHA.
2. Confirmar titularidade e licença do código herdado e das dependências do frontend; checar termos dos dados AIS/line-up/ENC e licenças comerciais por operação.
3. Integrar e homologar três edições reais de line-up por fonte; validar identificadores, geofences verdadeiras, frescor e cobertura dos cinco portos e terminais relevantes.
4. Operar histórico AIS contínuo permitido, descobrir gaps e backfill acessível legalmente; backup/restore de infraestrutura de nuvem, de custo autorizado.
5. Implementar API privada e UI com isolamento da fonte, autenticação e nenhum segredo no navegador; monitorar falhas e custos.
6. Calibrar ETA, filas e relações com hidrologia/meteorologia/fluxos terrestres mediante validação fora da amostra e sem inferir causalidade sem desenho adequado.
7. Executar aceite ponta a ponta dos 22 gates do contrato, incluindo sete dias operacionais, antes de publicar como dado realizado ou fazer deploy.

Custo: **R$ 0 em infraestrutura introduzida por estes commits;** não afirmar que cobertura AIS nacional em tempo real 24/7 será gratuita. Não contratar, criar recursos ou efetuar deploy sem homologação.

## Proveniência
Fonte sob a mesma conta GitHub: brunocapellari-dotcom/AgroLogMT, branch main, 19/10/2026. Arquivos foram adaptados por troca de imports. Para rastreabilidade comercial, fixar hashes exatos, diff, direitos autorais e licenças antes da release.


## Atualização de integração — 20/10/2026

- API local: src/nivon/maritime/maritime_gateway.py. Rotas GET /v1/maritime/config, /status, /vessels, /lineup, /summary e /vessels/{mmsi}/replay. Apenas 127.0.0.1, GET/HEAD, consulta limitada, sem CORS e sem escrita.
- UI MapLibre/deck.gl compilada e servida pela mesma origem local. Sem dados homologados, status DATA_GATED e contagens null, nunca zero falsamente observado.
- MaritimeInternalSnapshot.from_analysis() liga apenas posições AIS corroboradas pelo coordenador à UI, de modo SHADOW_INTERNAL, com auditoria bloqueante, direitos e source health verificados. Não habilita publicação ou API em nuvem. Simulação permanece SYNTHETIC_TEST_ONLY.
- model_validation.py executa avaliação prequential OOS de ETA e filas com previsões congeladas antes do desfecho, comparação de MAE/RMSE versus baseline, folds temporais e intervalo por fold. Mesmo SHADOW_BASELINE_WIN não promove o modelo.
- Testes novos: tests/test_maritime_gateway_nivon.py, tests/test_maritime_snapshot_bridge_nivon.py e tests/test_maritime_model_validation.py, além de regressões anteriores. Revalidar em CI após cada commit.

### Execução local

1. Instalar dependências e compilar na pasta maritime_ui com npm ci --ignore-scripts e npm run build.
2. Na raiz do repositório, executar PYTHONPATH=src python -m nivon.maritime.maritime_gateway --port 8765 --ui-dist maritime_ui/dist.
3. Abrir http://127.0.0.1:8765/maritime/ no mesmo computador, sem proxy externo.

O executável padrão não injeta AIS nem line-up reais. Integração Python interna pode injetar MaritimeReadAPI(internal=MaritimeInternalSnapshot.from_analysis(report, lineup_calls=...)) após passar pelos gates. Isso NÃO é produção.

**Bloqueios:** API com autenticação para nuvem, coleta AIS licenciada e contínua, line-up real homologado, geofences operacionais, validação externa de previsão, backup em nuvem, revisão de supply chain e sete dias de aceite E2E.


## Auditoria das fontes marítimas — 20/10/2026

Catálogo canônico existente: config/rotas_coleta.v1.json e config/fontes_nivon_master.v1.json, com a cobertura de LINEUP_SANTOS, LINEUP_PARANAGUA, LINEUP_SANTAREM, LINEUP_BARCARENA_VILA_DO_CONDE, LINEUP_ITAQUI, ANTAQ_MOVIMENTACAO e AIS_POSICOES. Esta investigação não cria fontes duplicadas.

1. APS Santos: https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/atracacoes-programadas/ — há programação oficial, com navio, IMO, DUV, ETA e outros campos conforme a edição. É programação informada, não carga realizada. O parser oficial é nivon._agrolog_portos_html; a nova ligação tipada é nivon.maritime.official_lineup_bridge.
2. Portos do Paraná: https://www.portosdoparana.pr.gov.br/ — disponibiliza atalhos para line-up, manobras, marés e tempo. O parser PDF já está em portos_automaticos. Requer edição/documento, série, hash e testes específicos; a página inicial NÃO é um feed estruturado.
3. ANTAQ: https://www.gov.br/antaq/pt-br/acesso-a-informacao/dados-abertos e https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/estatisticos-aquaviarios — base pública oficial para movimentação e atracação observadas em escala estatística, sujeitas a competência, revisões e disponibilidade de downloads. O novo SDP começou retomada de envio em outubro/2026; estatística agregada não substitui um evento operacional individual, e painel inacessível não autoriza bypass de WAF.
4. AISStream: https://github.com/aisstream/issues/issues/290 e https://github.com/aisstream/aisstream/issues/16 — há pedidos públicos de esclarecimento sobre licença comercial, armazenamento, retenção e redistribuição, sem prova documental obtida nesta auditoria. AISSTREAM fica explicitamente NO_LIVE_ACCESS e NO_REDISSEMINATION até permissões formais por operação.

### Gates por fluxo

- Leitura de página pública ≠ permissão automaticamente verificada para armazenamento, streaming comercial, redistribuição e envio de dados de terceiros.
- A ponte HTML exige FonteWeb autorizada, SHA-256, URL/domínio canônico, instante com fuso, identificador de escala DUV/ID e ETA com horário explícito; entradas sem identidade/horário não viram previsões. Chamar a função não coleta a rede: só recebe bytes previamente adquiridos por canal aprovado.
- A visualização SHADOW_LINEUP_ONLY aceita somente a saída do bridge e permissão específica de exibição. Exibe contagem de escalas programadas; não gera número zero de navios físicos, fila ou tonelagem embarcada.
- Não ativar busca contínua, armazenamento ou redistribuição AISStream até licença independente revisada. Não fornecer tokens de provedores no frontend.

### Pendências práticas

- Santos: confirmar edição atual e validar parser com três documentos reais de dias distintos, incluindo publicação e captura.
- CDP Santarém/Vila do Conde: verificar layout atual e datas/IDs de escala, sem assumir que um mesmo site equivale a um porto único.
- Paranaguá e Itaqui: testar documentos PDF efetivos com serie/data; falhar fechado quando arquivo/link mudar.
- ANTAQ: localizar e homologar pacote de dados históricos de atracação/movimentação com schema e licença efetivamente acessíveis, registrar versões e hash, evitar interpretações de realização a partir de line-up.
- AIS: resolver autorizações e cobertura antes de capturar posições em nuvem.
