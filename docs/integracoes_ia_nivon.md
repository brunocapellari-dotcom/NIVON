# NIVON — Integrações de apoio (P0–P2)

## Catálogo adicional aprovado para avaliação (26/10/2026)

As seis capacidades **P1–P2** avaliadas nas referências externas (Docling, OpenWiki, Future AGI, Skills for Real Engineers, Caveman e Qdrant) estão registradas em [CATALOGO_FERRAMENTAS_IA_P1_P2_20261026.md](CATALOGO_FERRAMENTAS_IA_P1_P2_20261026.md), com escopo, pontos de reuso, critérios de aceite, limites de custo e regras para evitar serviços duplicados.

**Situação:** catalogadas para testes posteriores; não instaladas, nem ativas, nem homologadas por esta inclusão. Nenhuma dependência nova no M1. O GitHub permanece canônico para o trabalho e BigQuery/RAW auditado para dados.

Estado: **implementação de contratos locais e conectores opt-in**. **Não habilitado em produção**. **Não altera M1**.

## Princípios e responsabilidades

- NIVON é o único projeto ativo. A camada abaixo é subordinada aos pipelines existentes; não constitui nova plataforma.
- M1 (`terminal_web`, Cloud Run, IAP, BigQuery): nenhuma dependência deste pacote; não incluir nos requirements do contêiner ou no deploy. A PR de consolidação M1 continua independente.
- A fonte canônica de tarefas de engenharia permanece GitHub. Papel do Paperclip: leitura consultiva, sem criar fila paralela nem assumir execução.
- A fonte canônica de números é BigQuery/RAW validado com proveniência. Firecrawl, Magnitude, PageIndex e Hindsight jamais criam observações publicáveis automaticamente.
- Rede, instalação de terceiros, consumo de APIs pagas, execução de navegador e envio de PDFs são sempre **desabilitados por padrão**. Não são usados na CI. Nenhum segredo no repositório.
- Serviço em nuvem, não notebook do usuário. Pilotos opcionais ficam em runner isolado, com egress e orçamento aprovados. Nada desta PR cria recursos Cloud Run, Scheduler ou IAM.

## Catálogo e testes sem rede

```bash
PYTHONPATH=src python -m nivon.integracoes_ia.cli catalogo
PYTHONPATH=src python -m nivon.integracoes_ia.cli diagnostico
PYTHONPATH=src python -m unittest discover -s tests -p 'test_integracoes_ia.py' -v
PYTHONPATH=src python -m nivon.integracoes_ia.cli grafo-local src/nivon
```

O catálogo indica *instalado/detectado*, não disponibilidade operacional nem homologação.

## P0 — skills e aceite de entrega

- `engenharia.aceite_trabalho` gera um **registro de verificação pendente**, nunca aprovação final. Registro contém identificador, PR, commit e resultado do teste.
- Uma URL escrita pelo agente não comprova deploy; evidência deve vir de GitHub Actions e do Cloud Run autenticado (leitura real BigQuery) e passar pelos aceites existentes do M1.
- Skills em `.agents/skills/` são instruções versionadas; não executam comandos espontaneamente. Atualização exige revisão do diff, testes e aprovação conforme risco.
- `engenharia.gerar_skill_rascunho` converte texto de fonte aprovada em **rascunho rastreável** (`*.rascunho.md`) com hash e referência; promoção a `SKILL.md` exige revisão. Não copia livro inteiro sem permissão; a entrada deve ser texto cuja reutilização é autorizada.

## P1 — Firecrawl

Conector real `provedores.consultar_firecrawl(url, politica)` utiliza `POST https://api.firecrawl.dev/v2/scrape`, somente Markdown. Requer `FIRECRAWL_API_KEY`, duas autorizações explícitas na política, e domínio-fonte exato previamente aprovado. Retorno: texto + evidência `EXTRAIDO_NAO_VALIDADO`, `publicavel=false`, hash SHA256, referência e data de coleta. Não grava no banco nem altera coletores existentes. Para usar em produção, primeiro validar licença, custo, extração, frescor, direito de reutilização, prevenção de SSRF via egress e comparação com o coletor primário.

## P1 — Magnitude

Script separado `scripts/nivon_magnitude_piloto.mjs` usa **o projeto de automação de navegador** (`magnitudedev/browser-agent`, pacote `magnitude-core`) — não confundir com o projeto atual de inferência local chamado Magnitude. Exige instalação **na nuvem/runner isolado**, credenciais do modelo quando aplicável e autorizações `NIVON_AI_NETWORK_APPROVED=true`, `NIVON_AI_EXTERNAL_APPROVED=true`, `NIVON_AI_APPROVED_HOSTS=dominio.exato`. O piloto só navega em um site HTTPS aprovado, encerra sessão e retorna status `publicavel=false`.

