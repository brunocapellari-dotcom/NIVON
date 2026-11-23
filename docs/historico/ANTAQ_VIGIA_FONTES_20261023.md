# NIVON — Vigia automatica do acesso oficial ANTAQ

**Data inicial:** 23/10/2026. Código: `src/nivon/antaq_fonte_saude.py`; agenda: `.github/workflows/antaq-vigia-fontes.yml`.

Roda diariamente, 12:45 UTC, **somente depois de integrada à main**, em GitHub Actions sem credenciais, armazenamento GCP ou downloads em massa. O objetivo é identificar se a antiga exportação oficial de microdados ANTAQ volta a funcionar e se o espelho HF muda de revisão.

Sondas fixas autorizadas:
- `https://estatistica.antaq.gov.br/ea/sense/download.html` — GET com limite de bytes, sem seguir redirects;
- `https://estatistica.antaq.gov.br/ea/txt/2025.zip` — HEAD apenas, não baixa;
- aviso institucional em `gov.br/antaq` — HEAD;
- `https://huggingface.co/api/datasets/vinicius-souza/antaq` — API de metadados de revisão.

A cada rodada, registra status HTTP, categoria, timestamp e SHA da réplica em JSON efêmero e artefato GitHub com prazo de 30 dias. **Status 200 não homologa uma base**: mesmo o marcador `CANDIDATO_A_DOWNLOAD_OFICIAL` exige validação real do ZIP autorizado, schema, competência, qualidade e licença. HTTP 401/403 não tem bypass, redirect não é seguido, falhas de rede não viram zero. Uma revisão da réplica é apenas aviso para auditar, não autorização de escrita no BigQuery.

Prova inicial 23/10/2026:
- download legado oficial e `2025.zip`: 301, sem acesso validado ao ZIP;
- revisão da réplica HF: `ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8`, sem alteração;
- aviso gov.br: GET 200 na primeira sonda e HEAD 403 na segunda (regras de acesso diferem por método), sem provar disponibilidade operacional.

Evidências:
- https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39951478648
- https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39951660331

Bloqueio P0 #144 continua: aguardar canal de microdados primários com prova de download. A coleta de toneladas reconstruída na réplica de terceiros permanece **NÃO HOMOLOGADA**, não podendo sobrescrever o histórico oficial nem somar rotas hidroviárias sobrepostas.
