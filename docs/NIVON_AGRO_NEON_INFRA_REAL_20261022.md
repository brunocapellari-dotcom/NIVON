# NIVON — Infraestrutura agrícola persistente (Neon Free)

**Atualização verificada:** 22/10/2026 em Mato Grosso, eventos na madrugada UTC de 23/10/2026.

A infraestrutura abaixo foi **criada e consultada** via conexão Neon autorizada. Os IDs e hosts são localizadores públicos do serviço, não credenciais. **Nenhuma senha, URL temporária assinada ou token deve ser enviado ao GitHub.**

## Projeto PostgreSQL agrícola: separado da PTAX

- Projeto Neon: **NIVON-AGRO-DADOS** (`little-snow-10994610`), região `aws-sa-east-1` (São Paulo).
- Branch padrão: `br-crimson-union-b6dphq9e` (principal), PostgreSQL 17, banco `nivon_agro`.
- Endpoint identificado via connector: `ep-fancy-lake-b6xqxo0u.c-2.sa-east-1.aws.neon.tech`.
- Conta/organização: Free, identificada diretamente no conector. Configuração de compute mínimo/máximo 0,25 CU, limite exibido de 1 GiB por branch. O plano gratuito não garante disponibilidade ininterrupta, backup independente ou throughput de produção.
- Migração `sql/postgres/002_zarc_mt_staging.sql` **já aplicada neste banco real**: `nivon_agro_staging.zarc_edicoes`, `zarc_coletas`, `zarc_linhas_mt` e índices. Consulta posterior verificou que essas três tabelas existem, com **zero edições e zero linhas reais**.
- Migração `sql/postgres/003_zarc_ckan_sinais.sql` **já aplicada**: `nivon_agro_staging.zarc_ckan_sinais`. Há **uma observação de metadados reais** inserida e consultada pelo connector Neon:
  - Coleta original: `2026-10-23T03:00:18.102438+00:00`.
  - Recurso: `139e5a60-1f43-4cc8-aeab-a35dbbf816c0`.
  - Licença: `cc-by`.
  - Revisão CKAN recurso: `23321f88-93a2-4c8f-b956-27d83f6d84f6`.
  - Fingerprint de metadados: `a96f4fb03cb44364af7b0df4f12ba9d22eef86c127b0cfbe31a83066c9832931`.
  - Prova: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39892626092.
  - `pacote_modified_text` e `recurso_modified_text` preservam os tempos sem offset do CKAN, **sem atribuir fuso ou afirmar atualização de CSV**.
- `src/nivon/zarc_ckan_neon.py` oferece a escrita transacional idempotente desse sinal, com hostname e database explicitamente restritos. A implantação agendada **não foi ativada**.

## Arquivo original RAW: bucket privado separado

- Região São Paulo do Neon retornou `region_unavailable` para Object Storage, apesar de suportar PostgreSQL. A separação abaixo é intencional; não presumir armazenamento de objetos disponível em São Paulo.
- Projeto Neon **NIVON-ARQUIVO-RAW** (`jolly-queen-35369598`), região `aws-us-east-1`.
- Branch principal `br-restless-paper-b72vbhp7`.
- Bucket criado e verificado: `nivon-zarc-raw`, **private**.
- A listagem do bucket retornou **0 objetos**. O arquivo oficial ainda **NÃO foi enviado**, apesar de o coletor ter sido capaz de lê-lo anteriormente em um runner efêmero.
- `src/nivon/zarc_neon_raw_upload.py`: prepara cópia Gzip determinística e só admite URLs temporárias de PUT/GET com SHA no caminho esperado e domínio desse bucket; exige `executar=True`. **PUT sem GET completo e SHA original não é sucesso.**
- As URLs temporárias são obtidas pelo conector `presign_storage_object`, com `operation=upload/download`, `bucket_name=nivon-zarc-raw`, `object_key=zarc/2026-2027/<sha_original>.csv.gz`, `content_type=application/gzip` para PUT. **URLs nunca devem ser logadas, postadas no GitHub, incluídas em prompts ou passadas em CLI visível.** Fornecer por variáveis de ambiente efêmeras/canal protegido.
- Testes de upload com cliente HTTP sintético verificam host, caminho, TLS, assinatura, conteúdo Gzip, corrupção e redirecionamentos. Eles **não comprovam upload real** nem backup independente.
- Armazenamento de objeto com verificação remota não substitui uma segunda cópia e teste de restauração fora do mesmo provedor.

## Próximos passos sem retrabalho

1. **RAW real:** obter novamente o CSV oficial ZARC 2026/2027 mediante GET autorizado; verificar tamanho e o SHA atual, lembrando que `65f52578a4869894311888323d87db75a5452829a3dabef90786f3f14b02d652` foi observado em execução anterior e pode ter mudado. Não presumir que a edição atual tem SHA igual.
2. Verificar contrato CSV, 55 colunas, 27.918 linhas de MT **na edição antiga** — a quantidade pode mudar em nova edição. Aplicar atribuição MAPA, controlar origem e não inventar data de publicação de Portarias.
3. Gravar edição RAW com key por SHA no bucket privado e recuperar para prova de integridade. Habilitar escrita agrícola somente com a governança canônica revisada; **não mascarar arquivo real com tipo SINTETICO**.
4. Promover staging para PostgreSQL agrícola, comparar linhas e hashes integralmente, manter `publicavel=false` e `apto_backtest=false` até validação agronômica.
5. Acrescentar serviço de observação de revisões CKAN com credenciais armazenadas fora do GitHub público; após aprovação, agendar apenas o monitoramento de metadados e fazer download completo quando houver sinal confirmado e economia de banda.
6. Monitorar cotas Free de PostgreSQL, Object Storage, compute e transferência; as capacidades publicadas são limites, não direito a excedente gratuito.
7. Não apagar nem modificar os projetos PTAX preexistentes. Não criar projeto pago/upgrade automático. Não considerar armazenamento em um único provedor como backup definitivo.

## Proveniência e distinções

| Camada | Situação real |
|---|---|
| Projeto agrícola PostgreSQL | Criado, esquema instalado |
| Observação CKAN real | 1 linha persistida |
| Edicões oficiais no PostgreSQL | 0 |
| Registros ZARC MT no PostgreSQL | 0 |
| Bucket privado RAW | Criado, 0 objetos |
| Carregador PostgreSQL | Aprovado apenas em PG17 descartável com dados sintéticos |
| Uploader RAW | Aprovado em testes sintéticos de rede |
| Agendamento produtivo | Não habilitado |
| Cobrança ou upgrade | Nenhum plano pago contratado nesta implementação |

**Regra permanente:** artefatos de CI e metadados em Neon são evidências distintas de ingestão agrícola operacional. Não relatar número de observações reais como registros no banco até carga real efetivamente concluída.
