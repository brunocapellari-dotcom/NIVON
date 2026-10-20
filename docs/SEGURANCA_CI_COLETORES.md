# NIVON — execução segura do CI de coletores

Após a validação inicial dos endpoints e esquemas, as tarefas que acessam dados reais no workflow `.github/workflows/testes.yml` são **`workflow_dispatch` somente**, para evitar download externo em cada PR ou PR de terceiros.

- Automático em PR: compilação, suíte unittest offline/sintética, validação do catálogo e contratos, gates de acesso, verificações determinísticas e módulos da plataforma que não necessitem de dados reais.
- Manual (opt-in): inspeção de MAPA/SIPEAGRO, CONAB XLS, ANTT ferroviária e ANP diesel; inspeção ANTT CSV continua bloqueada por WAF até método autorizado.
- Os jobs manuais não concedem, por si, autorização legal de armazenamento ou redistribuição. Documentar o responsável e o motivo antes de executá-los.
- `workflow_dispatch` não é cron em nuvem, nem go-live. O fluxo ainda precisa de direitos por operação, dados completos reais homologados e backup remoto durável com restore.

Para custo mínimo, evitar automações de aquisição em CI e inspeções repetidas sem mudança de contrato. Nenhum serviço pago é habilitado por esta alteração.
