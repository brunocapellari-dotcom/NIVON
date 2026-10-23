# NIVON / IVO — Pipeline operacional PAM (offline e controlado)

**Marco:** 22/10/2026. **Escopo entregue:** fase local reversível, com teste E2E e resultados rastreáveis. **Não é autorização para coletar, publicar, treinar, pagar serviços ou fazer deploy.**

## Fluxo de execução

```text
Planejamento de 1–25 células SIDRA/PAM 1612
        │ preflight de município, cultura, ano e unidade
        ▼
Arquivos já recebidos localmente com SHA conferido
        │ OU transporte injetado exclusivamente no ambiente de teste
        ▼
Coletor pontual reutilizado, sem rede implícita no orquestrador
        ▼
Quarentena por hash (bytes originais + recibos imutáveis)
        ▼
Auditoria: célula, tamanho, URL, SHA, unidade, origem declarada e PDF
        ▼
Manifesto de lote com resultados e falhas isoladas
        ▼
Fila de revisão independente: licença, publicação, assinatura, OIDC
        ▼
BLOQUEADO: nenhuma escrita canônica / modelo / publicação automática
```

### Módulos integrados de verdade no código

- `src/nivon/ivo_pam_operacao_lote.py`: pré-valida até 25 recortes; exige transporte injetado, fonte e direitos declarados, validações IBGE SIDRA e quota; encadeia coleta, quarentena, auditoria e manifesto com SHA; permite tratamento explícito de erros operacionais isolados. Preflight inválido impede qualquer arquivo; arquivo capturado antes de falha de auditoria continua em quarentena e nunca é promovido.
- `src/nivon/ivo_pam_gate_promocao.py`: confere integridade e estrutura do manifesto, rejeita pedidos de promoção forjados, cria fila detalhada de provas independentes necessárias. SHA local é **somente integridade, não autenticação criptográfica de terceiro**. Não há método de aprovação automática.
- `src/nivon/ivo_pam_cli_local.py`: importador de arquivos pré-existentes a partir de lista explícita com hashes; valida todos os caminhos, SHA, horários e recortes antes de tocar o destino. Não existe chamada HTTP nesse caminho. Emite `manifesto_<sha>.json`, `fila_<sha>.json` e guarda bytes em `quarentena/`; repetição com conteúdo idêntico é permitida, adulteração bloqueada.
- `scripts/smoke_ivo_pam_lote.py`: exercício completo com **dois municípios e culturas sintéticos**, duas execuções idempotentes, importação real desses arquivos sintéticos do disco e validação dos dois relatórios.
- `tests/test_ivo_pam_lote_e2e.py` e `tests/test_ivo_pam_cli_local.py`: testes E2E para plano, dois registros, execução, idempotência, PDF complementar, recusa de URL e path traversal/symlink, hash adulterado, quota, falhas isoladas, sigilo, não promoção, não publicação e saída CLI.
- `.github/workflows/testes.yml`: executa o smoke do fluxo após a suíte em todos os PRs, sem secrets ou rede para PAM.

## Como usar o importador LOCAL, com dados que já podem ser mantidos legitimamente

Prepare um diretório com `pam_soja.json` e um arquivo `manifesto.json`. O exemplo abaixo é **somente ilustrativo**; o SHA precisa ser o **SHA-256 real do arquivo correspondente**, nunca o de outro arquivo. Confirme previamente os direitos de guarda dos arquivos.

```json
{
  "schema": "nivon_ivo_pam_importacao_local_v1",
  "somente_quarentena": true,
  "publicacao_proibida": true,
  "capturado_em_declarado": "2026-10-21T15:00:00+00:00",
  "referencia_direitos_declarada": "REFERENCIA_DOCUMENTAL_NAO_ATESTADA",
  "itens": [
    {
      "municipio_ibge": "5107958",
      "ano": 2021,
      "categoria_c81": "2713",
      "variavel": "214",
      "arquivo": "pam_soja.json",
      "arquivo_sha256": "<SUBSTITUIR_POR_SHA256_REAL_DO_ARQUIVO>"
    }
  ]
}
```

