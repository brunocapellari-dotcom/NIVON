# NIVON — Verificações privadas pontuais de acesso (USDA, ANA e INMET)

**Data:** 21/10/2026. **Uso:** não comercial. **Estado:** código de testes, não homologação de APIs.

## Prova documental, sem segredos em repositório

- Gmail: três mensagens identificadas em `docs/ACESSOS_ANA_INMET_GMAIL.md`.
- USDA: mensagem de `noreply@api.data.gov` indica chave da plataforma API.Data.gov, **sem comprovar sua validade atual no gateway USDA**.
- ANA: mensagem de cadastramento identifica credenciais, mas autenticação ainda depende de teste.
- INMET: processamento concluído no BDMEP com URL individual; validade e ZIP ainda não verificados.

## Base técnica

API oficial USDA FAS: https://apps.fas.usda.gov/opendatawebv2/
O gateway `https://api.fas.usda.gov/api/psd/commodities` aceita chave API.Data.gov no header `X-Api-Key` segundo documentação e client do agrobr (`agrobr/usda/client.py`). Não usar a URL legada de origem.
Cliente ANA existente: `src/nivon/ana_hidrowebservice.py`; instruções oficiais de fevereiro/2026.
Cliente BDMEP existente: `src/nivon/inmet_bdmep.py`; download de ZIP privado com SHA e checagem de segurança.

## Novo executor opt-in

`src/nivon/acessos_smoke_privado.py`:

- Sem `--live`, produz apenas `REDE_DESATIVADA`, mesmo quando há segredos configurados.
- Com `--live`, executa **uma única fonte por invocação**, e só no executor privado.
- Saída JSON contém somente estado e contagem resumida; não inclui tokens, CPF, senhas, URLs privadas, caminhos de arquivos, hashes brutos, payloads ou erros HTTP externos.
- Nenhum resultado é homologado nem liberado para publicação; não muda catálogos, autorização ou jobs do NIVON.

### Provisionamento seguro — executor privado do NIVON

Configurar os segredos **fora do GitHub e fora da conversa**, somente no ambiente confiável do executor do NIVON:

| Fonte | Variáveis | Procedimento |
|---|---|---|
| USDA FAS | `AGROBR_USDA_API_KEY` | Segredo obtido na mensagem do Gmail, sem copiar para arquivo versionado |
| ANA | `NIVON_ANA_IDENTIFICADOR`, `NIVON_ANA_SENHA` | Recebidos no e-mail oficial de cadastramento |
| ANA opcional (dados) | `NIVON_ANA_ESTACAO`, `NIVON_ANA_DATA_BUSCA`, `NIVON_ANA_ZONA_ESTACAO` | Estação real conhecida, data AAAA-MM-DD, timezone comprovado |
| INMET | `NIVON_INMET_BDMEP_URL`, `NIVON_INMET_DIRETORIO_PRIVADO` | URL individual; diretório já existente, privado e com permissões restritas |

**Não usar GitHub Actions em pull requests para executar acessos autenticados.**
Se for utilizar um serviço com secrets manager, exigir credenciais isoladas, logs redigidos, egress limitado aos domínios oficiais, sem artefatos de CI que contenham os dados. Não disponibilizar credenciais em comandos shell, commits ou parâmetros URL.

### Execução

```bash
# Verificação offline, sem rede:
PYTHONPATH=src python -m nivon.acessos_smoke_privado --fonte usda
PYTHONPATH=src python -m unittest discover -s tests -p 'test_acessos_smoke_privado.py' -v

# Exclusivamente no executor privado onde os segredos já estão provisionados:
PYTHONPATH=src python -m nivon.acessos_smoke_privado --fonte usda --live
PYTHONPATH=src python -m nivon.acessos_smoke_privado --fonte ana --live
PYTHONPATH=src python -m nivon.acessos_smoke_privado --fonte inmet --live
```

**Cuidado INMET:** `--live` realiza um download para o armazenamento privado. Não executar novamente desnecessariamente nem anexar o ZIP ao PR. Se o endereço expirar, solicitar novo processamento/URL via BDMEP oficial.

**Interpretação dos estados:**
- USDA `AUTENTICACAO_E_SCHEMA_OK`: API respondeu com lista JSON estruturada; não prova cobertura histórica.
- ANA `AUTENTICACAO_OK_CONSULTA_PENDENTE`: token recebido, mas nenhuma medição lida. `AUTENTICACAO_E_LEITURA_OK`: endpoint de dados validado e medições checadas.
- INMET `ZIP_RECEBIDO_E_INSPECIONADO`: ZIP privado salvo e inventariado; parsing e uso analítico ainda pendentes.

