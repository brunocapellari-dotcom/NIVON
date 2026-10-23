# NIVON — Isolamento e pré-validação transacional dos PDFs marítimos

**Data:** 23/10/2026. **Status:** código de pesquisa/teste, sem execução de fontes reais, sem merge ou deploy. Continuação empilhada sobre PR #132 na PR #150.

## Objetivo da entrega em bloco

A frente de PDF marítimo já possui extratores para Paranaguá/Itaqui, ponte normalizada, histórico SQLite, comparações de versões, dossiê candidato Nº Prog–DUV e um comando único com manifest local. Este pacote remove o maior risco técnico ainda evitável por código: executar `pdfplumber` diretamente no processo que mantém o SQLite.

### Caminho efetivo da CLI

1. Operador declara fonte e direitos no manifest e fornece **PDF original local**, já adquirido por meio lícito e com SHA-256 próprio.
2. `scripts/maritime_pdf_batch.py` valida diretório relativo, URL oficial, status manual de direitos, bytes e SHA antes da extração.
3. `extract_pdf_tables_isolated` abre `python -m nivon.maritime.pdf_extraction_worker` em **outro processo**, transmitindo bytes via STDIN. O worker aplica `RLIMIT_CPU` de 12 s (limite absoluto 14 s), memória virtual máxima de **1 GiB**, ausência de core dumps, quota de 60 páginas, 300 tabelas, 12.000 linhas, 240.000 células, entrada máxima 20 MB e JSON de saída de até 6 MB.
4. O processo pai limita a chamada a **25 segundos**, exige saída JSON v1 dentro da quota, tipos corretos e SHA dos bytes de entrada; erros/timeout/cota excedida interrompem o lote. Não interpreta saída livre ou stderr como dados.
5. A dupla validação original do coletor de autoridade e a ponte PDF reutilizam **as mesmas tabelas já extraídas**. O pai normaliza programações declaradas e gera histórico, sem nova abertura do arquivo com `pdfplumber`.
6. `run_offline_pdf_batch` faz **pré-validação integral das diferenças históricas** antes de chamar `save_batch`. Uma falha de leitura do histórico ou comparação não resulta em nova edição gravada; a operação de gravação posterior é transacional e rejeita versões conflitantes.
7. O relatório JSON diferencia programa publicado de operação física. `publication_allowed=false`, volume realizado/atracação/escala confirmada permanecem `null`; nenhum Nº Prog é convertido automaticamente em DUV.

Esta é **isolação de extração por subprocesso**. O processo filho ainda compartilha o usuário do SO e pode ter acesso à rede se executado fora de contêiner; o hash de resposta verifica consistência, não é assinatura criptográfica de uma autoridade. Assim, a CLI direta é apenas para arquivos de confiança e não é aprovada para arquivos externos hostis em produção.

## Executor em contêiner sem rede (opcional)

Arquivos: `docker/Dockerfile.maritime-pdf-offline` e `scripts/run_maritime_pdf_container.sh`. **Construção e execução são manuais; não foram realizadas nem homologadas por esta PR**. O build precisa obter Python/pdfplumber de registries e PyPI; a execução do contêiner usa `--pull never --network none` e não faz downloads. A imagem base usa tag, devendo ser pinada a digest aprovado para produção.

```bash
# Na raiz do repositório, somente em ambiente autorizado com Docker instalado:
docker build -f docker/Dockerfile.maritime-pdf-offline \
  -t nivon-maritime-pdf-offline:local .

# Dry-run: diretórios de entrada/saída existentes e separados.
bash scripts/run_maritime_pdf_container.sh \
  ./dados_autorizados ./auditorias_lote \
  manifest.json relatorio_01.json 2026-10-23T12:00:00-04:00

# Escrita derivada local: somente se direitos de processamento/guarda
# tiverem sido comprovados externamente e documentados no manifest:
bash scripts/run_maritime_pdf_container.sh \
  ./dados_autorizados ./auditorias_lote \
  manifest.json relatorio_02.json 2026-10-23T12:00:00-04:00 --commit
```

O wrapper exige imagem já construída, executa contêiner sem rede/privilegios, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 40`, 1536 MiB e 1,5 CPU, usuário não root, entrada `/inputs` montada read-only, saída `/output` em diretório separado, `/tmp` temporário `noexec`. Não conecta a Google Cloud, Oracle, GitHub, AIS nem ativa coletores.

**Limites residuais:** a imagem e o wrapper precisam de avaliação de segurança de container (digest, CVEs, seccomp/AppArmor, conteúdo do host, permissões, logs, backup e tempo máximo do contêiner como um todo). O fluxo não estabelece licença; os booleans `ATTESTED`, `--ack-rights` são alegações humanas. Antes de qualquer material real, o parecer de direitos, revisão das fontes e plano de tratamento de incidentes continuam obrigatórios.

## Recuperação, integridade e diferenças

- Em um lote com múltiplos documentos, o processamento e o relatório de diferenças são validados **antes** de inserir qualquer novo snapshot na base SQLite; caso um PDF falhe na extração, o banco fica sem novas edições.
- Confirmações de programação não são confirmações físicas. `Nº Prog` é referência documental de programação; linhas de produtos não somam navios; o DUV só é candidato com vínculo documental independente.
- Report JSON e transação SQLite **não compõem uma transação distribuída**. Se o relatório em arquivo falhar depois de uma gravação válida, verificar o SQLite e reexecutar o lote idempotente com novo nome de relatório; o operador não deve fazer sobrescrita silenciosa.
- Os documentos originais e licenças não foram salvos no GitHub. A validação de integridade SHA local não autentica o publicador nem substitui assinatura ou prova de publicação.

## Evidências de teste e status

Testes novos cobrem: protocolo entre pai e filho, SHA/schema/resposta inválida, timeout, rejeição de PDF corrompido sem criar banco, execução de PDF binário verdadeiro sintético pelo subprocesso, ausência de nova extração `pdfplumber` no pai, falha de consulta/comparação antes do commit, equivalência entre relatório de dry-run e pós-commit, sintaxe bash e controles estáticos do wrapper Docker.

O código do contêiner foi entregue como **artefato não executado**, sujeito a revisão por quem opera Docker. Suíte Python e PDF sintético real são verificados na CI; os resultados exatos devem ser lidos na ação do SHA final.

**Status de homologação:** `CODE_TESTED_SYNTHETIC_ONLY` / `ORIGINAL_SOURCES_UNHOMOLOGATED` / `REAL_RIGHTS_UNVERIFIED` / `RELEASE_BLOCKED`.

## Próximas prioridades

1. Obter legalmente três edições originais por fonte/série de Paranaguá e Itaqui, com prova de publicação, coleta, SHA, direitos de processamento/guarda, e inspeção visual por página.
2. Em ambiente local aprovado, construir e inspecionar a imagem, aplicar política de segurança de contêiner, rodar o lote real autorizado e validar auditoria de layout/linha. Não acionar serviços pagos ou envio automático.
3. Resolver e documentar identificadores N. Prog/DUV somente por evidência explícita de autoridade; sem correspondência oficial, não unir as bases.
4. Após homologação, executar aceitação operacional em modo shadow, reconciliação temporal e avaliação editorial independente; sem isso, não habilitar relatório publicado, merge em main ou implantação.
