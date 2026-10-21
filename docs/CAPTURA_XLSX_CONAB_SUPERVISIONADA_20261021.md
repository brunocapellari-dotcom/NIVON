# NIVON — Captura pontual supervisionada de XLSX CONAB

**21/10/2026.** Módulo: `src/nivon/captura_xlsx_conab.py`.

## Escopo

O bloqueio atual é de **acesso aos bytes do arquivo oficial**, não de descoberta do endereço. Conferidos em 21/10/2026:

- [Página CONAB 12–18/10/2026](https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-12-10-a-18-10-26/acompanhamento-das-lavouras-05-10-a-11-10-26): publicada em 19/10/2026; link `Plantio e Colheita 10-10 a 16-10` retorna declaração MIME `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- [Página CONAB 05–11/10/2026](https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-05-10-a-11-10-26/acompanhamento-das-lavouras-05-10-a-11-10-26): publicada em 12/10/2026, link `Plantio e Colheita 03-10 a 09-10`, MIME XLSX.
- O download no ambiente atual via `urllib.request` falhou com `URLError [Errno -3] Temporary failure in name resolution`. Não foi possível calcular hash real ou validar XLSX de outubro.

## Implementação

A captura por HTTP está **bloqueada por padrão**: exige dois parâmetros explícitos: `autoriza_requisicao=True` e `direitos_coleta_conferidos=True`; o módulo **não verifica direitos pelo operador** nem afirma posse de licença individual. Sem ambos, aborta antes de solicitar URL.

Quando autorizado e houver acesso de rede, o módulo faz **uma única GET** HTTPS, com User-Agent identificado, domínio e caminho oficial estritamente validados, HTTPS com TLS padrão, **sem proxies de ambiente, sem redirects, sem cookies explícitos, sem retries**. Exige HTTP 200 e URL final idêntica, Content-Type XLSX, Content-Length coerente, no máximo 20 MB. Bytes são conferidos com o detector ZIP/XLSX existente e parser OOXML; a competência das observações deve corresponder ao intervalo informado no portal.

Só depois de todas as validações grava, em pasta local **nova e vazia, privada `0700`**, dois arquivos exclusivos em `0600`:

- `conab_progresso_raw.xlsx`: exatamente os bytes recebidos.
- `conab_captura_evidencia.json`: requisição original/final, HTTP status, ETag, Last-Modified, MIME, Content-Length, UTC de início/fim, hash SHA256 calculado, tamanho, competência, ID da edição, versão/hash do parser, número de observações e gates NO-GO.

Dados (e relatórios de evidência) **não devem ser commitados no GitHub**; armazenar em volume privado com backup, controle de acesso, retenção definida e proteção de segredos.

### Exemplo somente para operador com autorização e licenças verificadas

```sh
mkdir -m 700 /dados/privados/conab-captura
PYTHONPATH=src python -m nivon.captura_xlsx_conab \
  --manifesto config/conab_publicacoes_identificadas_20261021.json \
  --id-edicao CONAB_PROG_2026_10_18 \
  --destino /dados/privados/conab-captura \
  --autorizar-requisicao \
  --direitos-coleta-conferidos
```

**Não executar esse comando sem verificar os direitos individualmente e aprovar a aquisição.** O código não ativa agendadores, migração, backfill, escrita em SQLite, publicação nem envio externo.

## Limitações de proveniência e método

- Metadados `ETag` e `Last-Modified` fornecidos pelo servidor são preservados **sem tratá-los como certificado criptográfico** ou timestamp da CONAB. O SHA identifica o corpo recebido, mas não certifica autoria.
- A função de transporte pode ser substituída por um mock **apenas nos testes**. Sucesso de mock não significa HTTP real bem-sucedido.
- URLs oficiais preservam possível anomalia de slug publicada pela própria CONAB. A janela do PDF/planilha pode divergir da janela da página, por isso campos separados.
- A obtenção futura pode falhar se a CONAB mudar MIME/redirect/layout; esses casos exigem revisão, **não** relaxar silenciosamente segurança.
- Testes de CI usam **somente um XLSX de fixture pública de terceiro (agrobr)**, servido por transporte de teste, não RAW oficial. Não inferir comportamento da CONAB real.
- Mesmo em captura bem-sucedida, o manifesto continua com `migracao_permitida=false`, `publicacao_permitida=false`, `direitos_redistribuicao_verificados=false` e `origem_publicada_arquivada_independentemente=false`. Declaração do operador de direitos de coleta não cobre redistribuição.

## Próximo gate

Executar captura **apenas em ambiente com DNS/HTTPS e licença avaliada**, registrar SHA e metadados observados, testar XLSX real de 2026-10-16; confrontar diretamente com duas vintages independentes e revisão do parser antes de qualquer dado entrar no NIVON.

Status atual: ferramenta implementada e testável offline, **RAW real ainda ausente**.

## Revalidação posterior dos bytes e manifesto

A função `verificar_pacote_captura_local(edicao, pasta)` acrescenta um
segundo controle **somente leitura e sem rede**:

1. exige dois arquivos privados no diretório, com nomes e esquema esperados;
2. confere novamente SHA-256, tamanho, conteúdo RAW, janelas de captura
   UTC e URLs original/final do transporte registradas;
3. compara novamente o código do parser (SHA do módulo), o resultado
   de extração e a competência com o manifesto e o catálogo da edição;
4. rejeita XML/ZIP inválido, alteração do arquivo, adulteração de campos
   de liberação, chave JSON repetida, links simbólicos ou arquivos
   inesperados no mesmo diretório.

O estado resultante é
`PACOTE_LOCAL_REVERIFICADO_SEM_ATESTACAO_EXTERNA`, e **não**
`ORIGEM_OFICIAL_COMPROVADA`. A revalidação não prova que alguém não
tenha falsificado simultaneamente o XLSX e o JSON; para essa garantia
será necessário armazenamento imutável e atestação independente de
captura/assinatura, fora do escopo desta PR.

**Cuidado:** revalidação pode falhar após modificar o código do parser,
pois o SHA fixado no manifesto pertence à versão usada na captura;
manter versão original disponível ou realizar reprocessamento
versionado após auditoria.
