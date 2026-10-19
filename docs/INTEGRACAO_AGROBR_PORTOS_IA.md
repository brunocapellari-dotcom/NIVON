# NIVON — Integração agrobr, portos, previsão e agentes (19/10/2026)

## Estado comprovável
Esta entrega incorpora **código** e **testes offline**, não go-live, licença comercial,
servidor, conexão Meta/CME ou promessa de previsão validada.

- CONAB Progresso Semanal: src/nivon/conab_agrobr.py chama agrobr.conab.progresso_safra
  e semanas_disponiveis em instalação opcional agrobr==2.0.0.
- Séries percentuais: cultura + safra + Semeadura/Colheita + UF + semana;
  mantém pct da semana atual, semana anterior, ano anterior e média de 5 anos;
  preserva marcador revisado, cobertura de área e média CONAB dos estados.
  **MEDIA_ESTADOS != BR**. Data de publicação desconhecida é NULL, sem substituir
  pelo horário da coleta.
- Portos: portos_automaticos.py usa aquisição HTTPS segura já existente,
  com allowlist e direitos por operação. HTML do antigo AgroLog para Santos/CDP
  e PDF para Paranaguá/Itaqui com pdfplumber **opcional**. Outros portos
  não têm parser homologado e falham fechado.
- Previsões: previsoes_bibliotecas.py integra StatsForecast AutoETS em série
  mensal, checa calendário e realiza walk-forward vs baseline sazonal.
  Sem vintages de dados reais, permanece CENARIO_NAO_HOMOLOGADO.
- Briefing: briefing_composto.py combina notícias de 24h com indicadores
  datados e fretes **anunciados** nos corredores Sorriso/MT–Rondonópolis/MT e
  Sinop/MT–Miritituba/PA. Exige licença específica para CBOT e outros indicadores.
- Agentes: agentes_nivon.py define fronteira read-only e coordenador E2E offline.
  Executor de LLM/Hermes ainda não conectado; sugestão textual não adquire
  autoridade para publicar, alterar dados, gastar ou despachar mensagem.
- Entrega WhatsApp: adaptador com quatro gates, desativado por padrão; mesmo
  depois do aceite do provedor, o retorno **não** equivale a entrega ao usuário.
  Exige outbox durável e idempotência para operação em nuvem.

## Proveniência de código reutilizado

1. https://github.com/bruno-portfolio/agrobr — **MIT**, versão 2.0.0 publicada
   em 10/10/2026. Integração como dependência opcional, sem incluir seu código
   no repositório NIVON. **Licença MIT do software não licencia automaticamente
   coleta, armazenamento, retransmissão ou distribuição dos dados CONAB**.
2. Código de parsing portuário oriundo do repositório da mesma conta:
   brunocapellari-dotcom/AgroLogMT, caminhos
   collector/official_lineup_html.py e collector/official_lineup_pdf.py.
   Cópias internas identificadas em _agrolog_portos_html.py e
   _agrolog_portos_pdf.py. Registrar hash exato do commit de origem e verificar
   titularidade/licença antes de liberação comercial; não importar cloud_store,
   BigQuery ou agendamento legado.
3. https://github.com/Nixtla/statsforecast — licença Apache-2.0.
   A instalação em NIVON é opcional para preservar o núcleo mínimo.
4. https://github.com/jsvine/pdfplumber — contrato técnico condicionado
   ao pacote extra "ports"; inspecionar licenças das dependências transientes.
5. Extras de processamento: DuckDB, Polars e Pydantic disponíveis por
   pip install -e '.[analytics]'; integração geral de modelagem/cálculo
   ainda não validada com datasets produtivos.

## Instalação

Runtime offline padrão, sem chamadas de rede:
    python -m pip install -e .
    PYTHONPATH=src python -m unittest discover -s tests -v

Bibliotecas por responsabilidade, sem forçar dezenas de dependências:
    python -m pip install -e '.[agro]'
    python -m pip install -e '.[forecast]'
    python -m pip install -e '.[ports]'
    python -m pip install -e '.[analytics]'

Nenhuma instalação/acesso agendado é disparado automaticamente por este PR.

## Gates obrigatórios para ativação (por fonte)

1. Atestar direitos de CONSULTA, COLETA, ARMAZENAMENTO, TRANSFORMAÇÃO e
   PUBLICAÇÃO/REDISTRIBUIÇÃO para a finalidade concreta.