Não há instalação automática, crawl em lote, login, clique de confirmação nem alteração em sistemas externos. O runner deve impedir egress para hosts internos/metadata e seguir redirecionamentos somente para destinos aprovados; os controles de URL do script não substituem isolamento de rede.

## P1 — PageIndex

`provedores.consultar_pageindex(pdf, pergunta, politica)` utiliza a SDK `pageindex` **em modo local** (`PageIndexClient(index=<modelo>, chat=<modelo>)`), para PDF textual já autorizado; importa PDFs locais até 20 MB, explicitamente solicitados. Precisa de SDK instalada no runner e um provedor LLM configurado, pois *local* é a localização do índice, não significa que o conteúdo nunca será enviado a uma API. Exige `NIVON_PAGEINDEX_MODELO` e `NIVON_PAGEINDEX_CHAT_MODELO` e aprovação de rede/serviço externo. Não publicar conclusões sem conferência de página e fonte original. O SDK Cloud/OCR foi deliberadamente excluído deste primeiro contrato para prevenir upload involuntário.

## P1 — Graphify

`engenharia.dependencias_python` já mapeia `import` Python via AST sem executar código, gerando uma camada de dependências **efetivamente utilizável agora**. `engenharia.importar_graphify` reconhece exportação JSON externa com hash, mas **não usa a exportação como verdade canônica**: o formato Graphify pode variar. Uso do `/graphify` (Claude Code skill) é opcional, fora de produção, sem acesso a secrets. Esse adaptador ainda não executa o Graphify automaticamente.

## P2 — Hindsight

`provedores.consultar_hindsight` usa `hindsight-client` para `recall` read-only em banco isolado `NIVON_HINDSIGHT_BANK_ID` e `NIVON_HINDSIGHT_URL`. Usa `NIVON_HINDSIGHT_API_KEY` sem gravá-la. Memória recuperada recebe `MEMORIA_NAO_VALIDADA` e nunca substitui `claim_id`/`evidence_id`, data de competência, fontes originais ou banco operacional. **Não ativa retain/reflect nem instala servidor** nesta fase. Endpoint deve estar atrás de TLS e autenticação, em hostname aprovado.

## P2 — Paperclip

`provedores.listar_paperclip` executa GET somente leitura de `/api/companies/{company_id}/issues?limit=50`, com `PAPERCLIP_API_KEY`, `NIVON_PAPERCLIP_ORIGEM` e `NIVON_PAPERCLIP_COMPANY_ID`. Não cria empresa, agentes, gastos, aprovações, tarefas nem infraestrutura. GitHub permanece como fila e estado de engenharia até decisão explícita em contrário.

## P2 — RTK / llmtrim e Book-to-Skill

- RTK/llmtrim: `diagnostico()` detecta binários **sem executá-los**. `limitar_contexto()` oferece redução determinística nativa com hash e aviso de truncamento; não chama LLM nem substitui informações completas por resumos silenciosos. Acionamento direto de RTK/llmtrim permanece pendente de teste de compatibilidade de versões e de ganho de tokens; não é honesto declarar esses binários integrados ao runtime.
- Book-to-Skill: gerador de rascunhos disponível via `skill-rascunho` no CLI; requer arquivo-texto validado, referência HTTPS e revisão para promoção. Nenhuma conversão automática de obras protegidas.

## Critérios para ampliar sem interromper o go-live

| Capacidade | Estado desta entrega | Próxima prova exigida |
|---|---|---|
| P0 catálogo, skills, aceites | Implementado offline | CI + revisão da PR |
| P1 Firecrawl | Conector HTTP pronto, não executado em fornecedor | Fonte autorizada + credencial + custo + comparação de dados |
| P1 Magnitude | Runner piloto preparado, não executado | Ambiente isolado com dependência instalada + navegação de domínio permitido |
| P1 PageIndex | Conector SDK pronto, não executado em fornecedor | PDF licenciado + SDK/modelos + comparação com leitura humana |
| P1 Graphify | Grafo AST funcional, bridge JSON de Graphify | Exportação real + validação semântica |
| P2 Hindsight | Leitura SDK pronta, sem serviço | Banco isolado, autenticação e recuperação real sem PII |
| P2 Paperclip | GET REST implementado, sem servidor | Servidor autorizado + leitura real, sem novas tarefas |
| P2 RTK/llmtrim | Diagnóstico + redução determinística | Benchmark comparativo antes de chamar binários |
| P2 Book-to-Skill | Gerador auditável de rascunhos | Revisão humana e testes da skill antes da ativação |

**Não usar o sucesso dos testes offline como declaração de go-live, nem alterar o estado do M1 a partir destes resultados.**

## Evidências de inspeção automática do código

