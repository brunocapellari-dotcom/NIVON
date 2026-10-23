# Pipeline JSON estruturado PTAX + IBGE PAM — OFFLINE

Implementação `src/nivon/pipeline_api_dados.py` liga normalizadores existentes (`bcb_ptax`, `sidra_pam`) ao `registro_snapshots` e guarda somente **observações canônicas** em `nivon_observacoes_api`, não arquivos originais. Ingestão requer bytes explícitos e esquema reconhecido, SHA-256, hora de coleta e autorização de COLETA + ARMAZENAMENTO quando classificados como reais. O padrão são **fixtures sintéticas**.

Registros usam chave estável por observação, idempotência por SHA e versão distinta quando um mesmo período é revisado. Consultas `observar_asof_coleta` só oferecem visão do que já havia sido coletado. Como os endpoints não comprovam `publicacao` em cada dado, **NÃO** são consideradas reconstrução por data oficial de publicação nem backtesting sem look-ahead garantido. Sintéticos são excluídos por padrão. `publicacao_comercial_permitida=False` permanece incondicional.

Falha no meio da persistência: o ledger de proveniência pode conservar um snapshot sem linhas, e uma reingestão é idempotente e reconstitui as observações. O registro não deve ser declarado sincronizado com fonte externa sem conferir contagens. Backup local é possível via `backup_sqlite`, mas ainda é necessário backup remoto durável e restore homologado para produção.

Este módulo NÃO realiza HTTP, não habilita rotas, não agenda e não acessa credenciais. O próximo passo é um runner oficial com gate de direitos e parser real homologado; não deve haver execução automática antes disso.
