# NIVON — Auditoria independente R06: resolução DNS e SSRF

**Data:** 21/10/2026 (America/Cuiaba)  
**Implementação auditada:** [PR #69](https://github.com/brunocapellari-dotcom/NIVON/pull/69), SHA `3a830939c37a8400e74c88bf20a34f27604a369c`.  
**Auditoria:** [PR #77](https://github.com/brunocapellari-dotcom/NIVON/pull/77), branch `audit/r06-ssrf-resolucao-dns-20261021`.  
**Código produtivo:** não modificado. Apenas testes e este relatório.  
**Evidência inicial:** [GitHub Actions 39663416968](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39663416968) (SHA `3bed7a6c979a69a919d5789513350537f105c983`), 2.009 testes, 11 falhas de subcasos, 3 skips.  
**Teste revisado:** commit `9ee8d16e56ea13e33942a54d4db6c9bfd83b0ed2`, usando IPs globais verdadeiros **somente no mock** em vez de faixas de documentação nos casos de resposta mista.

## Problema comprovado no contrato local

`src/nivon/coleta_web.py` / `FonteWeb.verificar()` bloqueia IPs literais e hostnames de zonas internas, exige domínio textual aprovado, HTTPS, porta 443 e ausência de redirects. É uma melhoria válida. Porém, `adquirir_fonte()` não consulta ou valida os endereços A/AAAA resolvidos antes de chamar `abridor.open`. A chamada HTTP pode receber um domínio aprovado que aponta para rede interna/metadata se não houver controle independente de DNS/egress.

**NC-AUD-024 — P0 para ativação de coleta externa:** DNS de domínio aprovado resolve endereço privado, link-local ou loopback sem rejeição na camada testada. A variante de DNS misto (IP global + interno) também é aceita pelo coletor. Riscos de SSRF não foram demonstrados em rede real; esta é evidência de que falta uma defesa no aplicativo, em linha com o bloqueio explicitamente reconhecido pela equipe R06. **Não classificar os 11 subcasos como CVEs distintos ou incidentes reais.**

### Casos executados

- **Controle positivo:** `https://169.254.169.254/` como URL literal é rejeitada com `ErroAquisicao` antes de usar o abridor (verde).
- **Controle positivo:** HTML sintético de domínio nominal autorizado retorna hash/metadados e classificação `ARQUIVO_COLETADO_NAO_EQUIVALE_DADO_OPERACIONAL_VALIDADO`, sem homologação (verde).
- **Adversarial DNS privado:** com `socket.getaddrinfo` simulado, oito endereços (`127.0.0.1`, `10.2.3.4`, `172.16.0.5`, `192.168.1.20`, `169.254.169.254`, `::1`, `fd00::55`, `fe80::1`) são aceitos até o ponto de chamada do abridor; deveria haver rejeição antes de HTTP.
- **Adversarial DNS misto:** com `socket.getaddrinfo` simulado, três pares de endereços (IPv4 `1.1.1.1` + `127.0.0.1`, IPv4 `1.1.1.1` + metadata, IPv6 `2606:4700:4700::1111` + `fd00::1`) também chegam ao abridor.

Os valores públicos são strings de fixture usadas para modelar respostas DNS mistas, **não alvos de acesso**. Todas as chamadas HTTP são respondidas por um abridor artificial dentro do teste. Não houve lookup DNS real, socket externo, SSRF operacional ou exfiltração de dados.

## Critério de correção

1. Preservar default-deny de `status_direitos`, `operacoes_permitidas`, HTTPS, domínio, porta, MIME, tamanho, hash, redirects desativados.
2. Verificar todas as resoluções DNS A/AAAA contra política que proíba qualquer IP não globalmente roteável, inclusive privado, loopback, link-local, multicast, reserved e os endereços especiais de metadados cloud. Qualquer resposta não permitida deve falhar fechado.
3. Evitar **TOCTOU / DNS rebinding**: validar o IP **efetivamente conectado**, não somente consultar DNS e deixar o cliente HTTP resolver novamente. Necessário pinning seguro da conexão/TLS SNI e `Host`, ou política equivalente no proxy de egress e firewall. Respeitar proxies/túneis e não confiar em verificações textuais isoladas.
4. Retestar os quatro testes independentes da PR #77 e adicionar teste de rebinding no transporte/egress controlado com prova de recusa de socket para IP privado. A suíte atual, com `abridor` falso, **não demonstra** enforcement da infraestrutura de egress nem cobre corrida real de DNS.
5. Não ativar coleta real até verificação de direitos das fontes, segregação de chaves, testes de rede, limites por origem, logs minimizados e autorização operacional explícita.

## Estado

**REPROVADO para homologação de coleta externa.** O teste formaliza uma lacuna já reconhecida no documento `docs/R06_AUDITORIA_PROVENIENCIA_20261021.md`; não houve mudança de implementação, merge, deploy, ativação de web collector ou uso de credenciais nesta auditoria.
