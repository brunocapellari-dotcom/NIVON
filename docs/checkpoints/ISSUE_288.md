# Checkpoint #288 — pré-voo GCP privado

Branch: `codex/288-gcp-readiness`, baseada em `97f032d` da main.

Entrega: `python -B -m nivon.terminal_preflight` gera JSON com gates locais,
metadados mockáveis, estado privado de IAM e `ready_for_deploy` fail-closed.
Reutiliza os recursos/verificações do deploy existente e constantes do terminal.
Não cria recursos, executa SQL, faz deploy, imprime tokens ou erros externos.

Validação local: 10 novos testes de configuração ausente, IAM, billing, recursos,
credencial ausente, sucesso simulado, privacidade e erro sanitizado. Suíte completa:
764 testes, sem falhas; 2 ignorados opcionais Parquet. `git diff --check` aprovado.
CI novo usa apenas doubles, sem autenticação Google.

Execução no ambiente atual: `CONFIGURACAO_PENDENTE`, `ready_for_deploy=false`,
zero consultas SQL e zero gravações. Há binding de credencial Google no ambiente,
mas variáveis NIVON e gates não estão configurados; gcloud não foi encontrado.
Não é evidência de falta de acesso da credencial nem de recursos inexistentes.
Nenhuma leitura GCP real foi feita; nenhum gate foi definido como verdadeiro.

Gates de IAM/custo/deploy exigem decisão específica; o novo
`NIVON_TERMINAL_IAM_REVIEWED` registra revisão humana do IAM efetivo que políticas
parciais não comprovam. O diagnóstico não muda o script de deploy existente.

API GitHub permanece bloqueada com `Forbidden`; páginas públicas/Git funcionam.
PR ainda não criada, CI remoto não confirmado. Próximo bloco: #289, contratos
ANTT/SIADE, cache, proveniência e fonte defasada; issue pública consultada aberta.
PRs #276/#283 foram inspecionadas e devem ser preservadas, sem duplicar servidor.
