# NIVON Maritime Cockpit — STAGING / DATA_GATED

Interface MapLibre + deck.gl herdada do AgroLogMT, compilada para funcionar com a API local read-only do NIVON. **Não existe dado AIS ou operação portuária real homologada nesta versão.** Não fazer deploy público.

## Executar localmente (não usa nuvem)

Com Node 22 e Python 3.11+:

1. Na pasta maritime_ui, executar: `npm ci --ignore-scripts && npm run build`.
2. Na raiz do repositório, executar:
   `PYTHONPATH=src python -m nivon.maritime.maritime_gateway --port 8765 --ui-dist maritime_ui/dist`
3. Abrir `http://127.0.0.1:8765/maritime/` no navegador do próprio computador.

Somente o dispositivo local pode acessar o servidor, que liga em 127.0.0.1. Não fazer proxy público, túnel, abertura de firewall ou exposição a endereços externos. O servidor é um artefato **de homologação local**, não possui login nem mecanismos completos de produção. Para nuvem, será necessária uma API autenticada, controles de acesso e homologação antes de publicação.

## Contrato API
- GET /v1/maritime/config
- GET /v1/maritime/status
- GET /v1/maritime/vessels?port_id=SANTOS&hours=6&limit=500
- GET /v1/maritime/lineup?port_id=SANTOS&past_hours=24&future_hours=336
- GET /v1/maritime/summary?port_id=SANTOS&hours=24
- GET /v1/maritime/vessels/<MMSI>/replay?hours=24

Os endpoints retornam `status=DATA_GATED` e contagens `null` quando nenhuma fonte foi homologada. **Contagens nulas não significam zero navios.** Fixtures sintéticas são injetadas apenas nos testes e sempre retornam `status=SYNTHETIC_TEST_ONLY`. Essa API ainda não consulta o armazenamento de AIS real nem line-up real.

Métricas de contexto do AgroLog (overview, PTAX e hydrology) ainda precisam de adaptadores para o Gateway do NIVON; enquanto faltarem, a UI deve mostrar indisponível. O mapa-base padrão é serviço externo de demonstração MapLibre e requer internet para visualizar tiles; as camadas AIS continuam vazias sem fonte.

## Testes de regressão
`PYTHONPATH=src python -m unittest discover -s tests -p 'test_maritime*.py' -v` e `npm ci --ignore-scripts && npm run build`.

## Limitações / gates
- sem captura AIS 24/7, geofences aprovadas ou histórico real;
- sem API privada em nuvem, autenticação, auditoria de acesso ou direito de redistribuição;
- sem previsão ETA/fila homologada, mesmo com motores matemáticos presentes;
- sem IA generativa de produção conectada ao módulo marítimo;
- sem deploy ou gastos autorizados.

Código reutilizado do mesmo proprietário do AgroLogMT; verificar a cadeia de licença do frontend e dados antes de qualquer release comercial.
