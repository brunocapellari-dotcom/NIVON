# NIVON / Inteligência Pecuária — plano de entregas SIDRA

**Última revisão: 22/10/2026 (local MT).** Escopo isolado na PR #22.
**Maturidade: código testado exclusivamente com respostas sintéticas.**
O sistema não possui captura oficial validada da Pesquisa Trimestral do Abate
de Animais e não está autorizado a publicar indicadores de produção ou previsão.

## Prioridades e critérios de aceite

| Ordem | Execução | Evidência de testes | Estado |
|---|---|---|---|
| P0.1 | Sondar HTTPS 1092/1093/1094 sem crawler | Plano sem rede, 6 respostas falsas, HTTP 500, JSON inválido | **Código implementado; HTTP oficial pendente** |
| P0.2 | Processar amostras em lote, variáveis e categorias explícitas | Captura -> normalizador -> auditoria -> historico por corte | **Implementado/testado em sintéticos** |
| P0.3 | Processar as três espécies numa operação | Lote de 3 cadeias, erros de dimensão, direitos, 25 entradas | **Implementado/testado em sintéticos** |
| P1.4 | Preservar histórico, hashes e revisões | SQLite 1 transação, rollback, reimportação, as-of | **Implementado/testado em sintéticos** |
| P1.5 | Consolidar relatório de prontidão | Cobertura BR/UF desconhecida, censuras, revisões, bloqueios | **Implementado/testado em sintéticos** |
| P1.6 | Interface local e governança | CLI subprocess, dry-run, persistência autorizada, path traversal | **Implementado/testado em sintéticos** |
| P0 real | Homologar metadata, direitos, cronologia e respostas IBGE | HTTP oficial, metadados verdadeiros, 3 fixtures autorizadas | **BLOQUEADO por ambiente de consulta** |

Os quatro itens de inferência que não podem ser tomados como verificados
pela ferramenta: autenticidade HTTPS histórica, publicação original,
categorias/unidades oficiais e autorização legal de armazenamento.

## Pipeline implementado

