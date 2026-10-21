# NIVON — Proveniência das publicações CONAB (21/10/2026)

## Resultado da verificação pública

O portal CONAB oferece páginas semanais e anexos de plantio/colheita:

| Edição da página | Página publicada | Intervalo do anexo | Estado |
| --- | --- | --- | --- |
| 05–11/out/2026 | 12/out/2026, 19h00 (horário de portal, fuso não estabelecido no HTML) | 03–09/out/2026 | XLSX identificado, **RAW não obtido** |
| 12–18/out/2026 | 19/out/2026, 19h00 (horário de portal, fuso não estabelecido no HTML) | 10–16/out/2026 | XLSX identificado, **RAW não obtido** |

Fonte primária:
- https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-05-10-a-11-10-26/acompanhamento-das-lavouras-05-10-a-11-10-26
- https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-12-10-a-18-10-26/acompanhamento-das-lavouras-05-10-a-11-10-26

**Anomalia de nomenclatura na publicação mais recente:** o segundo URL efetivamente publicado contém o nome de arquivo de página da edição anterior (`acompanhamento-das-lavouras-05-10-a-11-10-26`) sob a pasta correta de `12-10-a-18-10-26`. O NIVON **preserva o URL observado** em vez de inventar um slug corrigido.

Anexos linkados e identificados:
- `.../acompanhamento-das-lavouras-05-10-a-11-10-26/plantio-e-colheita-03-10-a-09-10.xlsx`
- `.../acompanhamento-das-lavouras-12-10-a-18-10-26/plantio-e-colheita-10-10-a-16-10`

O sistema de leitura web retornou `Unsupported content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` ao seguir os anexos, atestando seu *tipo de mídia reportado*, não acesso ao corpo. A tentativa de baixar o documento diretamente pela ferramenta de download falhou; ambiente local não resolveu `www.gov.br` via DNS. **Nenhum arquivo oficial foi adquirido ou ingerido nesta entrega.**

## Código entregue

- `config/conab_publicacoes_identificadas_20261021.json` guarda o vínculo página → anexo e janelas, **SHA dos bytes em NULL** enquanto não houver captura verificável.
- `src/nivon/auditoria_publicacao_conab.py` valida URL oficial, identidade da edição, janelas de datas e unicidade de anexos; em modo sem bytes retorna `PAGINA_E_ANEXO_IDENTIFICADOS_RAW_NAO_AUTENTICADO`.
- Função `auditar_conab_local(..., bytes_anexo=...)` permite validar um arquivo local futuramente: cálculo SHA do **arquivo fornecido**, inspeção estrutural e reprocessamento com o parser XLSX existente, verificando se a semana extraída corresponde à semana do anexo. **Mesmo assim** o resultado será `BYTES_LOCAIS_VALIDOS_SEM_PROVA_CADEIA_DE_DOWNLOAD` até haver proveniência autenticada da coleta oficial. Nenhum registro agrícola fica exposto no relatório.
- Sem rede, escrita SQLite, alterações em catálogo/coletor ativo, scheduler ou publicação.

Rodar resumo das URLs identificadas:

```sh
PYTHONPATH=src python -m nivon.auditoria_publicacao_conab \
  --manifesto config/conab_publicacoes_identificadas_20261021.json --resumo
```

## Riscos remanescentes

1. Hash, tamanho, ETag, Last-Modified e bytes do XLSX oficial continuam **não obtidos**; só comparar URL e tipo MIME não equivale a ingestão.
2. A data de publicação provém do HTML. **Não atribuir fuso horário** a um timestamp do portal sem validação.
3. O parser é testado contra uma fixture *de terceiro* (agrobr), não contra estas edições reais de outubro. Nem o contrato nem o conteúdo do XLSX estão homologados por múltiplas vintages.
4. Licença individual e direitos por operação (coletar, armazenar, transformar, redistribuir) permanecem **pendentes**.
5. Nenhuma migração/republicação foi autorizada. `migracao_permitida=false` em todos os resultados.

Próximo gate: obter o RAW de maneira autorizada, gerar manifesto com URL final, datas, ETag/Last-Modified quando disponíveis, SHA-256 e trilha de aquisição; usar `auditar_conab_local` com o arquivo. Falha de download não pode ser contornada nem substituída por resultado artificial.
