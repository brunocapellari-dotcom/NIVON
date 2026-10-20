# Nivon — Plano oficial de histórico meteorológico INMET

**Corte documental:** 19/10/2026. **Estado:** inventário e pré-processamento em código, sem extração operacional automática.

## Fontes oficiais verificadas
- Índice anual do INMET: https://portal.inmet.gov.br/dadoshistoricos/
- ZIP por ano publicado no mesmo índice: https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip, https://portal.inmet.gov.br/uploads/dadoshistoricos/2025.zip, com arquivo de 2000 igualmente indexado.
- Segundo o índice público, em 19/10/2026 o ZIP de 2026 estava identificado como atualizado **até 30/09/2026**. Não considerar esse ZIP como telemetria das últimas 24h.
- BDMEP: https://bdmep.inmet.gov.br/ permite solicitar CSV por e-mail e usa fluxo de confirmação/geração. Não automatizar ou contornar esse processo; tabelas de menor intervalo estão no sistema TEMPO.

## O que já existe no PR #1

- Planejamento parametrizado de downloads anuais entre 2000 e 2026, sem rede, sob contrato de licença pendente.
- Inventário de ZIP **local** usando biblioteca padrão; não extrai no disco e bloqueia traversal, membros repetidos, links simbólicos, arquivos grandes e razão excessiva de compressão.
- Leitura de CSV em memória apenas por nome explícito, com limite de tamanho e CRC verificado.
- Histórico versionado de estações e variáveis: src/nivon/series_ambientais.py; acesso temporal as-of e bloqueio de valores/unidades inconsistentes.
- Testes de segurança e processamento sintético: tests/test_inmet_historico.py e tests/test_series_ambientais_ana.py.
- Registro no motor METEOROLOGIA, sem marcar como coleta operacional.

## O que falta antes de fazer o primeiro backfill real

1. Revisar direitos de download, armazenamento, uso interno, uso comercial e redistribuição em separado.
2. Baixar somente por fluxo autorizado e controlado, com limites de memória, tráfego e tamanho, hash SHA-256 e histórico de captura.
3. Conferir arquivo ZIP real por ano, identificadores e mudanças de schema, horas UTC versus datas locais, valores nulos e marcadores de qualidade.
4. Implementar parser do formato observado e testes com fixture de amostra oficial autorizada, antes de transformar horas em precipitação diária e Tmin/Tmax.
5. Armazenar de forma durável, fazer backup/restauração e validação de integridade antes de permitir séries operacionais.
6. Para informação diária recente, integrar fonte atualizada do INMET ou serviço equivalente com licença e janela de latência verificadas — não reutilizar o ZIP anual como informação de hoje.

**Separação metodológica:** o diretório anual INMET entrega observações históricas, não previsão do tempo, seca projetada ou alerta hidrológico. Séries pluviométricas não substituem cota e vazão ANA.

**Segurança:** não executar ZIP, não salvar extrações não homologadas no repositório GitHub, não ativar coleta agendada, não inserir segredo pessoal/credencial nem realizar deploy.
