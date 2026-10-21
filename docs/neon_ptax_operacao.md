# NIVON — PTAX oficial: banco cloud e execução agendada

## Estado verificável — 21/10/2026

**Coleta diária, recuperação histórica horária e armazenamento persistente ATIVOS apenas para PTAX USD/EUR**, na plataforma Neon Free. Isso **não** homologa os 42 widgets do Notícias Agrícolas e **não** significa que os motores de soja, milho, fretes e tendências estão conectados.

| Item | Estado |
|---|---|
| Projeto Neon operacional | NIVON-PTAX-OPERACIONAL, id \`divine-lab-03469752\` |
| Região | AWS Virginia (\`aws-us-east-1\`), pois Neon Functions não está disponível em São Paulo nesta data |
| Banco | \`nivon\`, Postgres 17, schema público com prefixo \`nivon_ptax_\` |
| Neon Function | \`ptaxcollector\` no branch \`br-twilight-cell-b77ukd6x\` |
| Agendamento diário | Trigger principal: 30 1 * * 2-6 UTC |
| Backfill horário | Trigger /backfill: 5 * * * * UTC; uma janela de 31 dias por moeda |
| Horário esperado | 01:30 UTC terça–sábado (~22:30 Brasília segunda–sexta) |
| Primeira execução nativa real | 21/10/2026 17:19 UTC; sucesso, quatro janelas e 174 registros na primeira execução |
| Registros em Postgres | **48 USD + 238 EUR = 286**, de seis janelas confirmadas no banco em 21/10/2026 |
| Histórico integral 2020–2026 | **Ainda incompleto**. Rotina horária de backfill ativo (uma janela por moeda por hora), além de backfill na rotina diária |
| Retenção | Persiste além do ciclo do GitHub Actions; limites Free de Neon se aplicam |
| Custos | Organização Neon no plano Free; nenhuma contratação ou upgrade |

**Importante:** há outro projeto \`NIVON-PTAX\`, id \`bitter-sky-19426037\`, na região São Paulo. Ele foi provisionado antes da verificação de disponibilidade regional das Functions, está sem cotações gravadas e **não está conectado ao agendador**. Preservado, não excluir automaticamente.

## Provas de persistência

Consulta após trigger real:

\`\`\`sql
SELECT currency, count(*), min(reference_date), max(reference_date)
FROM public.nivon_ptax_quotes GROUP BY currency ORDER BY currency;
-- EUR 238; USD 48

SELECT job_type,currency,window_start,window_end,status,fetched,inserted
FROM public.nivon_ptax_runs ORDER BY id;
-- DAILY USD 7; DAILY EUR 35; BACKFILL USD 22+19; BACKFILL EUR 110+93

SELECT count(*) FROM public.nivon_ptax_checkpoints;
-- 6
\`\`\`

O Neon Trigger executou a função sem credencial fornecida ao GitHub. A URL pública **rejeitou** chamada de teste com cabeçalho falsificado \`x-neon-trigger-invocation-id\` (HTTP 403): não utilizar calls diretas com esse cabeçalho como se fossem invocações autênticas da plataforma.

## Proveniência e semântica

- O coletor usa somente a API OData oficial do Banco Central, independente do widget 232 Notícias Agrícolas.
- USD usa \`CotacaoDolarPeriodo\` sem \`tipoBoletim\`; categoria técnica \`COTACAO_DOLAR_DIARIA\` não deve ser apresentada como tipo publicado.
- EUR usa \`CotacaoMoedaPeriodo\` com tipos de boletim originais, podendo produzir múltiplos registros por dia.
- A data de cotação é mantida sem atribuição de um timezone que a API não informa. \`published_at\` é NULL, nunca extrapolado da data de coleta.
- Valores de compra/venda são distintos; série etiquetada \`INFORMADO\` e fonte original Banco Central/PTAX, licença ODbL.
- Deduplicação por moeda, data, horário, tipo, preço de compra e venda; revisões de valores permanecem como versões distintas.
- Checkpoint de período já concluído não é inferência de observação para cada dia do intervalo.
- Falha HTTP, inconsistência ou paginação da API gera erro; **nunca** publicar como preço atual valores defasados.

## Infraestrutura e limites

- A função Neon recebe \`DATABASE_URL\` internamente; **nenhuma senha aparece no repositório público**.
- O bundle gerado pela GitHub Action a partir de \`functions/ptax_neon/index.mjs\` é implantado na função Neon; a versão no runtime precisa ser reconciliada quando o código for atualizado.
- O cron do GitHub Actions \`ptax-monitoramento.yml\` foi retirado para evitar agenda duplicada; workflow está disponível somente para diagnóstico manual.
- Free tem cotas de armazenamento, CPU, invocações e tráfego; ausência de cobrança não garante execução ilimitada. Monitorar consumo e disponibilidade periodicamente.
- **Não há backup externo nem alerta de falha configurados**, e ainda não se comprovou execução em múltiplos dias consecutivos. Essas validações são pendências para declarar o sistema inteiramente operacional de ponta a ponta.
- Os arquivos \`database/neon_ptax_schema.sql\` são o schema reproduzível; nenhuma série real deve ser enviada ao GitHub.

## Pendências reais

1. Confirmar execução de 22/10 e em dias seguintes, com incremento de checkpoints e idade correta da referência.
2. Planejar backup e restauração em armazenamento privado permitido, sem contratação, para proteção além do recurso de restauração temporária do Neon.
3. Projetar indicadores de freshness e alertas de atraso com calendário do Banco Central e revisão de dados.
4. Verificar a conclusão progressiva de todas as janelas de 2020–2026 sem ultrapassar cotas, limites de API e sem declarar cobertura completa antes de auditoria.
5. Validar termos e APIs primárias de CEPEA/IMEA; nenhuma coleta desses dados foi habilitada.
6. Integrar as séries validadas de PTAX à camada do motor de tendências/briefing, nunca confundir dados de referência antigos com atualizados.

Códigos e evidências: [PR #58](https://github.com/brunocapellari-dotcom/NIVON/pull/58), [issue #59](https://github.com/brunocapellari-dotcom/NIVON/issues/59).
