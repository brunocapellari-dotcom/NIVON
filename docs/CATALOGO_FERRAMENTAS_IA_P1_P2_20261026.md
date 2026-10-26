# NIVON — catálogo de capacidades de IA e engenharia (P1–P2)

**Decisão registrada em:** 26/10/2026.
**Escopo:** somente NIVON, único projeto ativo.
**Natureza:** incorporação ao planejamento técnico para avaliação/implementação e testes posteriores. **Não é instalação, ativação em produção, integração operacional comprovada nem autorização de custos.**
**Objetivo principal:** acelerar entrega de dados reais e confiáveis e melhorar continuidade do desenvolvimento. Não criar uma segunda plataforma de gestão, backend ou fila.
**Responsável pela execução técnica:** fluxo existente de desenvolvimento do NIVON (Claude/GitHub); este catálogo não designa novos agentes executores.

## Salvaguardas obrigatórias

1. **M1 não pode depender destas ferramentas.** Não alterar o deploy privado no Cloud Run, IAP, BigQuery, pipelines operacionais, `requirements` de produção, recursos GCP ou credenciais para adotar itens deste catálogo.
2. **Uma fonte de verdade por finalidade.** GitHub para código, PRs e trabalho de engenharia; BigQuery/RAW auditado e evidências versionadas para dados; documentação aprovada no próprio repositório. Índices, wikis e avaliações são projeções derivadas e reconstruíveis.
3. **Reaproveitar antes de substituir.** Inspecionar implementações presentes antes de instalar bibliotecas, duplicar parsers ou introduzir serviços e bancos adicionais.
4. **Executar em ambiente isolado, fora do equipamento do proprietário**, sempre que for necessário um piloto. Não criar novos serviços permanentes por padrão. Sem uso de APIs externas/LLMs pagas sem autorização e controle de custo.
5. **Proveniência e qualidade.** Todo texto, tabela, trecho indexado e resultado de avaliação deve guardar fonte original, data relevante, hash quando aplicável, localizador (página/arquivo/linha), classificação e estado de validação. Sem promover extração ou síntese a dado observado automaticamente.
6. **Segurança e licença.** Avaliar versão, licença, cadeia de dependências, tratamento de arquivos enviados, possíveis conexões externas, telemetria e retenção. Proibido publicar documentos privados, credenciais e traces contendo PII.
7. **Critério de conclusão.** `CATALOGADO` ≠ `ADAPTADOR IMPLEMENTADO` ≠ `TESTADO` ≠ `HOMOLOGADO` ≠ `OPERACIONAL`. Registrar evidência de cada passagem. Mudanças de runtime exigem revisão, testes E2E e decisão de adoção baseada em ganho observado.

## Matriz de prioridades

