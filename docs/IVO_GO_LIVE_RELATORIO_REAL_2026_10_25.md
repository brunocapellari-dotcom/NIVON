# NIVON — Go-live interno por entregas verificadas (25/10/2026, MT)

Este é o registro de **aceitação operacional da frente PAM/IVO**, não
declaração de que o NIVON inteiro ou o terminal Cloud Run estejam em
produção. O escopo do MVP é o relatório anual municipal de soja obtido
da PAM/IBGE, com proveniência verificável, consulta histórica por
coleta, backup e revisão. Projeto não comercial.

## Entrega executada: relatório com dados reais, sem nova coleta externa

- Execução [aceite real PAM 40261123977](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261123977)
  em 25/10/2026 (horário de Mato Grosso). Restaurou o backup
  anteriormente coletado com **24 capturas, 6 vintages distintas**,
  verificou SQLite/bytes/recibos, consultou seis células PAM/SIDRA 1612,
  e produziu **HTML estático, Markdown, JSON estruturado e auditoria**.
  Não realizou GET do SIDRA no teste de aceitação. As capturas de
  origem são de 23/10/2026 UTC; o relatório foi gerado em
  26/10/2026 UTC. Nenhuma revisão de valor apareceu nesse histórico.
- [Suíte 40261123920](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261123920):
  **1.288 testes executados, 8 ignorados e 1.280 aprovados**.
- Pacote de relatório salvo no Google Drive do projeto:
  [NIVON IVO — relatório PAM real](https://drive.google.com/file/d/1vVSTkT9M2DsatmFF3Ur8Tpk0foPFPwHX/view?usp=drivesdk).
  O artifact do GitHub está sujeito a expiração (não é backup permanente).
- `src/nivon/ivo_pam_relatorio.py`: saída HTML autocontida e Markdown
  com município IBGE, ano civil, cultura, indicador, toneladas, hora
  de coleta UTC e SHA original. Escapa texto HTML; não apresenta
  valor faltante como zero nem captura como data de publicação.
- `src/nivon/ivo_pam_aceite.py`: **backup validado -> restauração ->
  relatório** totalmente offline, com falha se qualquer célula exigida
  não estiver presente. Não cria servidor público.
- `src/nivon/ivo_pam_ciclo.py` e
  `.github/workflows/ivo-pam-piloto.yml` passam a produzir HTML/MD
  após cada ciclo de coleta bem-sucedido, junto ao backup e aos JSONs.
- `.github/workflows/ivo-pam-relatorio-real.yml`: executa o aceite
  usando o backup real de 24 capturas, publica os cinco arquivos
  de relatório, sem consultar dados externos.

## O que já existe no branch principal e deve ser reutilizado

Em 25/10/2026 o `main` do repositório está à frente do antigo
branch-base do IVO e inclui os workflows
`nivon-terminal-go-live.yml`, `nivon-go-live-interno.yml` e
`nivon-go-live-readonly.yml`.

O diagnóstico real [40257929205](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257929205)
demonstrou:
- autenticação federada Google Cloud operacional;
- projeto **`nivon-data`**, dataset **`nivon_raw`** e bucket
  **`nivon-data-raw-2026`** existentes, ambos na região
  **`southamerica-east1`**;
- a tabela **`agro_fonte_stage` não existia** naquele instante
  (o job saiu com código 4).

O workflow do terminal
[40261018737](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261018737)
passou os testes e o diagnóstico de metadados, mas o job de deploy
foi **ignorado**. O workflow de painel interno
[40261402117](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261402117)
passou a qualidade, mas a publicação em GCS foi **ignorada**.
Portanto não existe confirmação de URL/serviço interno publicado.

A frente IVO/PAM agora referencia as **variáveis do GCP já existentes**
`NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`,
`NIVON_GCS_BUCKET`. Nenhuma identidade ou bucket paralelo.
A publicação automática no GCS continua exigindo
`NIVON_PAM_GCS_WRITE_APPROVED=true` e
`NIVON_GCP_COST_REVIEWED=true`, pois o uso de dados públicos
não elimina o controle de ativação de recursos pagos ou IAM.

## Caminho crítico real, em ordem

| Ordem | Próximo trabalho | Critério de aceite |
|---|---|---|
| 1 | Consolidar mudanças recentes do `main` com PRs antigos | PR #1 não está `dirty`; evitar sobrescrever código já merged |
| 2 | Corrigir existência/schema da tabela `agro_fonte_stage` | diagnóstico `readonly` concluído sem erro |
| 3 | Completar pré-requisitos privados do terminal Cloud Run, se custo autorizado | preflight + serviço privado com revisão IAM; nunca público |
| 4 | Publicar primeira edição interna via `nivon-go-live-interno.yml` | GCS com readback e relatório verificável |
| 5 | Adicionar as saídas PAM/IVO ao painel principal | uma única experiência de consulta, não várias interfaces paralelas |
| 6 | Implantar backup automático e alertas | recuperação do estado incremental em novo runner e auditoria |
| 7 | Expandir CEPEA, IMEA, CONAB, Argentina, logística e marítimo | E2E com dados atuais, estados e cadência por fonte |

A dependência técnica central para o **go-live de todo o NIVON** não é
mais a ausência de código de relatório PAM, mas a integração de branches,
a cobertura das fontes críticas e os gates explícitos de publicação
privada no Google Cloud. Não forçar merge/deploy sem evidências.

## Integridade epistemológica

Valores da PAM/IBGE são **estatísticas anuais informadas**. As
24 capturas representam múltiplas consultas das mesmas seis células,
NÃO 24 anos, novas vintages ou realizações agrícolas. A captura de
outubro de 2026 NÃO reconstrói a versão disponível ao usuário em 2021.
O relatório não produz previsões nem usa dados sintéticos como fatos.

O PDF/HTML não contém credenciais e é destinado a revisão interna.
A planilha/banco original continua separado no acervo de proveniência.
