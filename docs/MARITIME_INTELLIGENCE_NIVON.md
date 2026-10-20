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
