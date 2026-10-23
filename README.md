# NIVON — Inteligência de Mercado, Indústria e Logística

Plataforma independente de análise agroindustrial, de granéis e de logística do Brasil, com foco inicial em Mato Grosso.

## Estado

**Implementação inicial em andamento; NÃO HOMOLOGADO para uso operacional.**

Auditorias de 16/10/2026: **GO COM CONDIÇÕES para implementação**, não para go-live. Nenhuma saída sintética pode ser apresentada como observação real.

## Diretrizes vinculantes

- Somente código, documentação e dados sintéticos publicáveis neste repositório público. **Nunca** credenciais, arquivos privados ou séries de terceiros sem direito de redistribuição.
- Custos de implantação e operação: objetivo **R$ 0**; nenhuma contratação ou deploy sem autorização.
- Fontes de dados: permissões separadas por operação; direitos restritos ou desconhecidos implicam **bloqueio por padrão**.
- Dados OBSERVADOS, INFORMADOS, ESTIMADOS, INFERIDOS e PROJETADOS jamais são intercambiáveis.
- Dados ausentes são ausentes, não zeros imputados.
- Não misturar ano civil e safra sem mapeamento explícito; preservar competência, referência, publicação e coleta.
- CEPEA: 440 L etanol, 331 kg DDG, 20,4 L óleo por t de milho são **parâmetros de análise de margem**, não um trio automaticamente válido para balanço físico.
- ANTT/MDF-e: recortes por NCM são amostrais, e municípios com terminal e fábrica são AMBÍGUOS; jamais publicar volume amostral como total observado.
- Line-up PROGRAMADO não é realizado; aquisição de página não é operação portuária concluída.
- Reuso de projetos antigos exige proveniência/licença/testes e não pode forçar dependências em BigQuery, Cloud Run, Hermes ou Holding.

## Desenvolvimento

O trabalho de implementação inicial ficará em uma branch e em PR para revisão. Os testes locais usam somente fixtures sintéticas. A aprovação dos auditores não equivale à homologação operacional.

## Licenciamento do código

**Ainda não foi concedida uma licença aberta para este código.** A visibilidade pública do repositório não deve ser interpretada como permissão genérica de cópia ou sublicenciamento. Componentes de terceiros só serão incorporados após exame das respectivas licenças.

## Desenvolvimento autônomo local (Claude Code + Codex)

A PR de cooperação fornece o comando Claude Code \`/nivon-autonomo\` e o script local \`bash scripts/nivon-autonomo.sh\`.
Ambos operam com **tarefas delimitadas**, worktrees separadas, testes offline, limites de duração e commits **somente locais**. Não fazem deploy, push ou merge automático. A operação real requer um host com as duas CLIs autenticadas; não está ativada pelo simples merge dos arquivos.

Instruções: [docs/AUTONOMIA_CONTINUA_NIVON.md](docs/AUTONOMIA_CONTINUA_NIVON.md).

Diagnóstico sem usar tokens: `bash scripts/nivon-autonomo.sh doctor`. Planejamento sem modificar fila: `bash scripts/nivon-autonomo.sh plan`. Qualidade estrutural diurna: `bash scripts/nivon-autonomo.sh quality`.

**Janela autônoma:** somente 20h–6h no horário de Cuiabá, sem agendamento automático; `night-status` exibe o próximo intervalo. Para ferramentas opcionais de código e capacidade independente via modelos locais, consultar [Catálogo de engenharia](docs/FERRAMENTAS_ENGENHARIA_20261023.md). Testes gerados exigem contêiner Docker local sem rede; não há execução do host autorizada por esta PR.

A execução autônoma acumula entregas em `autonomo/integracao` **local**, com cherry-pick serializado e nova rodada de testes offline. Não publica nem mescla na `main` automaticamente.

**Compatibilidade Claude OAuth:** o executor usa `--restricted --safe-mode`, não `--bare`, que não recupera a sessão de assinatura. O `doctor` rejeita credenciais de API potencialmente faturadas. Testes no Docker mantêm o checkout montado somente para leitura. Para testes Parquet adicionados na `main`, o ambiente isolado precisa da dependência PyArrow previamente instalada.

**Dueto de desenvolvimento:** `bash scripts/nivon-autonomo.sh dueto` (estado local em JSON) e `bash scripts/nivon-autonomo.sh painel` (HTML privado, sem rede). [Procedimento de operação](docs/DUETO_DESENVOLVIMENTO_NIVON.md).

Painel local opcional com atualização a cada 15 segundos e duração de até 120 minutos: `bash scripts/nivon-autonomo.sh painel-live`. Ele consulta só o SQLite, sem chamadas aos agentes e sem servidor.
