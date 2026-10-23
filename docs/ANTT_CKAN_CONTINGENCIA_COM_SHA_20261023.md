# NIVON — Contingência ANTT CKAN com evidência de fontes oficiais (23/10/2026)

O catálogo CKAN da ANTT mostrou falhas intermitentes: primeiro arquivo de 2026 exigiu reexecução; a rotina histórica 2006–2021 falhou porque package_show retornou HTML/JSON inválido mesmo após repetição. O comportamento correto é falhar fechado, **nunca transformar HTML em CSV ou fabricar volumes**.

## Referências preservadas de acesso oficial real

Execução anterior: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944237120

Artefatos do GitHub Actions, contendo arquivos **manifesto-antt.json** com URL de cada CSV, identificador de recurso CKAN, data de coleta, SHA-256 e quantidade de registros:
- 2006–2010: artifact ID 12496219833
- 2011–2015: artifact ID 12497057471
- 2016–2020: artifact ID 12496953489
- 2021–2024: artifact ID 12497078327

As referências por ano estão congeladas em src/nivon/antt_historico_verificado.py, sem armazenar conteúdo bruto ou credenciais no repositório. Correspondem a **19 arquivos anuais**; 2025 e 2026 têm URLs próprias já verificadas no módulo transporte_multimodal.py.

## Regra de fallback, opt-in e segura

1. Tentar sempre o catálogo CKAN oficial e aceitar novas revisões segundo sua validação de formato.
2. Quando o catálogo retornar somente erro transitório documentado (JSON inválido ou HTTP 429/5xx), permitir URL histórica exata apenas se a flag de contingência estiver ativa.
3. Para 2006–2024, o CSV direto deve ter o **mesmo SHA-256 anteriormente observado**. Caso contrário, BLOQUEAR e aguardar CKAN restaurado para validar revisão nova. Nunca tratar dados antigos como atuais.
4. Validar HTTPS, host dados.antt.gov.br, UUID do recurso e nome anual exatos; não seguir redirecionamentos; não contornar HTTP 401/403; validar cabeçalho, competências, TU e TKU.
5. Marcar o manifesto com descoberta_fonte=URL_OFICIAL_PREVALIDADA_SEM_CKAN_ATUAL, preservando também origem_evidencia e sha_anterior.
6. Não adicionar anos sem manifesto oficial previamente observado. Qualquer divergência de SHA bloqueia escrita no GCP.

A execução histórica permanece dividida em cinco lotes, cada um com limites de bytes e linhas e reconciliado no BigQuery após carga; não ativa atualizações recorrentes. A evidência de URLs/hashes não é autorização para ignorar licenciamento, nem dispensa auditoria histórica.