| ID | Projeto externo (fonte) | Prioridade | Aplicação restrita ao NIVON | Estado em 26/10/2026 |
|---|---|---|---|---|
| IA-P1-01 | [Docling](https://github.com/docling-project/docling) | P1 | Extração estruturada de PDF, tabelas, DOCX e outros relatórios de fontes agro/logísticas | CATALOGADO — avaliação pendente |
| IA-P1-02 | [OpenWiki](https://github.com/langchain-ai/openwiki) | P1 | Documentação derivada de código/testes para orientar o Claude, com evidência por arquivo | CATALOGADO — avaliação pendente |
| IA-P1-03 | [Future AGI](https://github.com/future-agi/future-agi) | P1 | Métricas e avaliações do IVO: groundedness, citações, uso de ferramentas e falhas | CATALOGADO — avaliação pendente |
| IA-P1-04 | [Skills for Real Engineers](https://github.com/mattpocock/skills) | P1 | Melhoria pontual de TDD, revisão de código e clareza das entregas | CATALOGADO — curadoria pendente |
| IA-P2-01 | [Caveman](https://github.com/JuliusBrussee/caveman) | P2 | Benchmark de redução do consumo de tokens em tarefas de desenvolvimento | CATALOGADO — benchmark pendente |
| IA-P2-02 | [Qdrant](https://github.com/qdrant/qdrant) | P2 | Índice vetorial de documentos apenas se a busca disponível não atender as necessidades | CATALOGADO — análise de necessidade pendente |

As prioridades são **de avaliação**, não obrigação de instalar. Um item P2 pode ser descartado tecnicamente quando não superar a solução existente.

### IA-P1-01 — Docling (coleta documental)

- **Problema:** PDFs de fontes públicas e privadas autorizadas com tabelas quebradas, múltiplas colunas, cabeçalhos e rodapés.
- **Ponto de extensão:** estágio de parsing/extração documental dos coletores já existentes, com adaptador opcional por tipo de documento. Preservar original e parser atual como fallback.
- **Escopo piloto:** relatórios CONAB, documentos de IMEA/CEPEA obtidos de forma autorizada, balanços e documentos portuários públicos. Testar PDF nativo, tabela complexa e imagem/scan conforme disponibilidade de amostras.
- **Saída contratual:** arquivo de origem, SHA-256, URL/provenance, página, tabela/coluna/célula quando possível, unidade, data, valor, texto original e status `EXTRAIDO_NAO_VALIDADO`.
- **Reuso:** `pdfplumber` já é dependência opcional em `pyproject.toml`; comparar Docling com esse parser antes de substituir qualquer coisa. OCR apenas quando necessário.
- **Teste de aceitação:** nenhuma troca silenciosa de unidades, separadores decimais, totais ou campos ausentes; medir completude, acurácia por campo, tempo, memória e custo. Dados só passam a publicáveis após regras de normalização/auditoria já existentes.
- **Decisão:** ADOTAR apenas adaptador incremental se demonstrar ganho relevante; não instalar `docling-serve` nem expor serviço novo por padrão.

### IA-P1-02 — OpenWiki (documentação de engenharia)

- **Problema:** perda de contexto, mudanças sucessivas sem visão confiável das dependências e do estágio real do trabalho.
- **Ponto de extensão:** geração/atualização opcional de wiki Markdown versionada via PR, derivada do código, testes e arquivos existentes.
- **Reuso:** `docs/integracoes_ia_nivon.md` já descreve grafo AST, artefatos de GitHub Actions, skills e aceite de entregas. Evitar novo catálogo concorrente.
- **Teste de aceitação:** página deve apontar arquivos/commits que fundamentam afirmações; diferenciar código presente, execução comprovada e pendência; não inventar estados operacionais. Detectar atualização incremental após diff controlado e medir custo de manutenção.
- **Limites:** não editar automaticamente documentação canônica sem revisão, não sobrepor instruções críticas em `AGENTS.md`/`CLAUDE.md`, não habilitar auto-merge, não criar serviço de wiki em produção.
- **Decisão:** manter wiki como material derivado navegável, nunca como autoridade sobre dados/implantação.

### IA-P1-03 — Future AGI (avaliação do IVO)

- **Problema:** o IVO pode responder sem evidência, confundir observação/projeção, citar números errados ou falhar na execução de ferramentas.
- **Ponto de extensão:** suíte offline de cenários e avaliação de traces **sanitizados**, usando componentes isolados (SDK/avaliadores), não gateway de tráfego obrigatório.
- **Indicadores mínimos:** precisão e cobertura de fontes, taxa de respostas sem sustentação, confusão entre tipos de dado, completude, correção de uso de ferramenta, recusas adequadas, latência e custo por caso.
- **Cenários críticos:** fretes com condições comerciais distintas; preços físicos versus CBOT; line-up programado versus realizado; dados antigos versus atuais; ausência de fonte; AIS inferido versus confirmado.
- **Teste de aceitação:** suíte reprodutível com entradas e saídas esperadas aprovadas, score por caso e revisão humana em divergências; falhas graves bloqueiam promoção. Não usar score autodeclarado por um LLM como prova de verdade.
- **Limites:** o pacote de self-hosting inclui componentes adicionais e telemetria; não instalar o stack integral nem enviar prompts/dados sensíveis sem decisão de segurança, custo e necessidade. Priorizar testes determinísticos/SDK leve quando tecnicamente suficiente.

### IA-P1-04 — Skills for Real Engineers (qualidade de código)

- **Problema:** retrabalho e perda de foco durante desenvolvimento, excessos de perguntas, execução sem testes/E2E e alterações de estrutura não justificadas.
- **Ponto de extensão:** curadoria das práticas de `code-review`, `tdd` e melhoria arquitetural, adaptadas às `.agents/skills/` já versionadas no NIVON.
- **Teste de aceitação:** selecionar só conteúdo sem redundância; inspecionar diff/licença; usar em alteração real; validar que não cria filas, prompts repetitivos, perguntas desnecessárias ou execução sem autonomia previamente autorizada.
- **Limites:** não instalar coleções inteiras ou comandos globais no computador do usuário; evitar sobrescrever as políticas técnicas do projeto.

### IA-P2-01 — Caveman (eficiência em tokens)

- **Problema:** consumo elevado de contexto durante sessões de engenharia.
- **Reuso:** existe diagnóstico de RTK/llmtrim e limitação determinística de contexto em `src/nivon/integracoes_ia`.
- **Teste de aceitação:** executar lote pareado de tarefas idênticas e medir tokens de entrada/saída, custo total da execução, tempo, correções, testes e qualidade de resposta. Não extrapolar métricas promocionais para o NIVON.
- **Limites:** respostas curtas não podem eliminar evidências, erros, resultados de testes e estado; se reduzir qualidade ou custo não cair, **REJEITAR**. Não ativar auto-start ou proxy automaticamente.

### IA-P2-02 — Qdrant (índice semântico)

- **Problema condicional:** consultas com baixa recuperação de trechos relevantes em documentos já autorizados e muito volumosos.
- **Regra prévia:** medir pesquisa existente; comparar com busca textual/híbrida e opções que usem a infraestrutura atual. Implementar só se houver lacuna comprovada.
- **Arquitetura:** índice derivado e reconstruível de documentos, com `document_id`, `chunk_id`, fonte, datas, nível de acesso, hash, versão do embedding e referência à passagem original; respeitar filtros de permissão.
- **Teste de aceitação:** precisão/recall por pergunta de referência, latência, custo, isolamento de dados, remoção/reindexação e consistência com a fonte canônica.
- **Limites:** Qdrant nunca será fonte primária de números de mercado; não criar cluster/serviço permanente por padrão. Caso BigQuery e a busca existente bastem, **RESERVAR**.

## Exclusões conscientes (fora do P1–P2)

- [PocketBase](https://github.com/pocketbase/pocketbase): não adotar; backend e autenticação paralelos, potencial fragmentação da infraestrutura.
- [Escale Biz](https://escale.biz/): não contratar; gestão de agentes paralela ao fluxo Claude + GitHub existente.
- [AI Marketing Skills](https://github.com/ericosiu/ai-marketing-skills): P3, fora desta aprovação; marketing não bloqueia o terminal privado e não deve consumir recursos da frente técnica.
- Central de Skills mostrada no último print: sem repositório inequívoco; **não instalar** até identificar fonte oficial, escopo e licenciamento.

## Sequenciamento sem afetar o M1

1. **Agora:** catálogo e rastreabilidade aprovados em documentação; nenhuma instalação nem alteração de produção.
2. **Após disponibilidade do M1 ou em trilha offline que não o bloqueie:** comparar extração Docling versus parser atual; selecionar práticas de engenharia; piloto OpenWiki com página derivada.
3. **Após fluxo IVO com evidências reais:** implantar suíte de avaliação isolada Future AGI ou testes equivalentes sem duplicar serviços.
4. **P2 sob evidência:** benchmark Caveman; Qdrant apenas se houver deficiência mensurada de recuperação documental.

## Evidência exigida em cada ativação futura

Para cada ID registrar PR/commit, versão upstream e licença, proprietário do módulo no código, dados de teste autorizados, medição antes/depois, custo de execução, revisão de segurança, CI/E2E, decisão `ADOPT`/`RESERVE`/`REJECT`, flag de ativação e plano de reversão. Sem esses elementos, permanecerá `CATALOGADO`.

**Nenhum item deste catálogo deve ser declarado funcional, instalado, integrado ao Google Cloud ou homologado apenas pela inclusão neste documento.**
