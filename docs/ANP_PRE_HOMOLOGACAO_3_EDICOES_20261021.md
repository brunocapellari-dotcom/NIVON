# NIVON — Protocolo de pré-homologação de 3 edições ANP/LPC (21/10/2026)

## Objetivo e situação verificável

O NIVON **não possui três XLSX reais homologados** nesta data. A página oficial do Levantamento de Preços da ANP (atualizada em 20/10/2026 13h05) anuncia, entre outras, as semanas:
- 27/09/2026 a 03/10/2026;
- 04/10/2026 a 10/10/2026;
- 11/10/2026 a 17/10/2026.

Fonte primária: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas

**O índice anuncia planilhas de preços médios; não comprova, por si só, download concluído, layout ou preços lidos.** A indicação de atualização da página não é a hora inicial de disponibilização de cada XLSX; notas entre parênteses referentes a arquivos por posto não devem ser atribuídas às tabelas de médias. A tentativa direta de buscar os arquivos a partir do ambiente de trabalho não confirmou acesso à mídia binária. Não se fabricaram SHAs reais, preços ou datas de publicação.

## Termos e finalidade do NIVON

O NIVON opera **sem fins comerciais**. Os termos públicos do portal ANP, consultados em 21/10/2026, autorizam reprodução total ou parcial **sem fins lucrativos**, com **citação clara e visível** da fonte, preferencialmente com link. Também proíbem comercialização de serviços utilizando conteúdo do portal, além de restrições técnicas e de direitos de terceiros.

Fonte primária: https://www.gov.br/anp/pt-br/acesso-a-informacao/termos-de-uso-privacidade-e-seguranca-1/termos-uso-portal-anp

Consequência: **não exigir uma autorização para uso comercial se o uso continua genuinamente não comercial**, mas conservar comprovação de atribuição, termos aplicáveis ao conjunto de dados, finalidade declarada, direitos de terceiros e prova de que o dado deriva da fonte oficial. Se o uso mudar para comercial, revisar todos os gates antes de ativar. O campo genérico `direitos_comerciais` do pipeline anterior é um *indicador conservador de ausência de homologação* e não significa que o NIVON tenha fins comerciais.

## Processo operacional offline

1. Obter legalmente o HTML oficial do índice e os **três XLSX das médias municipais** indicados, sem contornar proteções técnicas e sem obter fichas individuais de postos.
2. Em área local isolada, registrar origem, URL *efetivamente encontrada no índice*, SHA-256 do HTML, SHA-256 de cada XLSX, data/hora de captura com timezone, data/hora de publicação **apenas quando sustentada por evidência independente** e SHA da prova de publicação. Data estimada ou deduzida da semana não substitui prova.
3. Armazenar os quatro arquivos em uma pasta local protegida; construir `manifesto.json` conforme contrato a seguir. Nunca incluir credenciais, identificadores de postos, preços brutos ou XLSX reais no GitHub.
4. Executar `PYTHONPATH=src python scripts/auditar_tres_resumos_lpc.py --manifesto caminho/manifesto.json --saida caminho/relatorio.json` com Python 3.11 e o extra `openpyxl==3.1.5` já disponível. Não há download automático.
5. O relatório só registra metadados, contagem de municípios/produtos, período, integridade e lacunas; **não imprime preços**, não grava no store canônico e não marca `publicavel=true`.
6. Especialista independente compara os valores de municípios e produtos amostrados com os próprios XLSX originais, confirma layout e horários reais, verifica os direitos/atribuição e assina um parecer. Se qualquer evidência faltar, `NAO_HOMOLOGADO`.
7. Somente após parecer e implantação da autoridade de homologação, abrir mudança separada e auditada para permitir ingestão `REAL_AUTORIZADO`, com histórico point-in-time, políticas de retenção, segregação de uso e publicação sob licença aplicável.

## Contrato do manifesto

O arquivo JSON abaixo é **um modelo, não um manifesto validado**. Todos os campos entre `<...>` devem ser substituídos por evidências coletadas. As URLs não devem ser construídas artificialmente: usar o caminho exato identificado no índice HTML.

```json
{
  "indice_arquivo": "indice.html",
  "indice_sha256_esperado": "<sha256_verdadeiro_do_html>",
  "capturado_indice_em": "<data_hora_iso_8601_com_timezone>",
  "ano": 2026,
  "as_of": "<instante_do_corte_iso_8601_com_timezone>",
  "edicoes": [
    {
      "arquivo": "semana1.xlsx",
      "url": "<url_real_da_planilha_27-09_a_03-10>",
      "sha256": "<sha256_da_planilha>",
      "publicado_em": "<instante_real_sustentado_por_prova>",
      "coletado_em": "<instante_real_com_timezone>",
      "prova_publicacao_sha256": "<hash_da_prova_independente>"
    },
    {
      "arquivo": "semana2.xlsx",
      "url": "<url_real_da_planilha_04-10_a_10-10>",
      "sha256": "<sha256_da_planilha>",
      "publicado_em": "<instante_real_sustentado_por_prova>",
      "coletado_em": "<instante_real_com_timezone>",
      "prova_publicacao_sha256": "<hash_da_prova_independente>"
    },
    {
      "arquivo": "semana3.xlsx",
      "url": "<url_real_da_planilha_11-10_a_17-10>",
      "sha256": "<sha256_da_planilha>",
      "publicado_em": "<instante_real_sustentado_por_prova>",
      "coletado_em": "<instante_real_com_timezone>",
      "prova_publicacao_sha256": "<hash_da_prova_independente>"
    }
  ]
}
```

