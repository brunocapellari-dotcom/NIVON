# NIVON / IVO — Consolidação do ciclo PAM e preparação GCS

**Data:** 23/10/2026. **Estado:** implementação em PR draft, sem deploy, agendamento ativado, bucket criado, acesso GCS real, cobrança ou promoção canônica.

## O que foi unido

O piloto da PR #7 incluiu ciclo de coleta PAM, auditoria e cliente Google Cloud Storage. A PR #78 já possuía outro formato de backup auditado, uma ponte de revisão, CLI de importação e testes E2E. **Esses dois formatos ZIP não eram compatíveis.** Esta integração não instalou os dois formatos em paralelo: preservou `src/nivon/ivo_pam_backup.py` da PR #78 como **única autoridade de escrita/restauração de backup**.

O ciclo `src/nivon/ivo_pam_ciclo.py` foi adaptado para `operacional.sqlite`, objetos SHA e recibos na raiz restaurada, com argumentos canônicos `criar_backup_pam(banco, cofre, arquivo_zip)` e `restaurar_backup_pam(arquivo_zip, destino)`. Não aceita ZIP legado diretamente nem cria histórico novo sem `iniciar_novo=True`.

`src/nivon/ivo_pam_storage_gcs.py` foi adaptado à mesma API/estrutura de backup canônico. O protocolo implementado mantém backups GCS nomeados pelo SHA, bloqueia redirecionamentos e escrita em namespace estranho, exige `ifGenerationMatch`, baixa novamente e confere o backup antes de atualizar o ponteiro de estado. Um novo backup deve conter integralmente todas as linhas antigas de `pam_vintages` e `pam_capturas` e avançar o número de capturas. Corridas na geração do ponteiro falham sem sobrescrita. **Foi testado apenas em GCS simulado.**

## Migração explicitamente auditada do arquivo antigo

`src/nivon/ivo_pam_migracao_legado.py` aceita **somente** ZIP do piloto antigo com `pam.sqlite`, `cofre/objetos_sha256/`, `cofre/recibos/` e metadados conhecidos. Verifica nomes, contagem, expansão, links, SHA dos objetos, integridade SQLite/célula/recibo. Gera novo ZIP em staging temporário, testa restauração completa **antes** da publicação do arquivo convertido e usa hardlink exclusivo para não sobrescrever o destino.

```bash
PYTHONPATH=src python -m nivon.ivo_pam_migracao_legado \
  --origem /acervo_autorizado/pam_legado.zip \
  --destino /acervo_autorizado/pam_canonico.zip
```

Este comando **não foi executado com o ZIP verdadeiro do Drive nesta rodada**; tests usam históricos sintéticos criados em SQLite/quarentena reais do CI. Migrar não valida licença, autenticidade externa, publicação oficial antiga nem vigência de um dado PAM.

## Auditoria de revisões entre capturas

`src/nivon/ivo_pam_alertas.py` compara **a mesma célula** (município, ano civil, variável e categoria C81) entre capturas, com `LAG` SQL e delimitação as-of. Classifica primeira captura, sem mudança, alteração de estado, mudança numérica e novo arquivo com mesmo valor. **Exige auditoria completa SQLite + arquivos em quarentena antes de devolver qualquer alerta.** Suas diferenças numéricas são candidatas internas e nunca se tornam preços, operações realizadas, dados homologados ou datas de publicação.

## Cloud/CI preparados, mas inativos

- `tests/test_ivo_pam_storage_gcs_e2e.py`: integração com servidor GCS em memória, usando SQLite, ZIP e restaurações locais reais; inclui percurso de **dois ciclos completos** (inicial, GCS, recuperação, atualização, GCS, restauro).
- `tests/test_ivo_pam_ciclo_unificado_e2e.py`: novo ciclo, conservação de versões, falha sem sobrescrita, restauração e recusa de modo legado.
- `tests/test_ivo_pam_migracao_legado_e2e.py`: conversão, checksum, recuperação, arquivo adulterado, path traversal e CLI.
- `tests/test_ivo_pam_alertas_integridade_e2e.py`: alertas, janela temporal, repetição, recortes separados e bloqueio por corrupção.
- `.github/workflows/ivo-pam-gcs-inspecao-manual.yml`: **somente `workflow_dispatch`**, sem cron/push/PR; restrito a `main`, exige WIF existente e ambas variáveis `NIVON_PAM_GCS_HOMOLOGADO=true` e `NIVON_PAM_GCS_CUSTO_APROVADO=true`. Mesmo quando autorizado, chama apenas `ivo_pam_storage_gcs estado` para **ler** o ponteiro; não faz upload, recuperação nem coleta.
- O workflow anterior `.github/workflows/ivo-pam-piloto.yml` desta candidata **não foi substituído pela versão agendada da PR #7**, deliberadamente. É necessária revisão de homologação/custo/retention/bootstrap antes de habilitar coleta recorrente.

A configuração dessas variáveis, credenciais, bucket ou IAM **não foi realizada**. O fluxo GCS simulado e os testes não provam IAM externo, preços, latência, quotas ou disponibilidade de bucket.

## Próxima decisão técnica

1. Validar o estado e as permissões reais das fontes/objetos de backup previamente autorizados, independentemente do hash de integridade.
2. Se houver autorização, recuperar o pacote histórico genuíno (há registros do piloto com seis e depois 24 capturas em outra frente), **confirmar exatamente a versão adequada**, migrar sem sobrescrever o original e testar restauro.
3. Confirmar bucket privado, WIF/identidade, IAM restrito, FinOps, backup e política de retenção; somente após aprovação do proprietário habilitar o primeiro teste remoto e, posteriormente, gravação condicionada por geração.
4. Preparar a integração com Hermes e a revisão independente antes de qualquer promoção para a base canônica.
5. Conciliar as demais frentes da PR #13, mantendo relatórios PAM anuais distintos dos preços/fretes do NIVON.

**Ressalva:** o histórico local e seus SHA evidenciam capturas e integridade de arquivos; `coletado_em` não equivale a `publicado_em`, e uma versão obtida em outubro de 2026 não prova os dados disponibilizados em 2021–2024. Nenhum valor de simulação é reportado como observado.