- \`src/nivon/pecuaria_sidra_sondagem.py\`: consultas HTTPS **somente se invocadas
  explicitamente com --rede**. Hosts fixos (apisidra.ibge.gov.br e
  servicodados.ibge.gov.br), sem redirect, proxy ou login, timeout máximo
  de 10 segundos e payloads limitados a 1/2 MB. Sem persistência.
- \`src/nivon/pecuaria_sidra_operacao.py\`: CLI offline que consome manifesto
  e referências a arquivos JSON locais. Prévia é padrão, recusa caminhos
  absolutos, symlinks, path traversal, dados grandes e permissões omitidas.
- \`src/nivon/pecuaria_sidra_lote.py\`: executa pré-validação de até 24
  capturas, normalização 1092/1093/1094, qualidade territorial somente com
  lista oficial explicitamente declarada, seleção de vintages ao corte, e
  relatório JSON sucinto sem linhas brutas.
- \`src/nivon/pecuaria_sidra_arquivo.py\`: função
  \`arquivar_lote_sidra_atomico\` verifica todos os pacotes, abre uma
  transação SQLite, identifica duplicatas e faz **rollback do lote inteiro**
  se alguma captura conflitar com a base. Bancos SQLite continuam locais,
  sob a política de direitos do operador, e **não** são imutáveis contra
  administrador.
- \`src/nivon/pecuaria_sidra_abate.py\`,
  \`src/nivon/pecuaria_sidra_vintages.py\`: normalização de observações,
  símbolos SIDRA (zero vs. censura), calendário 1997+, controle por
  espécie/UF/competência/indicador e prevenção de look-ahead.
- Registro de BOI, SUINO e FRANGO contém o pipeline **desligado**:
  \`scheduled_enabled=false\` e \`operational_enabled=false\`.

## Procedimento de execução

**1. Inspecionar URLs sem rede:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_sondagem --periodo 202602
\`\`\`

**2. Diagnóstico HTTPS somente em rede autorizada:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_sondagem --periodo 202602 --rede
\`\`\`

Se retornar \`FORMATO_PRELIMINAR_CONFIRMADO\`, verificar manualmente
corpo, categorias e unidade contra a documentação oficial. Esse estado
NÃO é homologação de fonte. \`ERRO_NAO_HOMOLOGADO\` não significa
automaticamente indisponibilidade da API para todos.

**3. Preparar manifesto 1.0 fora do repositório público:**

\`\`\`json
{
  "schema_version": "1.0",
  "capturas": [
    {
      "especie": "FRANGO",
      "tabela_sidra": "1094",
      "arquivo_valores": "1094-valores.json",
      "arquivo_metadados": "1094-metadados.json",
      "url_valores": "https://apisidra.ibge.gov.br/values/t/1094/n1/1/p/202602/v/allxp/h/y",
      "url_metadados": "https://servicodados.ibge.gov.br/api/v3/agregados/1094/metadados",
      "publicacao_declarada": "SUBSTITUIR_POR_PUBLICACAO_COM_FUSO",
      "coleta_declarada": "SUBSTITUIR_POR_COLETA_COM_FUSO",
      "dimensoes": {},
      "totais": {},
      "variaveis": {}
    }
  ]
}
\`\`\`

**Os campos em branco são obrigatórios:** devem vir de uma inspeção
real da tabela, não de IDs de testes (\`9999\`/\`8888\` são **fictícios**).
O manifesto acima é ilustrativo e **falhará fechado até ser preenchido**
e acompanhado dos dois JSONs reais autorizados.

**4. Executar prévia offline, sem gravar banco:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_operacao \
  --manifest /dados/sidra/manifesto.json \
  --base-dir /dados/sidra/brutos \
  --corte 2026-10-23T00:00:00-04:00 \
  --confirmar-direitos
\`\`\`

**5. Arquivar apenas após confirmar direitos e contrato dimensional:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_operacao \
  --manifest /dados/sidra/manifesto.json \
  --base-dir /dados/sidra/brutos \
  --corte 2026-10-23T00:00:00-04:00 \
  --confirmar-direitos --gravar \
  --banco /dados/sidra/capturas.sqlite
\`\`\`

O arquivo SQLite deve ficar fora do GitHub. O sinalizador
\`--confirmar-direitos\` é **declaração do operador**, não atestado
externo de licença. Reexecução idêntica reaproveita IDs e dados. Divergência
no mesmo instante de coleta é recusada e provoca rollback do lote.

**6. Executar suíte inteira:**

\`\`\`bash
PYTHONPATH=src python -m unittest discover -s tests -v
\`\`\`

Os testes de CLI constam em \`tests/test_pecuaria_sidra_operacao_cli.py\`;
os de pipeline/rollback/sondagem em
\`tests/test_pecuaria_sidra_lote_integrado.py\`. O CI completo é a
evidência canônica após cada HEAD.

## Políticas de dados e liberação

- CEPEA e SCOT permanecem fora deste escopo até autorização/licença de
  consulta, armazenamento e redistribuição; não supor acesso liberado.
- Uma coleta atual não é vintage autêntico de edição histórica.
- Não misturar rebanho anual com abate trimestral, abate federal SIF com
  produção total sob inspeção, nem Brasil com soma das UFs desconhecidas.
- A Pesquisa Trimestral do Abate possui revisões históricas. Documentar
  data de publicação e fonte de edição quando houver dado real.
- JSON arquivado/HTTP 200 não autoriza uso comercial nem publication.
  O pipeline nunca sinaliza \`publicacao_permitida=true\`.
- Sem execução agendada, integração WhatsApp, credenciais, serviços cloud,
  merge ou gasto ativados nesta PR.

### Referências públicas
- Pesquisa e tabelas IBGE: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/
- API Agregados v3: https://servicodados.ibge.gov.br/api/docs/agregados?versao=3
- Esquema/API conceitual independente: https://docs.ropensci.org/ibger/articles/api-concepts.html