2. Rodar no mínimo 3 capturas reais de cada porto em dias distintos; comparar
   contagem, nomes, data e volumes ao arquivo original. Datas das capturas
   não provam que um ETA/atracação tenha ocorrido.
3. Backfill CONAB até a edição autorizada mais antiga acessível, versionar
   e preservar revisões, e comprovar dados da safra com CONAB oficial.
4. Persistir raw autorizado e série normalizada em servidor remoto sem
   vazamento para GitHub; backup e **restore** real; monitorar SOURCE_LAG.
5. Executar regressão com edições reais, faltantes, mudanças de layout,
   calendário, tipos de dados, licença, duplicatas, falhas de rede, custo.
6. Motor StatsForecast: documentar vintage as-of, dados observados,
   backtest walk-forward independente, baseline, erro e incerteza.
7. Provedor IA real: autenticação, orçamento zero aprovado, logs de ações
   sem PII, proteção contra injection, testes de regressão, aprovação de
   publicação por auditor determinístico.
8. Provedor de WhatsApp: consentimento, template aprovado, política Meta,
   custos, outbox persistente, idempotência, ACK e E2E. Nunca enviar
   por simulação de template ou API.

## Pendências concretas

- CONAB: outros produtos, custos, armazéns e evolução de plantio precisam
  de amostras reais/validação e agendamento; progressos de agrobr não são
  homologação por si só.
- Portos: PDF usa uma página de série por recurso, com detecção conservadora.
  Multi-PDF, JavaScript, login e bloqueios não são contornados; precisam de
  conectores e acesso legítimo específicos.
- Inteligência Nivon: forecasting mensal adicionado, mas não existe ainda
  um motor validado de paridades, projeção de frete, clima, ETA ou otimização
  para todos os mercados. Os cálculos sintéticos não autorizam publicação.
- Briefing: dólar/CBOT/fretes são apenas contratos de dados com gates;
  não há conector pago de market data ou motor editorial LLM operando.
- Nuvem: não houve deploy, merge em main, ativação agendada ou gasto.

**Orientação de homologação:** conteúdo e cálculo determinísticos não devem
ser confundidos com dados reais, e nenhuma execução automatizada com rede
pode ignorar os direitos ou o custo zero estipulado pelo usuário.


## Incremento operacional — memória de safra, escala e briefing (19/10/2026)

- progresso_store.py: SQLite com chaves (cultura/safra/operação/UF/semana),
  checksum da edição, coleta reexecutável e consulta as-of. Revisões da
  mesma semana geram nova edição; publicação desconhecida não entra no backtest.
  atualizar_progresso() descobre semanas e permite retrocarga limitada; a
  execução real exige permissão explícita de coleta/armazenamento e evidence_id.
  O arquivo XLSX original ainda não é arquivado por este módulo.
- portos_store.py: SQLite para programação marítima normalizada; conserva
  navio, ETA previsto, terminal, DUV e hashes de documento, permitindo múltiplas
  capturas do mesmo documento sem duplicar versões.
  O snapshot não prova embarque, atracação ou descarga efetiva.
- portos_paranagua.py: localiza edição mais recente por série (Oeste, Leste,
  importação de sólidos) no índice oficial, exclui atas de atracação da procura
  por line-up e seleciona apenas PDF único autorizado na página da edição.
  Ainda faltam casos reais que comprovem layout, MIME e extração.
- outbox_briefing.py: registro idempotente por data local e destinatário
  pseudonimizado HMAC-SHA256, com estados PENDING -> RESERVED ->
  ACCEPTED -> DELIVERED somente mediante ACK autenticado. Não armazena
  número telefônico ou corpo do texto. Retry de estado ambíguo não é automático;
  reconciliação segura, store de texto cifrado e provedor real são pendências.

### Critérios de implantação

1. Bancos SQLite devem estar em volume persistente na nuvem com snapshot e
   ensaio de restauração; banco em runner efêmero não constitui memória durável.
2. Captura automatizada só se autorizações e direitos da operação
   (coleta/armazenamento/publicação) estiverem comprovados e auditáveis.
3. Histórico/indicadores continuam insuficientes para certificação comercial até
   provas com dados reais, vintages e auditoria.
4. No briefing, a fila não envia mensagens; o operador de entrega só deve
   reservar após template/consentimento/custo aprovados, sistema de antifraude,
   credenciais gerenciadas e webhook verificado.
5. A infraestrutura de CI não deve publicar snapshots brutos, segredos nem
   dados individuais ao GitHub.
