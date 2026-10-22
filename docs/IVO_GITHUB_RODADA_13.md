# IVO — Rodada 13: aquisição oficial pontual e quarentena de evidências PAM

**Data de referência:** 21/10/2026. **Sem deploy, merge, custo, coleta real,
ativação de licenças, modificação dos datasets canônicos ou treinamento de
modelos reais.** Os testes usam transporte e arquivos inteiramente fictícios.

## Estado da pesquisa verificável

- O IBGE publica avisos oficiais de retificação no portal
  [Erramos](https://www.ibge.gov.br/erramos.html), inclusive soja de
  Tangará da Serra/MT, PAM 2021, e sorgo de Arandu/SP, PAM 2020/2022/2023.
- O **FTP público oficial** mantém um
  [diretório histórico de PAM anual](https://ftp.ibge.gov.br/Producao_Agricola/Producao_Agricola_Municipal_%5Banual%5D/)
  com subdiretórios observados no trecho antigo **1993 a 2016**, mas
  **não é evidência de um snapshot municipal PAM 2021 anterior à
  errata de 17/09/2026**. O próprio índice não comprova que tal arquivo
  exista nesse acervo.
- Existem também
  [boletins históricos LSPA mensais, inclusive 2021](https://ftp.ibge.gov.br/Producao_Agricola/Levantamento_Sistematico_da_Producao_Agricola_%5Bmensal%5D/Tabelas_xls/2021/),
  mas esses boletins apresentam **estimativas mensais de safra/ano
  referenciadas**, não snapshots históricos da PAM 1612 municipal.
  Portanto **NÃO podem substituir a versão original do SIDRA**.
- A URL oficial pontual planejada para **soja / quantidade produzida /
  Tangará da Serra-MT / ano civil 2021** é:
  `https://apisidra.ibge.gov.br/values/t/1612/n6/5107958/v/214/p/2021/c81/2713/h/y/f/a`.
  A tentativa de acesso por ferramenta de pesquisa externa não permitiu
  obter o payload neste ambiente. A rota conhecida **não prova coleta**
  nem disponibilidade efetiva no runtime.

## Implementação

### `src/nivon/ivo_pam_coletor_pontual.py`

Completa o *transporte*, antes ausente do normalizador original
`src/nivon/sidra_pam.py`. Implementa UMA solicitação GET para uma URL
previamente validada, sem crawling, busca em links, autenticação ou
varredura de municípios/anos. Tipos aceitos:

- `SIDRA_JSON`: URL **exata** do planejador já existente, tabela 1612,
  município/ano/categoria C81/variável explicitamente autorizados,
  com semântica conferida. Resposta máxima de 2 MB e validação pelo
  normalizador existente, incluindo marcadores e chaves duplicadas.
- `PDF_IBGE`: um PDF explícito em domínio autorizado da biblioteca ou
  portal, até 8 MB; cabeçalho e MIME conferidos, **não** autenticidade.
- `ARQUIVO_LEGADO`: um arquivo explícito dentro do diretório
  `ftp.ibge.gov.br/Producao_Agricola/Producao_Agricola_Municipal_...`;
  até 8 MB e sem parser inferido. **Não** é evidência de vigência
  ou correspondência com a PAM 1612 atual.

Segurança: HTTPS exclusivo, domínios/paths restritos, sem porta ou
credenciais na URL, sem redirecionamentos, sem proxy de ambiente,
`Accept-Encoding: identity`, timeout restrito, Content-Type e limites
antes de normalização, e indicador de coleta sintética injetada distinto
de HTTP real. Uma chamada HTTP real bloqueia carimbo de coleta
arbitrariamente retroativo. Exige `IBGE_PAM` *enabled* e
`collection_authorized` no catálogo e direitos expressos de
`COLETA` + `ARMAZENAMENTO`, com identificador de autorização.
Isso verifica apenas declarações; não comprova contrato ou licença real.

**Resultado:** `CAPTURA_PONTUAL_PAM_QUARENTENA_NAO_HOMOLOGADA`.
Retorna bytes, hash e referência de direitos sem alterar o ledger,
atribuir data de publicação oficial ou liberar treinamento.

### `src/nivon/ivo_pam_quarentena.py`

Grava localmente bytes de candidato por SHA256 em
`objetos_sha256/<hash>.bin` e gera recibos JSON imutáveis com URL,
hash, tamanho e instante de captura declarado, em `recibos/<hash>.json`.
É **quarentena segregada**, não o banco canônico. Não realiza captura HTTP.
Suporta idempotência e múltiplas coletas do mesmo arquivo em datas
diferentes. Confere novamente bytes e manifesto durante leitura, rejeita
hash adulterado, conteúdo diverso com mesma identidade, links simbólicos
e tentativas de exceder a quota local de 64 MB por padrão.
Preserva `treinamento_real_autorizado=False` e
`ledger_canonico_atualizado=False` até auditoria independente.
A declaração de instante de captura não é uma assinatura de tempo
confiável; requer auditoria de logs e horário real da aquisição.

### `src/nivon/ivo_pam_plano_acervo.py`

Converte avisos do `ivo_radar_erratas_pam.py` em lista pontual de
trabalho com três artefatos **distintos**:
1. anúncio oficial de errata (página do IBGE **não é PDF**);
2. consulta da versão **atual** do SIDRA, permitida apenas para
   fontes/direitos aprovados e quando aviso já visível no corte;
3. versão **anterior** do arquivo, com URL **nula e status não
   localizado** enquanto não houver acervo verificável.

Acrescenta os diretórios IBGE FTP PAM e LSPA apenas como contexto de
pesquisa; não confunde LSPA com PAM nem presume que o FTP contém
a versão antiga de Tangará da Serra.

## Testes

- `tests/test_ivo_pam_coletor_pontual.py`: uma requisição por chamada,
  fonte desligada, direitos não concedidos, plano SIDRA adulterado,
  URLs de ataque, portas, sem redirects, marcadores, JSON duplicado,
  MIME e tamanho, doc PDF fictício, diretório legado, datas retroativas.
- `tests/test_ivo_pam_quarentena.py`: bytes preservados, hash e
  recibo idempotentes, múltiplas capturas, arquivo adulterado,
  recibo adulterado, quota, symlinks, flags de homologação falsas,
  ausência de escrita canônica.
- `tests/test_ivo_pam_plano_acervo.py`: Tangará/Arandu, distinção
  antes/depois do aviso, município/cultura errada, URL exata
  canônica e ausência do original não preenchida artificialmente.

## Próximos gates

1. Revisão de direitos de coleta/armazenamento e liberação das flags
   `IBGE_PAM` pelo mecanismo de governança canônico, **não por
   atalhos na branch IVO**.
2. Coletar o JSON atual pontual autorizado, executar quarentena e
   conferir bytes/hash, Content-Type e fuso do carimbo efetivo.
3. Localizar arquivo **municipal 2021 anterior a setembro/2026** em
   acervo datado que preserve de fato a mesma variável/cultura/município.
   Não usar URL atual como prova do conteúdo antigo.
4. Registrar no ledger canônico **depois** de prova de direitos,
   publicação e revisão independente, separando a quarentena de
   arquivos usados como labels.
5. Testar benchmark anual REAL em sandbox somente quando o histórico,
   a metodologia PAM e a versão de rótulo tiverem evidências completas.
   Manter primeiros releases, erratas e coletas bitemporais distintos.

**Não comprovado:** obtenção efetiva do valor original da soja municipal
anterior à errata, autenticidade documental dos PDFs, direitos reais
concedidos, performance preditiva real, implantação ou operação recorrente.
