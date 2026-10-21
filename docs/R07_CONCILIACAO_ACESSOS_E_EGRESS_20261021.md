# NIVON — R07 | reconciliação com `main` e bloqueio de egress implícito

**Data:** 21/10/2026. **Situação:** candidato PR #74 draft, sem merge ou deploy.

## Estado GitHub observado
- Base R06: PR #69, `3a830939c37a8400e74c88bf20a34f27604a369c`.
- A `main` atualizou-se após os merges das PRs #63 e #65 para `ca9d19585e8eb807cdac5b2a1cbe48678b4ef479`. A PR #65 apenas ajustou `runner.temp` em steps do workflow INMET e sua verificação.
- Dos treze arquivos distintos introduzidos pelos merges, **sete já existiam com SHA de blob idêntico** no candidato R06. Os seis restantes foram importados **da `main` atual** sem reescrever seus blobs:
  - `.github/workflows/acessos-privados.yml`: `7e568e8a1bc38bc6e7803c4085c467e0ce97ad38`
  - `.github/workflows/testes-acessos-isolados.yml`: `282bcfa4bd98fd670d4348c0841d0a0517933373`
  - `docs/BOOTSTRAP_ACESSOS_PROTEGIDOS.md`: `7fcb3bcd0230cc42e811e170388cf27f340bc52d`
  - `src/nivon/acessos_smoke_privado.py`: `043ad53e696544fb8559cc0e9643e34935750367`
  - `tests/test_acessos_smoke_privado.py`: `cea3fdd882f3e2c230b078eac772b35e77a4962e`
  - `tests/test_seguranca_workflows_acessos.py`: `c3d6f3c51a3023b14354e268d10e200c1075a81f`
- PR #7 (IVO) `13be715d...` → `2737e2e527dcb5a03653f0391a8661c6790dfe0e`: documento Rodada 11 e duas alterações (benchmark PAM anual e teste) incorporados em três paths. O código novo exige que todos os artefatos, incluindo edições futuras fora do corte retrospectivo, sejam identificados como **SINTETICO** no ledger antes de permitir benchmark sintético.

## Acesso privado e governança
- `acessos-privados.yml` é somente `workflow_dispatch`, exclusivamente no `main` e no GitHub Environment `nivon-fontes-privadas`, com `preflight` padrão. `live` requer decisão manual adicional do usuário. Este ciclo não disparou workflows manuais nem utilizou credenciais reais.
- `testes-acessos-isolados.yml` valida em pull requests sem secrets e sem endpoints externos; retorna `REDE_DESATIVADA` para USDA/ANA/INMET no ensaio sem opção live.
- Esses acessos não representam licença comprovada, coleta, persistência, dado atual, API geral disponível nem aprovação de conteúdo pela Knowledge Factory.

## Risco R06 e mudança implementada
- Em `src/nivon/coleta_web.py` havia fallback `build_opener(_SemRedirecionar())` quando `abridor=None`. Autorizar uma `FonteWeb` por metadados permitia que esse caminho resolvesse DNS e conectasse sem verificação independente do IP real, vulnerável a **DNS rebinding** caso nomes públicos resolvessem a destinos internos.
- A integração removeu o fallback: `adquirir_fonte` agora **lança `PermissionError: EGRESS_NAO_HOMOLOGADO`** quando não recebe transporte explícito, mesmo para fonte declarada `APROVADA`. Com abridor sintético injetado, seguem os testes offline de resposta/sha/mime/limite.
- O bloqueio evita o egress implícito **neste adaptador**. **Não** certifica o transporte injetado; antes de habilitar produção, exigir implementação e prova de pinning IP/TLS/SNI, análise de DNS em cada conexão, anti-redirect, denylist de IP especial, firewall/egress proxy, proteção de redirects e auditoria de credenciais. Outros clientes de rede do repositório precisam de revisão separada.
- O controle de direitos ainda depende de autorização/autenticação real por operação e não apenas do campo de um objeto Python.

## Evidência e limites
- CI após conciliação de main + PAM: [núcleo 39663107718](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39663107718) — **2.034 testes, OK (skipped=3)**; [acessos isolados 39663107680](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39663107680) — **2.034 testes, OK (skipped=35)**. Ambos offline, nenhum acesso live.
- Mudança R06 de egress: `tests/test_coleta_web.py` adiciona teste de default-deny mesmo com direitos declarados, além dos testes anteriores de URL hostil. **O HEAD desta nota é posterior aos dois resultados acima**; requer reexecutar CI e registrar run do HEAD final.
- O número de skips varia porque o workflow isolado não instala todos os extras; a diferença não deve ser tomada como resultado aprovado das bibliotecas ausentes.

## Próximos bloqueios
1. Validar egress restrito para cada coletor real, em sandbox de rede com IP pinning e testes adversariais de DNS rebinding.
2. Provar operação e termos de USDA/ANA/INMET por fonte, sem publicar URLs/segredos nos logs. Habilitação manual somente após avaliação explícita.
3. Integrar IAM/assinatura/revogação do Segundo Cérebro ao IVO e reforçar leitura `as-of` como dado não confiável; não duplicar conhecimento canônico.
4. Unificar os ledgers `outbox_briefing.py` e `outbox_whatsapp.py` com idempotência transversal e opt-out validado.
5. Auditar custo e redundância dos dois jobs completos em PR, preservar branch protection e testes de restore antes de qualquer promoção.
6. Mesmo com CI verde, PRs #1/#13/#14/#30/#40/#41/#50/#69 e esta PR #74 continuam não homologadas e sem autorização de merge.
