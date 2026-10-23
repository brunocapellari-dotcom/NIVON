# IVO — Rodada 18: consumo real da PAM, alertas materiais e entrega a relatórios

**Data:** 23/10/2026. **Branch:** `feat/ivo-governed-learning-20261019`,
PR #7, baseado no núcleo do NIVON. Trabalho executado sem merge, deploy,
cobrança de nuvem, credenciais novas ou treinamento preditivo real.

## Priorização consolidada desta rodada

| Prioridade | Implementação | Validação |
|---|---|---|
| P0 | IVO consultar o banco PAM já alimentado | **Concluído**: console em SQLite somente leitura, sem nova coleta |
| P1 | Detectar apenas revisões relevantes | **Concluído**: comparação de valor/estado com captura anterior da mesma célula |
| P2 | Evitar alerta cruzado por município/cultura/ano | **Concluído**: escopo integral por município IBGE, ano, variável e C81 |
| P3 | Publicar saída por célula para relatórios | **Concluído**: `entrega_ivo_pam.json` com valor/unidade/SHA/ano/coleta |
| P4 | Adicionar alertas e entrega ao ciclo de backup | **Concluído**: exportação na execução, junto de auditoria/ZIP |
| P5 | Comprovar o console com SQLite real anterior | **Concluído**: aceitação GitHub Actions com 24 capturas reais, sem HTTP SIDRA |
| P6 | GCS produção e automação de backup durável | **Ainda bloqueado**: bucket/WIF/conta de serviço não verificados ou ativados |
| P7 | Integrar relatórios amplos do NIVON ao feed | **Próximo lote**: consumir o JSON no editor responsável por publicar |
| P8 | Modelos retrospectivos anuais | **Pendente**: dados antigos da data original de publicação |

## Alterações integradas ao código

- `src/nivon/ivo_pam_alertas.py`: reconstrói sequências de captura
  por identificador canônico `municipio+ano_civil+variavel+C81`
  usando `LAG` do SQLite. Corta por horário de **coleta**, jamais
  chama o instante de publicação da PAM de comprovado. Apenas
  `VALOR_ALTERADO` e `ESTADO_ALTERADO` são eventos materiais;
  `PRIMEIRA_CAPTURA`, `SEM_ALTERACAO` e
  `NOVOS_BYTES_MESMO_VALOR` são contabilizados mas não geram
  alertas. Limites/escopo não podem truncar eventos silenciosamente.
  Cada evento preserva fonte, município, ano civil, indicador,
  cultura, unidade, valor anterior/atual, variação, SHA e instante.
- `src/nivon/ivo_pam_leitura.py`: abertura exclusiva `mode=ro`
  de arquivo SQLite já existente, schema e integridade conferidos,
  `PRAGMA query_only=ON`; recusa arquivo ausente ou link simbólico.
  Não cria outro SQLite vazio como efeito colateral.
- `src/nivon/ivo_console.py`: parâmetros novos `--pam-db`,
  `--municipio`, `--produto`, `--variavel`, `--inicio`,
  `--fim`, `--corte` e `--alertas-desde`. Todos os recortes
  devem ser informados explicitamente; a pergunta não autoriza
  inventar município ou produto. Exibe série anual e eventos do
  escopo; não chama coletor nem executa previsão. Sem argumentos
  PAM, mantém o planejamento anterior compatível.
- `src/nivon/ivo_pam_entrega.py`: constrói JSON editorial
  estruturado por célula, usando `painel_pam_ivo` existente,
  diferença anual somente para anos consecutivos, sem médias
  municipais nem conversão de PAM em safra/mês/produção final
  certificada. O relatório preserva `sha256_original` e captura.
- `src/nivon/ivo_pam_ciclo.py`: após restaurar backup e coletar,
  calcula alertas estritamente posteriores ao último timestamp
  do backup anterior, monta entrega IVO, executa auditoria/backup
  e grava `alertas_pam.json`, `entrega_ivo_pam.json`,
  `resultado_ciclo.json` e `auditoria.json`.
  Coletas idênticas permanecem no histórico, mas não criam
  alertas de revisão falsa.
- `src/nivon/ivo_pam_consulta.py`: CLI isolado também usa
  SQLite de consulta em modo somente leitura, sem criação.
- `.github/workflows/ivo-pam-piloto.yml`: exporta os dois JSON
  novos junto do backup verificado, sem criar novos gatilhos.
- `tests/test_ivo_pam_consulta_alertas_e2e.py`: E2E de coleta
  local, histórico, filtros, revisão, sigilo, sem mudanças,
  corte as-of, console e três ciclos com restauração/backup.

## Aceitação real sobre dados do SIDRA previamente capturados

O workflow novo `.github/workflows/ivo-pam-aceitacao-real.yml`
usa o artifact **real** de 24 capturas do
[run 39946796466](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946796466)
e executa uma aceitação com o código atual, **sem coletar de novo**.

**Execução aprovada:**
[GitHub Actions 40001515540](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001515540).
Restaurou o ZIP com manifesto e verificou:
- 24 capturas preservadas e 6 vintages distintas;
- quatro células anuais de soja em grão da PAM para
  Tangará da Serra-MT / IBGE 5107958 / variável 214 / C81 2713:
  2021 = 382.800 t; 2022 = 400.200 t;
  2023 = 423.540 t; 2024 = 364.048 t;
- consulta de alertas neste acervo: **zero mudanças materiais**,
  coerente com os SHA e valores repetidos nas recoletas;
- corte `2026-10-23T02:30:00+00:00`, **antes da primeira captura**,
  retornou células sem valores (sem vazamento temporal);
- confirma flags `coleta_nova_executada=False` e
  `modelo_preditivo_executado=False`.

Essa evidência valida a **leitura e tratamento do histórico capturado**
e não a recuperação do conteúdo que teria sido publicado em 2021
antes de eventuais erratas. Publicação oficial histórica distinta
de timestamp de coleta.

A suíte completa no mesmo SHA
`44bc55b73c210899e0b2355696a6c33554c84a92`:
[GitHub Actions 40001515470](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001515470) —
**1.285 testes executados, 8 ignorados, 1.277 aprovados**.
Testes opcionais ML não equivalem a modelos instalados em produção.

### Comando IVO para um banco local restaurado

```bash
PYTHONPATH=src python -m nivon.ivo_console \
  --pergunta "Como evoluiu a soja em Tangara da Serra?" \
  --pam-db diretorio_restaurado/pam.sqlite \
  --municipio 5107958 --produto 2713 --variavel 214 \
  --inicio 2021 --fim 2024 \
  --alertas-desde 2026-10-23T00:00:00+00:00
```

A API de leitura aceita `--corte` para um instante UTC conhecido
e não pode transformar dados capturados em outubro/2026 em
dados disponíveis em 2021.

## Próximas ações de maior impacto

1. Substituir leitura pontual no editor do NIVON por consumo do JSON
   `entrega_ivo_pam.json` aprovado, preservando a taxonomia PAM.
2. Separar entrega sintética/revisões reais por origem nas edições
   e produzir alerta apenas se o evento material ocorrer.
3. Validar os três identificadores de Google Cloud Storage/WIF
   existentes e ativar backup automático apenas em infraestrutura
   que não crie custos não autorizados.
4. Expandir tarefas pontuais de PAM para outros municípios e produtos
   de interesse operacional, sem varredura massiva e sem misturar
   área com quantidade ou preços/fretes.
