# IVO — Rodada 14: pacote de auditoria somente leitura de arquivos PAM/SIDRA

**Data:** 21/10/2026 (local do usuário). **Escopo:** integração local com a
quarentena construída na 13ª rodada. **Sem merge, deploy, contratação,
coleta real, mudança da política IBGE_PAM, homologação estatística ou treino.**

## Estado recuperado do repositório

- PR #1 (núcleo NIVON): SHA `662dbd5cdb685346ceba20d49953e8bf2508cb0e`.
- PR #7 (IVO): parte dessa base; rascunho e mergeable no início e na
  reconferência desta rodada.
- Última CI anterior: 1.207 testes (8 ignorados).
- No catálogo canônico, `IBGE_PAM` segue `enabled=false` e
  `collection_authorized=false`. Nenhuma flag foi alterada.
- Coleta real não deve ser simulada pelo transporte injetado em testes.
- Havia módulos de aquisição pontual e armazenamento de bytes por hash,
  mas nenhum contrato independente de **verificação do pacote completo**.

## Entrega

`src/nivon/ivo_pam_pacote_auditoria.py`:

1. Recebe SHA do recibo do JSON SIDRA, plano canônico
   `sidra_pam.planejar_pam_1612`, e opcionalmente SHA de recibo de PDF,
   data de publicação **declarada** e SHA **não validado** de versão anterior.
2. Recupera os arquivos por endereço de conteúdo na **quarentena local**,
   reutilizando `ivo_pam_quarentena.conferir_recibo_pam`, reconfere
   tamanhos e SHA-256; bloqueia objetos e recibos ausentes, alterados,
   symlinks e caminhos que não correspondem ao contrato.
3. Confirma a URL exata gerada pelo planejador da tabela SIDRA **1612**
   para um único município de 7 dígitos, ano civil, variável e produto.
   Não aceita PDF como JSON, outra tabela, município, cultura ou ano.
4. Passa os bytes **originais** ao
   `sidra_pam.normalizar_pam_1612` e aplica o mapeamento
   `ivo_pam_semantica.conferir_semantica_pam_1612`, distinguindo
   hectares de toneladas e retornando `marcadores especiais` como
   indisponíveis para inferência de valor numérico exato.
5. Admite PDF adicional somente como **documento anexado não autenticado**:
   hash, URL e direitos declarados precisam ser consistentes com o
   recibo. Isso **não** vincula conteúdo do PDF à célula específica do
   SIDRA nem comprova sua data de publicação.
6. Recusa data de publicação declarada posterior ao instante de coleta,
   ou dia inválido. Uma data declarada coerente **não é** comprovação
   da data oficial de publicação.
7. Se for indicado um hash de versão histórica anterior, trata-o
   como **referência ainda não verificada**, nunca como prova de posse
   ou de conteúdo do arquivo antigo.
8. Produz lista de bloqueios com ausência de publicação/autenticidade
   externa, direitos de treinamento, revisão independente, documento
   complementar e histórico anterior, sem liberar dados para modelos.
9. **Não escreve** no ledger `registro_snapshots` ou conhecimento
   canônico. Não baixa nenhum arquivo e não chama modelos.

### Testes

`tests/test_ivo_pam_pacote_auditoria.py`: fluxo ponta a ponta
`coletor sintético -> quarentena local -> auditoria read-only`.
Valida bytes, recibos, município, ano, cultura, variável, unidade,
documento opcional, direitos conflitantes, publicação incoerente,
marcadores de sigilo/zero, arquivo alterado, documento usado na
posição errada, e recusa de inferir treino ou publicação homologados.

Houve um erro de sintaxe inicialmente ao escrever um PDF sintético
com caracteres acentuados num literal `bytes`. O teste foi corrigido
para codificação UTF-8 explícita. Uma alteração concorrente na
frente de erratas também afetou testes temporais; as atualizações
foram preservadas e o conjunto voltou a passar.

**CI após correções simultâneas:** [GitHub Actions 39698750312](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698750312),
SHA `52132f8a5db236b9cdefc9daad5c936e0a80244d`:
**1.222 testes executados, 8 ignorados, 1.214 aprovados**. A execução
final após adicionar este documento deve ser conferida separadamente.

## Gaps executáveis — não concluir por simples presença do código

1. Prova documental da licença de coleta/armazenamento da PAM e eventual
   uso em aprendizado ou redistribuição, assinada ou vinculada à norma
   vigente, auditada na governança canônica.
2. Acervo persistente autorizado, com controle de acesso, backup e
   restauração ensaiada. A quarentena local **não é cloud** nem
   armazenamento imutável criptograficamente.
3. Auditoria de fonte: anexar link do aviso original, PDF/planilha
   oficial com versão exata, data e hash; comparar o escopo efetivamente
   descrito com o município/cultura/ano do SIDRA.
4. Encontrar os bytes **anteriores** às erratas da PAM 2021 de
   Tangará da Serra, comprovando captura/arquivamento na época. A URL
   atual do SIDRA não substitui a versão histórica.
5. Projetar posterior fluxo de promoção independente
   `QUARENTENA -> REVIEW ASSINADO -> VINTAGE CANÔNICA`;
   evitar escrita automática no ledger ou treino antes das evidências.
6. E2E com dados reais licenciados, teste de falha/rollback e
   custo de armazenamento cloud antes de go-live.

**Distinção central:** dados de origem IBGE, dados com SHA válido e
dados homologados são três níveis diferentes. O IVO não deve saltar
automaticamente de um nível para outro.
