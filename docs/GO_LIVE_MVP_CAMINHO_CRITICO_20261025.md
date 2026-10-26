# NIVON — Caminho crítico de go-live por entrega operacional

**Corte:** 25/10/2026. **Status:** projeto ainda não homologado; este ramo é piloto de operação interna, não release de produção.

## Decisão de escopo para acelerar

Não condicionar o primeiro valor ao término de 14 frentes, 131 datasets, modelos avançados, AIS e todas as licenças. Liberar primeiro uma **versão interna reduzida e segura**, baseada em dados realmente observados. Todo módulo não homologado aparece como `INDISPONIVEL`, nunca com dados simulados tratados como atuais.

### Ordem de execução — primeiro produto usável

| Prioridade | Fatia operacional | Aceite e bloqueios |
|---|---|---|
| P0-A | **Banco Central PTAX USD real: coleta pontual de leitura + normalização + frescor + saída interna** | Este PR: read-only, 1 GET, sem persistência; testes E2E, CI com artefato de metadados (sem valores) |
| P0-B | **IBGE/PAM, CONAB safra, ANP diesel, MDIC/Comex oficiais em pipeline durável** | Conectores com amostra real, rights per operation, schemas, RAW SHA256, ingestão GCP, monitoramento e backfill |
| P0-C | **CEPEA e IMEA atualizados frequentemente** | Contratos de acesso, coletores autorizados, delta, vintages, frescor; histórico do Drive não vira valor atual |
| P0-D | **Persistência GCP, backup/restore, observabilidade, custos/segredos** | Identidade e serviços homologados em projeto existente, ingestão idempotente, DQ, backups restauráveis, orçamento efetivo |
| P0-E | **Primeiro painel interno com dados reais e lacunas explícitas** | Consulta atual, fonte, data/hora de corte, rótulo observado/estimado, notícias <=24h, sem falso dado atualizado |
| P1 | **Briefing NIVON diário e envio WhatsApp** | Fonte das notícias, 24h verificadas, direitos de redistribuição, opt-in destinatário, provedor/envio e entrega reais |
| P1/P2 | Marítimo/line-ups completos, tendências, forecasting, outros países | Adicionar após base confiável, validação point-in-time e gates quantitativos |

**Não trocar execução de fontes reais por síntese de notícias, testes de unidade ou artefatos sintéticos.** A próxima etapa deve executar B/C/D/E em blocos interdependentes. Trabalho técnico reversível anda sem novos comandos; intervenção humana só diante de autorização material, segredo, gasto ou merge/deploy irreversível.

## O que foi implementado neste PR

`src/nivon/piloto_ptax_readonly.py` implementa a primeira fatia de aquisição oficial sem criar dependências externas:

1. Recebe instante timezone-aware, cria plano determinístico para USD no período de até dez dias.
2. Faz **no máximo uma requisição HTTPS GET** ao host oficial `olinda.bcb.gov.br`, sem redirects ou URLs definidas pelo usuário, resposta JSON com MIME e limite de 256 KB.
3. Usa o normalizador `bcb_ptax.normalizar_ptax_odata` que já rejeita duplicações, datas incorretas, paginação incompleta, preço inválido e período incoerente. Não faz login nem contorna bloqueios.
4. Seleciona boletim mais recente realmente observado, reporta competência, referência, SHA256 da resposta efêmera, idade e estado de frescor. Recusa como valor atual observação com mais de 96 horas. Se não houver dia anterior, não inventa variação.
5. O terminal interno com `--mostrar-valores` exibe compra/venda e variação, somente ao operador. Por padrão a CLI **omite valores** e pode ser usada em CI pública para evidência de operação real sem publicar série financeira.
6. A operação **não persiste preços**, não ativa `BCB_PTAX` no catálogo, não atualiza GCP, não manda WhatsApp, não publica relatórios e não afirma homologação ou assinatura.

### Execução local (somente quando acesso e política estiverem aprovados)

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_piloto_ptax_readonly.py' -v

# Consulta oficial, JSON sem preços nos logs:
PYTHONPATH=src python -m nivon.piloto_ptax_readonly --consultar-bcb

# Visualização estritamente interna: evitar logs públicos e redirecionamentos:
PYTHONPATH=src python -m nivon.piloto_ptax_readonly --consultar-bcb --mostrar-valores
```

A CI própria testa ponta a ponta e faz um GET real somente na PR da branch autorizada; artefato do Actions é retido 3 dias e não inclui preço. Se a API estiver indisponível, o job falhará explicitamente: não falsificar sucesso ou migrar silenciosamente para fixture.

## Limites e decisão de go-live

**Este PR não habilita go-live por si só.** Banco Central publicamente acessível não implica licença de armazenamento/redistribuição concedida à plataforma. A maturidade de código não substitui persistência GCP, monitoramento 24h, backup e segurança, nem repositório integrador consolidado. `status=BLOQUEADO_PARA_GO_LIVE` permanece enquanto qualquer gate crítico estiver pendente.

**Release e integração:** proposta pequena e isolada sobre a `main` pelo PR #317. A PR #305 mantém o trabalho original como referência, mas não precisa ter sua árvore divergente mesclada. Não executar merge, deploy ou habilitar cobrança sem os gates correspondentes; Vercel está fora do NIVON. Usar Google Cloud com componentes portáteis somente após revisão da configuração existente e autorização aplicável. Nenhuma credencial no GitHub público.


## Portabilidade de integração em `main`

Este pacote foi reaproveitado numa branch mínima iniciada diretamente em `main` para não exigir a fusão de frentes antigas. O piloto é **somente leitura / localhost**. O Cloud Run privado já existente na `main` continua sendo o único produto web de produção candidato para go-live, após IAM e custo aprovados. Não publicar este servidor localhost como serviço sem autenticação.