A CLI aceita somente arquivos relativos à pasta do manifesto (rejeita symlinks e paths externos), limita tamanhos, verifica hashes, intervalos, datas e correspondência com o índice e emite JSON agregado. **Saída `PRONTO_PARA_REVISAO_INDEPENDENTE_NAO_HOMOLOGADO` nunca é autorização para publicar ou sincronizar dados reais.**

## Cobertura e governança de indicador

- ANP é fonte primária da pesquisa de preços de revenda. O campo de diesel é uma **média amostral municipal de revenda** para combustível automotivo (diesel B), com contagem de postos e competência semanal oficial.
- **Não** extrapolar os preços ANP para diesel A, refinaria, PPI, preço de compra por transportadora, média municipal de fretes, valor de contrato, frete efetivo ou volumes de caminhões.
- A série oficial semanal LPC é distinta da série CSV mensal com semanas inferidas e de dados brutos por posto. Não reconciliar produtos, calendários ou locais sem metodologia.
- Se algum município não constar da amostra, apontar **sem observação**, jamais zero. Não imputar lacunas.
- Manter `competence_date`, `publication_date`, `collection_date`, hashes, prova, `as_of`, status de homologação e revisão de edição. Atribuição mínima: **Fonte: ANP — Levantamento de Preços de Combustíveis**, com link ao índice e, quando autorizado, à tabela correspondente.

## Evidência de testes

`src/nivon/anp_lpc_homologacao.py`, `scripts/auditar_tres_resumos_lpc.py` e os testes específicos foram incluídos na PR #42. As fixtures usam bytes XLSX fictícios; verificam encadeamento de três semanas, falsos reaproveitamentos, período alterado, ausência de municípios, vigência temporal e proteção contra caminho externo. A CI da PR #42 valida o leitor com `openpyxl` pinado. **Esses testes não afirmam que os arquivos reais de outubro foram obtidos.**

## Próximo bloqueio real

A homologação dos três arquivos reais exige acesso autorizado aos bytes e suas edições/metadados verdadeiros, além da confirmação independente da cronologia e das condições de utilização. Uma vez fornecida essa evidência, o verificador agora já está implementado para analisar os insumos locais sem download ou deploy.


## Reforço P0 — controle de identidade das autorizações (21/10/2026)

A rota `anp_semanal_store.gravar_edicao_semanal` foi endurecida para eliminar a situação em que um chamador classificava dado como `REAL_AUTORIZADO` apenas por enviar `direitos_confirmados=true` e SHA-256 de uma suposta prova. Hash é apenas **referência de conteúdo**, não autenticação de aprovação.

### Contrato implementado

- `src/nivon/anp_atestacoes.py` valida duas aprovações independentes com HMAC-SHA256, domínio separado `DIREITOS_USO` e `HOMOLOGACAO_LAYOUT`, emissores diferentes, **segredos diferentes com 32 bytes ou mais**, identificadores únicos, janela temporal limitada e lista confiável de revogações.
- Cada assinatura inclui, sem campos omitidos, SHA do XLSX, SHA derivado do resumo validado, URL original ANP, data de publicação, prova de publicação, prova de direitos, SHA do índice, operação permitida `ARMAZENAMENTO_ANALITICO_NAO_COMERCIAL` e `publicavel=false`. Alterar qualquer campo invalida a assinatura.
- O armazenamento requer, além das assinaturas, a habilitação operacional externa `habilitacao_real=true`, o índice validado e `direitos_confirmados=true`. A configuração é **desativada por padrão**; a rota de ingestão `anp_lpc_pipeline.py` continua a recusar classe real independentemente das flags.
- Tabela `anp_semanal_atestacoes` guarda emissor, domínio, identificador, hash da assinatura e validade por edição, na mesma transação que a observação. `aprovacao_id` é único para evitar reuso em outra edição; falta de qualquer um dos dois domínios bloqueia consulta. Registros históricos anteriores, mesmo classificados erroneamente como reais, permanecem **invisíveis** sem atestações.
- Chaves ficam no **registro confiável do controlador**, nunca são baixadas do arquivo ANP ou do payload do coletor. Não há chave de produção no repositório. Fixtures de teste usam chaves publicamente falsas e não demonstram legitimidade legal ou posse de chaves confiáveis.
- A expiração e lista de revogação são conferidas **no momento da ingestão**. Não há sistema real de KMS, emissão/assinatura, rotação, revogação após ingestão, consulta de CRL, prova de autenticidade da origem, relógio confiável distribuído nem política de atualização pós-aprovação. Esses itens permanecem pendências reais e **impedem alegar homologação operacional**.

### Critérios antes de habilitar dados reais

1. Obter e auditar bytes e os termos de uso da ANP e trilha das três edições verdadeiras. Garantir atribuição ANP e finalidade não comercial.
2. Implantar separação de identidade e custódia das duas autoridades externas (credenciais isoladas, revogação e rotação monitoradas), relógio do operador e trilha de aprovação imutável.
3. Vincular uma decisão de direitos e uma decisão de layout independentes por edição, sob política de finalidade não comercial e preservação de dados.
4. Exigir uma alteração revisada do pipeline atual para aceitar a classe real somente depois dos gates; manter revisão independente, testes com dados autorizados e trilha PIT.
5. Implementar invalidação pós-ingestão em caso de revogação de qualquer autoridade e bloqueio de consultas de edições revogadas — a verificação atual na ingestão **não** cobre revogações futuras.

Nenhuma destas alterações autoriza execução de coleta automática, publicação, dump da base, deploy, agendamento, compra ou mudança de finalidade.
