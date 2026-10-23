# NIVON R11 — Sincronização incremental CONAB/Argentina em lote

**Data:** 23/10/2026 (America/Cuiaba)  
**PR:** [#185](https://github.com/brunocapellari-dotcom/NIVON/pull/185). **Base:** R10 [#155](https://github.com/brunocapellari-dotcom/NIVON/pull/155).  
**CI do primeiro lote integrado:** [39983048779](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983048779), **2.377 testes, 0 falhas, 3 skips**.  
**CI com operador unificado:** [39983750676](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983750676), **2.384 testes, 0 falhas, 3 skips**.

## O que foi implementado

1. **CONAB, LAB somente:** reaproveita `sincronizacao_incremental_conab_lab.py` e suas dependências comprovadas da PR #157; histórico por SHA, delta de edições, revisão de semana bloqueada sem versionamento, integridade semântica e backup SQLite conferido. Os XLSX da referência são de terceiro/agrobr, **não** captura diretamente comprovada da CONAB; migração/publicação proibidas.
2. **Argentina/SAGyP, arquivo autorizado:** `sincronizacao_incremental_argentina_local.py` exige RAW CSV privados endereçados por SHA e catálogo de recursos. Lê e valida TODAS as novas entradas antes de qualquer inserção; insere o lote numa transação SQLite única, com SHA semântico das linhas, verifica integridade referencial e bloqueia alteração de edição já persistida. Uma segunda execução sem delta não reprocessa RAW; nova versão preserva a edição anterior.
3. **Operador unificado:** `operador_incremental_agro.py` aceita as duas fontes em **bancos diferentes**, bloqueia execução por padrão e uso argentino sem confirmação explícita de direito de armazenamento. Não faz rede, nem credenciais, nem writes Google Cloud. Retorna status `LOTE_PARCIAL_FALHOU_FECHADO` quando a segunda fonte falha após a primeira ter concluído — **sem alegar transação distribuída entre bancos independentes**.

## Manifesto local SAGyP

Os nomes dos RAWs precisam ser SHA-256 do próprio conteúdo: `<sha256>.csv`, guardados em diretório privado (0700) com arquivos 0600. Exemplo sintético de estrutura, **não é arquivo real do portal**:

```json
{
  "schema": "NIVON_ARG_INCREMENTAL_RAW_LOCAL_V1",
  "edicoes": [
    {
      "recurso": "soja",
      "sha256": "SUBSTITUIR_PELO_SHA256_REAL_64_HEX",
      "arquivo": "SUBSTITUIR_PELO_SHA256_REAL_64_HEX.csv",
      "origem_url": "https://datos.magyp.gob.ar/dataset/estimaciones.csv",
      "coletado_em": "2026-10-23T10:00:00-04:00"
    }
  ]
}
```

A data de coleta acima é apenas ilustrativa. Nenhum campo de `publicado_em` é inferido do timestamp de coleta ou `last_modified` do CKAN. Na base, `publicado_utc=NULL` e `disponibilidad_verificada=0`; o dado permanece **ESTIMADO e em quarentena**, não elegível a preço corrente ou backtest as-of até prova independente de publicação.

## Entrada operacional única

Por padrão, o comando faz apenas resposta de bloqueio (sem escrita):

```bash
PYTHONPATH=src python -m nivon.operador_incremental_agro \
  --conab-manifesto /pasta-privada/conab.json \
  --conab-banco /pasta-privada/conab-lab.sqlite \
  --conab-raw-dir /pasta-privada/raw-conab \
  --conab-backups /pasta-privada/backups-conab \
  --argentina-manifesto /pasta-privada/argentina.json \
  --argentina-banco /pasta-privada/argentina.sqlite \
  --argentina-raw-dir /pasta-privada/raw-argentina
```

Para execução **somente local e somente após autorizações externas de armazenamento** e arquivos aprovados, acrescentar `--executar --direitos-argentina-verificados`. Não executar para fontes sem direitos verificáveis. O operador não é scheduler e **não foi executado contra serviços reais nesta PR**.

## Qualidade e governança

- **Testes CONAB:** delta, no-op sem download/backup, atomicidade, revisão conflitante, adulteração, backup corrompido/ausente e proteção de diretórios.
- **Testes Argentina:** três ciclos de versão, idempotência, rollback por RAW inválido ou duplicata econômica, adulteração histórica, bloqueio de diretórios hostis e negativa de publicação.
- **Testes do operador:** sem execução por padrão, falta de direitos, separação das bases, zero promoção e status fiel de falha parcial.
- **Persistência:** bases SQLite locais de laboratório/quarentena; a verdade editorial e as fontes atuais continuam fora desses bancos. **Nenhuma conexão GCS/BigQuery comprovada por esta PR.**
- **Próxima integração:** reconciliar os contratos de RAW, proveniência, datas e QUARANTINED com as pipelines Google Cloud existentes da [PR #174](https://github.com/brunocapellari-dotcom/NIVON/pull/174). Não duplicar infraestrutura GCS e não promover arquivos SAGyP/CONAB para BigQuery analítico sem data de publicação, direitos e proveniência verificados.
- **Segurança:** código de aquisição remota R06 segue DEFAULT-DENY para tráfego real sem egress homologado, independentemente dos direitos declarados no manifesto. A proteção da `main` e o bloqueio Trivy HIGH permanecem gates independentes.

**Estado:** versão integrada offline aprovada nas suítes; NÃO significa coleta contínua ativa, autorização de uso, disponibilização comercial ou deploy.