O workflow `.github/workflows/nivon-integracoes-ia-ci.yml` executa, sem credenciais nem serviços externos, o **grafo AST dos módulos Python atuais** e o diagnóstico P0–P2, ancorados no `GITHUB_SHA`.

Em cada PR ou push que alterar o pacote de integrações, salva por sete dias um artefato de GitHub Actions, `nivon-integracoes-evidencias`, com `grafo-python.json`, `diagnostico.json` e `evidencia.json`. O sumário exibe contagem real de módulos, relações de importação e capacidades encontradas. Erros de sintaxe ou redução anormal de cobertura fazem a execução falhar.

**Limites:** o grafo representa apenas imports estáticos em Python e não substitui Graphify externo, integração real de provedores, dependências dinâmicas, inventário BigQuery nem aceite do Cloud Run. Os diagnósticos diferenciam `None` (dependência não averiguada ou não aplicável) de `True` (pacote detectado). Ter Node.js no executor não comprova instalação de Magnitude. Um workflow bem-sucedido não confirma dados atualizados nem go-live.

## Pilotos operacionais sob demanda (26/10/2026)

Novo fluxo `.github/workflows/nivon-integracoes-ia-pilotos.yml`: execução **manual**, uma capacidade por vez, em um runner GitHub descartável, sem instalação no dispositivo do proprietário e sem criação de infraestrutura Google Cloud. O executor é `python -m nivon.integracoes_ia.pilotos`, e todos os resultados são **metadados sanitizados, não publicáveis**, anexados ao GitHub Actions por sete dias.

- `diagnostico` e `grafo`: execuções reais locais (código atual), sem chaves ou custo de API de modelo.
- `firecrawl`: necessita `FIRECRAWL_API_KEY`, input da URL HTTPS e domínio exato em `vars.NIVON_AI_APPROVED_HOSTS`; faz uma única extração de Markdown. Nenhuma observação é publicada.
- `pageindex`: necessita `secrets.NIVON_IA_OPENAI_API_KEY`, `vars.NIVON_PAGEINDEX_MODELO`, `vars.NIVON_PAGEINDEX_CHAT_MODELO`, input de pergunta e um PDF **já versionado dentro de `docs/`**. O conector usa `PageIndexLocalClient` (índice local, LLM externo apenas se autorizado), evitando upload acidental à nuvem PageIndex.
- `hindsight`: necessita `secrets.NIVON_HINDSIGHT_API_KEY`, `vars.NIVON_HINDSIGHT_URL`, `vars.NIVON_HINDSIGHT_BANK_ID` e hostname permitido. Faz exclusivamente `recall` em um banco existente; não cria nem retém memórias.
- `paperclip`: necessita `secrets.PAPERCLIP_API_KEY`, `vars.NIVON_PAPERCLIP_ORIGEM`, `vars.NIVON_PAPERCLIP_COMPANY_ID` e hostname permitido. Lê tarefas existentes, **não** cria agentes, tarefas, cobranças nem recursos.
- `magnitude`: o piloto Node separado continua preparado mas **não roda em runner genérico sem isolamento de egress**. A navegação visual exige ambiente de browser protegido e chave de modelo. Não constitui bloqueador da coleta estruturada nem do terminal.
- `graphify`: o AST existente executa de fato; importar exportações Graphify ainda requer análise semântica. Nenhuma classificação de grafo inferido vira dado canônico.
- `rtk`/`llmtrim`: substituto determinístico com limites e hash está disponível; invocar executáveis externos sem benchmark não foi liberado.
- `book-to-skill`: rascunhos são gerados de arquivos de texto locais autorizados; promoção a skill executável permanece sujeita à revisão.

### Como executar sem instalar programas no computador ou celular

No GitHub: **Actions → NIVON - Pilotos P0-P2 sob demanda → Run workflow → main → capacidade**. Para capacidades externas, marque **confirmar_custo_e_envio** depois de verificar custo, autorização e configuração dos secrets/variables na interface GitHub. O workflow cancela a execução externa se essa confirmação não estiver marcada. Nunca coloque tokens, nomes de pessoas ou dados privados nos inputs.

Requisitos de aceitação **individuais**: log do workflow concluído, artefato `resultado.json` com `execucao=PILOTO_EXTERNO_REAL` e hash/contagens, conferência do fornecedor/consumo, comprovação de que dados não foram automaticamente publicados, e revisão dos contratos antes de promover o serviço à operação. Uma execução verde prova somente aquela ação; não valida frescor de fonte, qualidade de extração ou disponibilidade contínua.

**Status em 26/10/2026:** código e runner versionados; **não afirmamos execução externa real sem workflow de fornecedor e credenciais comprovadas**. Integrações P0–P2 continuam independentes do marco M1.
