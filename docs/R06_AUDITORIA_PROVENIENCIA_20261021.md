# NIVON — R06: proteção de entrada, proveniência e dados hostis

**Data:** 21/10/2026. **Situação:** PR #69 em draft, testes sintéticos/offline; não é habilitação de coleta ou produção.

## Base, origem e escopo

- Base da integração: PR #50, commit `86aaa51b96120c143d5b999eca85ce8cf2c960c0`.
- PR #7 avançou de `0c45d466a17136d878d105c2deb41308d30466a3` para `13be715d83685eaced437f4a692344c009e73924`. O delta tinha cinco arquivos **novos**, sem conflitos: histórico de publicações PAM, benchmark anual PAM, dois testes e a rodada de documentação; todos foram transpostos por SHA.
- Escopo de risco R06: URLs hostis contra coletores, reputação de fontes, integridade de claims e isolamento entre contextos. NÃO compreende homologação de DNS/egress/provedor externo ou validação do conteúdo científico.

## Implementação verificável

### 1. Coleta HTTP default-deny
- `src/nivon/coleta_web.py`: `FonteWeb.verificar` rejeita antes de `abridor.open`: hosts `localhost`, `.local`, `.internal`, `.test`, IPs literais, credenciais, portas diferentes de HTTPS, fragmentos, URL malformada, caracteres de controle, hosts sem nome de domínio e URL excessiva.
- A origem e o host continuam presos ao contrato da fonte e os redirects permanecem proibidos.
- Em `tests/test_coleta_web.py`, fontes adversariais usam um abridor sintético que confirma **zero** tentativas de abertura quando a URL é negada; as variantes CR/LF são bytes de controle reais, não sequências escapadas.
- **Importante:** hostname público pode resolver para IP privado (DNS rebinding), e uma declaração `status_direitos=APROVADA` em objeto local não é prova externa de concessão. Para conectores reais ainda são obrigatórios egress allowlist independente, verificação da resolução DNS no momento da conexão, proibição de redirecionamento, prova de autorização versionada, limites de download e auditoria. A presente PR **não** ativa o coletor.

### 2. Snapshots assinados do IVO
- Novo `src/nivon/ivo_atestacao_conhecimento.py` fornece **uma via opt-in** de verificação criptográfica do snapshot completo, com hash SHA-256 de TODOS os campos das claims (incluindo texto, origem, status, direitos, tipo, datas e supersession), assinatura HMAC-SHA256, comparação constante, versão, audiência, emissor e contexto explícitos, janela de validade e data de corte.
- Chave HMAC **não vem do snapshot, prompt, notícia ou documento**. Ela precisa ser injetada pelo chamador autorizado, obtida do cofre de segredos, com `emissor_confiavel` e `contexto_esperado` independentes. Nenhuma chave de produção foi usada, criada, consultada ou armazenada.
- Mesmo após assinatura correta, as saídas permanecem: `aprovacao_externa_verificada=false`, `publicacao_autorizada=false`, `escrita_canonica_autorizada=false`. A assinatura prova apenas que alguém com a chave configurada autenticou aquele conteúdo/contexto; NÃO prova que a organização emissora é a Knowledge Factory real ou que direitos, claims, fontes e avaliações científicas foram aprovados.
- O caminho `recuperar_claims_asof` **antigo permanece funcional e declarado NÃO autenticado externamente**. O novo caminho `recuperar_claims_de_snapshot_assinado` exige HMAC antes de consultar; ainda não foi ligado ao serviço Knowledge Factory real. Não considerar esta PR enforcement global de atestação.
- Sem ledger durável de revogação/replay, rotação de chaves, verificação de emissor via IAM e auditoria de cross-tenant; todos continuam bloqueadores de produção.

### 3. Testes adversariais
- `tests/test_ivo_atestacao_conhecimento.py`: assinatura válida sem permissão de publicação, adulteração de texto/direitos/tipo projetado→observado/URL/data, assinatura falsificada e troca de chave, emissor/audiência/contexto spoof, expiração/look-ahead, esquema inesperado, tamanho mínimo de chave, prompt injection tratado como **texto não confiável**, IDs duplicados rejeitados.
- `tests/test_coleta_web.py`: URL maliciosa não dispara chamada de rede mesmo com aprovação declarada sintética.
- A primeira execução da PR #69 falhou **por fixture de teste** que usou barra invertida+letra `n` em vez de LF literal. A amostra foi corrigida usando `chr(10)` e `chr(13)`; não era uma correção na validação operacional. Reexecutou-se a suíte inteira.
- Evidência [GitHub Actions #39655089552](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655089552): **2.005 testes; 0 falhas; 3 ignorados**, teste R06 da URL hostil e oito testes de assinatura passaram. Essa execução corresponde ao commit `bcc76b3b0664b7c84d5502ffff4846813de262df`; esta nota documental cria um HEAD posterior que exige nova validação.

## Gates críticos ainda abertos

1. **R06 rede real**: política de egress robusta a DNS rebinding, inspeção de XML/PDF/ZIP/XLSX em sandbox isolado, validação de MIME/bytes, decompression ratio e nenhum bypass de WAF/robots/termos.
2. **R06 Segundo Cérebro**: autenticação da identidade real da Knowledge Factory via IAM, mapeamento tenant/context, assinatura aprovada, rotação/revogação, status de auditoria rastreável e contrato de leitura canônica.
3. **Outbox WhatsApp**: unificação de `outbox_briefing` e `outbox_whatsapp`, consentimento e opt-out/verificação final, estados idempotentes e reconciliação de ACK/webhook.
4. **Previsões e modelos**: validação point-in-time com dados licenciados e comparáveis, separação observação/projeção, vedação de publicação sem auditoria. Testes ML opcionais foram ignorados na suíte padrão.
5. **Infra, segurança e custos**: restore, observabilidade, segredos fora do código, regras de branch protection e aprovação explícita de qualquer ação irreversível.

**Política operacional:** PR somente draft; sem merge para `main`, deploy, envio de mensagens, execução remota, coleta de dados reais ou promoção de conhecimento/modelos.
