# NIVON — runtime autenticado e recuperação operacional

Data: 20/10/2026. Estado: código em PR draft, sem serviço implantado.

## 1. Hermes ↔ NIVON

Arquivo: src/nivon/hermes_gateway_wsgi.py. Expõe apenas o endpoint
POST /v1/nivon/query. Nenhuma rota de execução, publicação, alteração
de fonte ou WhatsApp está disponível nesse gateway.

O gateway WSGI **não inicia um servidor** por conta própria. É necessário
um serviço HTTPS restrito na nuvem e injeção de:
- audience OIDC exata, definida pelo operador;
- allowlist explícita de service-account subjects;
- adaptador NIVON instanciado em nome da identidade autenticada;
- verificadora de assinatura criptográfica/expiração/emissor/audiência.

A implementação padrão verificar_oidc_google usa a biblioteca google-auth,
do extra opcional NIVON[auth]. Requer obter certificados do Google por
uma via permitida, com TLS e política de egress. Importar o pacote ou
executar testes com verificador simulado não autentica serviços reais.

A interface valida emissor Google, audience e subject mesmo após o verificador;
não confia em email, role, escopo, SQL, URLs ou permissões enviadas no corpo.
Recebe no máximo 64KiB de JSON e limita a resposta a 128KiB, sem logs de
token nem CORS permissivo. Erros não revelam caminhos de arquivos, credenciais
ou conteúdo da fonte.

IMPORTANTE: configurar e testar a verificação REAL de token e o ingresso
HTTPS antes de homologar. Exigir bloqueio externo por IP/ingress, quotas,
rate limit, observabilidade e gerenciamento de secrets. Sem isso, NÃO EXPOR
a aplicação à internet. Os testes injetam mock de verificador e não podem
provar autenticidade de credenciais externas.

## 2. Pacote de recuperação

Arquivos: src/nivon/bundle_persistencia.py e tests/test_bundle_persistencia.py.
Salva snapshots dos três SQLite CONAB, portos, outbox, com manifesto JSON,
SHA-256, data, integridade de tabelas/chaves, proteção contra overwrite e
permissões privadas. A restauração ocorre em diretório novo, com cutover manual.

O chamador DEVE bloquear escritores externos durante todo o snapshot.
O flag escritores_pausados=True expressa uma condição operativa, mas
NÃO implementa lock distribuído entre servidores. Os três backups são
coerentes individualmente, mas NÃO formam uma transação global atômica.
Reconciliar referências cruzadas e eventos de entrega antes do cutover.

Os arquivos gerados são LOCAIS. Backup local ou filesystem persistente
não equivale a cópia remota durável, redundante e isolada; deve haver
replicação autorizada para um destino controlado, ensaio periódico de
restauração, política de retenção e criptografia em repouso. A rotina
de recuperação não apaga bases em produção nem faz switchover automático.

## 3. Passos de homologação

1. Aprovar ambiente de execução permanente (custo conhecido = 0 ou autorizado).
2. Provisionar diretórios privados 0700 em volume confiável, separado de runners.
3. Configurar backup remoto autenticado, criptografia, retenção e recuperação.
4. Testar token OIDC REAL com audience, issuer, subject e exp corretos.
5. Conectar Hermes via rede interna apenas às funções read-only.
6. Verificar CONAB, portos, bolsas, câmbio, line-up, direito de publicação
   e confiança temporal com amostras REAIS em dias distintos.
7. Submeter modelos a backtest vintaged e auditoria independente.
8. Configurar Meta WhatsApp opt-in, templates, custo e entrega confirmada.
9. Exercitar E2E real sob observação, antes de abrir os gates.

Os artefatos desta rodada NÃO enviam WhatsApp, não ativam agendamento,
não fazem coleta real, não instalam cloud, não abrem portas e não cobram.
