# NIVON — Extração PDF em bytes reais sintéticos (21/10/2026)

## Escopo e estado verificável

PR #67 (sobre PR #54). O pipeline `PDF -> pdfplumber -> PdfTable -> parse_itaqui_tables/parse_paranagua_tables -> processar_documento_porto -> bridge_official_pdf_document -> LineupVintage` recebeu validação **com arquivos PDF efetivamente gerados em memória**, e não somente objetos `PdfTable` simulados.

**ATENÇÃO:** PDFs gerados pelo teste são documentos **sintéticos**, não provenientes das autoridades. A passagem do teste não homologa layouts, licenças, dados, DUVs ou séries oficiais. Não foi feita coleta de PDF de terceiros nesta PR.

### Achado público relevante para Paranaguá

- A autoridade Portos do Paraná publica páginas de line-up e resumos de programação:
  - Página índice: https://www.portosdoparana.pr.gov.br/Operacional/Pagina/Resumo-da-Programacao
  - Página de edição: https://www.portosdoparana.pr.gov.br/Arquivo/LINE-CORREDOR-OESTE-16102026
  - Documento histórico identificado em pesquisa web: https://www.portosdoparana.pr.gov.br/sites/portos/arquivos_restritos/files/documento/2026-03/LINEUP16032026.pdf
- No conteúdo textual indexado do PDF histórico, as tabelas mostram **Nº PROG** e, em determinadas seções, data de `CHEGADA` e horário separado. Também aparecem situações como NAVIOS ATRACADOS, NAVIOS PROGRAMADOS, LINE UP e navios anunciados/SEM PROG.
- O texto indexado não comprova que exista coluna DUV; **Nº PROG não deve ser promovido a DUV/identidade jurídica de uma escala marítima**.
- Na tentativa de obter as imagens/páginas do PDF na ferramenta de inspeção, o servidor respondeu 404. Assim, **o documento não foi considerado amostra original baixada, inspecionada visualmente ou homologada**. O mesmo vale para o link PDF da edição outubro/2026 que não respondeu à abertura; conteúdo do cache web não é prova suficiente de integridade dos bytes.
- Metadados da página oficial de edição podem conter datas incongruentes com o título do arquivo. Data de publicação não deve ser extraída cegamente de carimbo geral do CMS, título, endereço, metadado de arquivo ou data de coleta. Exigir evidência de publicação verificável.

### Validação técnica nova

- Teste `tests/test_maritime_pdfplumber_e2e.py` monta PDFs tabulares sintéticos válidos com `reportlab`, sem rede, reproduzindo variantes essenciais: cabeçalhos, DUV explícita, Nº Prog distinto e chegada separada em DATA + HORA.
- A biblioteca `pdfplumber` **realmente extrai células dos bytes PDF**, sem mocks do extrator. O pipeline e a ponte de escala são exercitados com checks de horário, porto, origem, hash e estados de programação.
- Casos negativos: data sem hora, falta de DUV, status ATRACADO, SHA adulterado, direitos de coleta ausentes e data de publicação não demonstrada.
- Job CI `validar-pdf-maritimo-offline` com dependências de teste fixadas: `pdfplumber==0.11.9` e `reportlab==4.4.9`. Nenhum downloader de documentos, credencial, deploy ou coletor foi habilitado.
- Não houve custo de hospedagem, AIS, API ou serviço pago introduzido pelo código. Execuções CI consomem minutos do GitHub Actions sujeitos à franquia do repositório.

### Evidências de CI no SHA b2831bb3549a1c713894df8b4f21e64228cb8901

- [Python leve — run 39653953441](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39653953441): 1.149 testes, **14 ignorados** (5 pré-existentes + 9 testados separadamente no job PDF), nenhuma falha.
- Mesmo run, job `validar-pdf-maritimo-offline`: **9/9 testes executados e aprovados com PDF real sintético**, conferidos nos logs de execução.
- [Build cockpit marítimo — run 39653953471](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39653953471): SUCESSO.

## Pendências P0

1. **Identificador de programação sem DUV:** projetar registro separado de `programa_portuario_oficial`, distinto de escala confirmada por DUV. Utilizar `Nº Prog` apenas com escopo autoridade + porto + série + edição/competência; não unir visitas por navio ou IMO. Manter classificação de programação e evitar dupla contagem de linhas de carga.
2. **Amostras reais:** obter direitos e três edições oficiais por fonte/série, verificar bytes, hash, fuso, horário de publicação, colunas e reconciliação com layout reais. Sem documentação, não considerar fonte homologada.
3. **Produção:** validar garantias e limites de `pdfplumber`, páginas/consumo de memória, identificação de layout e segurança de arquivo. A biblioteca e os parseres não devem rodar automaticamente em arquivos desconhecidos sem controle de recursos.
4. **Consolidação:** todos os PRs em cadeia estão em draft e sem merge/deploy. Pipeline permanece `CODE_TESTED_SYNTHETIC_ONLY / REAL_DATA_GATED / RELEASE_BLOCKED`.

## Critério editorial

Line-up expressa expectativa/programação. Não concluir que atracou, concluiu carga, saiu do porto, realizou tonelagem ou gerou frete a partir de programação, desaparecimento de arquivo ou inferência de ETA. Ausência de documentos não equivale a zero embarcações.
