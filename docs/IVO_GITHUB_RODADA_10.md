# IVO — Rodada 10: histórico de divulgações e erratas da PAM/IBGE

**Data-base: 21/10/2026.** Código no PR #7 (draft), sem coletar
PDFs/SIDRA reais nesta rodada, sem homologação externa, sem deployment,
contratação, merge, modelos treinados ou publicação operacional.

## Evidência de que as revisões importam

Fontes oficiais de consulta:
- [PAM — culturas temporárias e permanentes, IBGE](https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9117-producao-agricola-municipal-culturas-temporarias-e-permanentes.html)
- [Erramos — IBGE](https://www.ibge.gov.br/erramos.html)
- [Tabelas PAM/SIDRA](https://sidra.ibge.gov.br/pesquisa/pam/tabelas/)

No catálogo oficial de Erramos, o IBGE registra correções de:
- soja no município de **Tangará da Serra (MT), PAM 2021**, publicadas
  em 17/09/2026;
- banana em **Itacuruba (PE), PAM 2023**, publicadas em 17/09/2026;
- uva e manga em **Juazeiro e Casa Nova (BA), PAM 2025**, em 01/10/2026.

Esses eventos demonstram que o valor atualmente exibido no SIDRA pode
ser diferente do valor que estava disponível em um período passado.
Não reconstruir historicamente o valor antigo a partir do JSON novo.

## Implementação — `src/nivon/ivo_pam_publicacoes.py`

Nova função `historico_edicoes_pam_asof` recebe um conjunto pequeno e
explicitamente fornecido de `EventoPAM`. Cada evento possui:
- identidade, divulgação original ou errata;
- município IBGE, ano civil, código de variável SIDRA e categoria C81;
- **bytes JSON originais** e instante de sua captura;
- **bytes PDF da evidência**, URL de domínio IBGE, SHA-256 calculado
  dos bytes, publicação declarada, captura documental e revisor declarado;
- referência aos snapshots separados JSON e PDF já presentes no ledger
  `registro_snapshots`.

Exige no registro do NIVON correspondência exata para fonte, documento,
SHA, tamanho, MIME, schema, publicação declarada, ano, referência,
captura e classe `SINTETICO` ou `REAL_AUTORIZADO`. O JSON é
normalizado por `sidra_pam` através da ponte
`ivo_pam_bridge.preparar_pam_anual_asof`; plano é revalidado contra
o endpoint SIDRA canônico. Não há segundo coletor, cópia de lib ou
requisição HTTP.

O corte temporal considera **publicação, captura dos dois arquivos e
revisão declarada**. Edições futuras ficam invisíveis.
Uma `ERRATA` não pode surgir como histórico isolado sem
`DIVULGACAO` original já conhecida; não pode haver mais de
uma divulgação original da mesma série; versões ambíguas no mesmo
instante geram erro, nunca desempate arbitrário.

Para cada versão visível, retorna SHA do JSON e PDF, datas de captura,
status, classe de snapshot, revisor declarado, valor anual e alteração
numérica absoluta desde a edição anterior. Preserva originais e
erratas; não regrava os valores do passado.

**O teste de republicação demonstra que** novo arquivo com novos bytes,
mas mesmo valor anual, gera delta zero sem alegar ganho ou perda
estatística. O ledger impede atribuir datas de publicações conflitantes
ao mesmo hash do JSON.

## Limitações e controles de segurança

- PDF com cabeçalho válido, SHA correto e URL `ibge.gov.br` **não
  prova** origem oficial: falta verificação de assinatura, vínculo
  documental ao registro pesquisado, hash recuperado de canal oficial,
  licença e revisão metodológica independente.
- A data de publicação no JSON SIDRA pontual é ausente; a versão
  declarada no ledger **não substitui** prova de liberação pública.
- Um documento de errata geral não comprova automaticamente alteração
  no município/cultura/variável especificado; o escopo deve ser conferido
  documentalmente por um humano ou parser supervisionado.
- Por desenho, `label_final_certificado=False`,
  `treinamento_real_autorizado=False`,
  `data_oficial_publicacao_comprovada=False` e
  `origem_documental_autenticada_externamente=False`.
- Sem extrapolação de calendário **ANO_CIVIL** para competências
  mensais ou safras comerciais. A estatística PAM é anual.
- Marcadores SIDRA de sigilo, indisponibilidade e zero arredondado
  não viram resultado observado certificado.

## Testes

`tests/test_ivo_pam_publicacoes.py` usa **somente PDFs/JSON sintéticos**
armazenados em memória com os contratos originais
`sidra_pam` e `registro_snapshots`. Testa:
- primeira publicação e errata posterior;
- reprodução do valor disponível antes/depois da errata;
- corte antes da publicação e da revisão;
- rejeição de PDF ou hash sem snapshot;
- URL oficial estrita (sem subdomínio malicioso, porta ou HTTP);
- municípios, anos, categorias e planos não misturáveis;
- IDs duplicados, duas originais, errata isolada;
- documento com publicação divergente do JSON;
- valores censurados/ausentes não usados como resultados;
- republicação sem alteração de valor;
- classe de snapshot exposta.

Os exemplos usam datas inventadas **somente nas fixtures sintéticas**;
não são reprodução de payload de IBGE/errata real.

## Próxima prioridade

1. Resolver **documentos oficiais datados e escopo da errata** para
   os casos reais conhecidos e conferir se há informação histórica
   suficiente para reconstruir original e versão corrigida.
2. Preparar camada anual de backtest por município/cultura/variável,
   com baselines e etiqueta separada de qualidade de resultado.
3. Provar os direitos por finalidade, documentação técnica, auditoria
   independente, integridade dos dados reais e calendário de liberação.
4. Somente após a homologação, avaliar modelos anuais com resultados
   estatísticos reais. Sem propagação automática para produção, mercado
   físico, preço de frete ou recomendação de trade.

**Situação:** a cronologia pode ser reconstruída apenas para as edições
originais realmente disponíveis e arquivadas. Sem arquivos históricos
capturados, não é possível inventar o valor anterior a uma errata.