## Estado operacional e impedimento da execução agora

Não foi encontrado executor NIVON existente nas conexões de infraestrutura consultadas. O único serviço Render acessível pertence a outro projeto; os projetos Vercel disponíveis também não correspondem ao NIVON. Não mover credenciais Gmail para esses projetos. Os conectores GitHub disponíveis não permitem configurar secrets do repositório; não ativar acessos por parâmetros sensíveis em tool calls.

**Próximo gate:** disponibilizar um executor NIVON isolado e de custo autorizado, provisionar segredos em armazenamento privado e fazer as três verificações reais. Até lá: manter `AGROBR_USDA_API_KEY`, ANA e INMET sem autenticação comprovada, direitos por operação pendentes, catálogo desativado.

## Escopo excluído

O NIVON não executa receituário agronômico e não possui finalidade comercial.

## Continuidade técnica de 21/10/2026 — validação estrita de respostas

- USDA/FAS: a resposta HTTP 200 com JSON não implica sucesso; a consulta de catálogo de commodities deve ser lista não vazia de objetos com `commodityCode` de sete dígitos e `commodityName` textual preenchido, como nos dados oficiais documentados pelo agrobr. Um JSON de erro ou catálogo truncado/anômalo é `SCHEMA_INESPERADO`. HTTP 429 é `LIMITE_API_ATINGIDO`; 502/503/504 são `SERVICO_TEMPORARIAMENTE_INDISPONIVEL`. Esses estados não autorizam ingestão.
- ANA: um token válido e uma consulta com **zero medições** agora produzem `AUTENTICACAO_OK_SEM_MEDICOES`, sem afirmar que houve leitura de dados ou homologação. Status de rede/arquivo continuam privados e sem segredos.
- Verificação Vercel em 21/10/2026: projeto `nivon` existe, mas lista de sandboxes está vazia; tentativa prévia de criação v2 retornou **403 forbidden**. Não insistir em chamadas equivalentes sem mudança verificável de permissão/conta; manter bloqueio real.
- Testes: incluídos casos positivos e adversariais para recusar JSONs de erros HTTP 200, ausência de campos USDA, serviço indisponível/429 e estação ANA sem medições. A CI valida a PR; **não atribuir operação live à execução da CI**.

## Alternativa sem Sandbox Vercel: GitHub Actions manual e protegido

Foi acrescentado o workflow `.github/workflows/acessos-privados.yml` como alternativa à falha de autorização **403** na criação de Sandbox Vercel. Ele permanece **inativo enquanto estiver somente nesta PR**: o GitHub exige que workflows manuais estejam no branch padrão para acioná-los.

**Não executar com credenciais em PRs.** Depois que as PRs dependentes forem integradas com revisão, o proprietário poderá:

1. No GitHub, abrir NIVON → Settings → Environments → criar `nivon-fontes-privadas`, restringir a implantação à branch `main` e configurar revisores obrigatórios, quando disponível.
2. Configurar **somente nesse environment**, nunca em arquivo, as credenciais `AGROBR_USDA_API_KEY`, `NIVON_ANA_IDENTIFICADOR`, `NIVON_ANA_SENHA`, `NIVON_INMET_BDMEP_URL`. Esses valores deverão ser extraídos pelo proprietário de seus e-mails originais em uma sessão autenticada; não transferir do Gmail por ferramentas de chat, PR, artefatos ou logs.
3. Para estação ANA opcional, configurar as variáveis **sem segredo** `NIVON_ANA_ESTACAO`, `NIVON_ANA_DATA_BUSCA`, `NIVON_ANA_ZONA_ESTACAO`, de acordo com estação e fuso confirmados. Sem essas configurações, apenas o token será validado.
4. Abrir Actions → **NIVON - Verificacao privada manual de APIs** → Run workflow → **main** → escolher uma fonte por execução. Verificar o status sanitizado, sem fazer upload de dados.
5. INMET recebe um ZIP em diretório temporário isolado, **sem preservação entre execuções e sem artifact**. A carga histórica real exigirá armazenamento privado persistente e verificação adicional de permissões/metadata antes do uso.

O workflow possui somente `workflow_dispatch`; cada fonte é um job separado com o mínimo de segredos de que precisa, somente na `main`, ambiente protegido, permissões `contents: read`, sem agendamento, sem job em push/PR, e sem publicação de arquivo. O custo depende dos limites da conta GitHub; não declarar cobrança zero garantida.

**Não habilitar o workflow em `main` antes de revisar o código e habilitar proteções de environment.** Nenhum teste live decorre automaticamente da inclusão deste workflow, mesmo que os testes sintéticos da CI passem.