O campo SHA de exemplo é **placeholder inválido** e deve ser preenchido com os 64 dígitos hexadecimais do conteúdo efetivo. Este formato permite acrescentar até 25 registros e, opcionalmente, `pdf_url`, `pdf_arquivo`, `pdf_sha256`, `publicacao_declarada` e `versao_anterior_sha256`. A existência desses metadados não atesta uma data ou licença.

```bash
PYTHONPATH=src python -m nivon.ivo_pam_cli_local \
  --manifesto /caminho/arquivos/manifesto.json \
  --destino /caminho/quarentena_nivon

PYTHONPATH=src python scripts/smoke_ivo_pam_lote.py
```

A primeira execução materializa **somente** quarentena e fila de revisão para os arquivos que já possui; não baixa nada. A segunda é uma demonstração com fixtures sintéticas. O shell acima é documentação; **nenhum comando de importação com arquivo real foi executado nesta etapa**.

## Semântica obrigatória dos resultados

| Saída | O que efetivamente significa |
| --- | --- |
| `AUDITORIA_LOCAL_PENDENTE_HOMOLOGACAO` | Integridade e semântica locais examinadas, **não** prova de produção/verdade |
| `ERRO_OPERACIONAL_ISOLADO` | Um recorte falhou; podem existir objetos parciais em quarentena |
| `QUARENTENA_LOCAL_COM_FALHAS` | A importação criou relatórios, mas nem todos os recortes passaram |
| `REVISAO_INDEPENDENTE_NAO_EXECUTADA` | Trabalho de auditoria externo ainda a realizar |
| `AGUARDANDO_REVISAO_EXTERNA_NENHUMA_PROMOCAO` | Gate final não concede promoção nem liberação de treino |
| `manifesto_sha256` / `fila_sha256` | Integridade da representação local; não assinatura de autoridade |

## CI verificado

O checkpoint `0e38b2df4f028dcdedf3809ebfe334921ff87902` passou no [workflow GitHub Actions #39890696847](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890696847): **1.371 testes executados, 1.363 aprovados, 8 ignorados, zero falhas**. O smoke imprimiu `E2E_SUCESSO_REVISAO_PENDENTE`, importou dois arquivos locais sintéticos, escreveu dois relatórios e confirmou zero promoções.

## Portões P0 para atravessar a fronteira de produção

1. **Direito comprovado:** fonte/condição de uso/referência jurídica por operação (coleta, guarda, consulta, treino, redistribuição), com vigência e revogação. O manifesto registra apenas declaração, não valida direitos reais.
2. **Proveniência externa:** preservar bytes oficiais e identificar o arquivo realmente anterior à retificação; confirmar a data oficial e vincular o PDF à célula e competência, sem inferir.
3. **Assinatura e revisão independente:** servidor de auditoria autorizado, identidade distinta do coletor, trilha de assinatura, KMS e âncora de timestamp externos. Não reutilizar o SHA simples como selo jurídico.
4. **Hermes e autorização:** OIDC, ACL atual com lease, OPA/OpenFGA e tratamento fail-closed da aprovação pendente da PR Hermes #35.
5. **Persistência gerenciada e rollback:** controle de tenant e permissões, storage e backup exportável, observabilidade, teste de restauro, custos mensurados e aprovação de implantação.
6. **Integração das demais frentes:** o fluxo aqui se limita ao PAM/IVO; CEPEA, IMEA, CONAB, fretes e CBOT possuem seus próprios coletores e licenças. Este pipeline não os declara conectados.

**Governança:** os flags de catálogo habilitados no importador são **somente objetos temporários para satisfazer o contrato do adaptador offline**. Não alteram o registro canônico nem autorizam aquisição em rede. Nenhuma informação de unidade histórica é promovida automaticamente para motor quantitativo.
