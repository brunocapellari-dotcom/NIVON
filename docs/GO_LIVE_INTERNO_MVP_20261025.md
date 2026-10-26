# NIVON — corte de escopo para o primeiro go-live interno

Estado: código de interface MVP; **não significa serviço implantado nem produto completo**.

## Produto da primeira liberação
- Tela única NIVON em português, identidade verde agro, sem biblioteca externa.
- **Ferrovia:** visão de polos de MT e TU por competência, usando a view real ANTT/SIADE. A view é revisão atual; NÃO recria versões históricas.
- **Marítimo:** passagens PortWatch FMI, 30 dias, trânsitos AIS reportados e **volume ESTIMADO pelo modelo**. Não é carga embarcada, nem line-up realizado, nem fila AIS verificada.
- Dados só aparecem se duas fontes reais do BigQuery forem consultadas com sucesso. Caso contrário, status explícito de dados parciais ou indisponíveis. Não há números estáticos ou sintéticos no painel.
- São duas consultas limitadas a 50 MB faturáveis cada, até 400 observações por fonte, somente após aprovação explícita.

## Acesso
Interface HTML/CSS/JS empacotada no Python. Token de acesso de alta entropia fornecido pelo usuário no navegador **apenas na memória JS**, não armazenado em localStorage/cookies. O servidor compara SHA-256 em tempo constante. O valor esperado em `NIVON_MVP_TOKEN_SHA256` é um hash, não a senha.

A API `/api/v1/resumo` só executa se:
- token Bearer válido com mínimo 24 caracteres;
- `NIVON_MVP_BQ_READ_APPROVED=true` explicitamente aprovado;
- `NIVON_BQ_PROJECT` e `NIVON_BQ_DATASET` definidos e ADC com permissão de leitura;
- parâmetros `mes` e `passagem` dentro da lista permitida;
- consulta histórica respeitar cortes, fonte e controles de custo dos leitores ANTT/PortWatch.

`/healthz` testa apenas processo, não a saúde dos dados. **Não usar retorno 200 do healthcheck para afirmar go-live.**

## Rodar desenvolvimento (localhost, sem Cloud)
```bash
python -m pip install -e '.[gcp,mvp]'
python -m nivon.terminal_mvp
```
Acesso local: http://127.0.0.1:8080. Nenhuma consulta BigQuery sem configuração de token e flag financeira. A tela não depende de JavaScript de terceiros.

## Empacotamento
```bash
docker build -f infra/google_cloud/Dockerfile.terminal_mvp -t nivon-terminal .
```
Imagem sem chave privada, usuário não-root. Teste de build Docker ocorre no GitHub Actions; **nenhum push/deploy é executado pelo CI**.

## Pré-condições para Cloud Run privado
1. Confirmar custo máximo e alertas de orçamento para Cloud Run, Artifact Registry e BigQuery. Serviços pagos ou habilitação de APIs exigem autorização específica.
2. Confirmar projeto `nivon-data`, dataset `nivon_raw`, view `vw_antt_ferrovia_od_atual` e tabelas `maritimo_fluxos_passagens`; não depende das duas tabelas agrícolas ausentes.
3. Confirmar runtime service account **somente leitura** do dataset e permissão BigQuery jobs (consultas podem ser faturadas).
4. Implantar Cloud Run com `--no-allow-unauthenticated`, sem Scheduler, sem tornar a URL pública. Usar conta administradora/deploy existente e invocação IAM aprovada.
5. Injetar `NIVON_MVP_TOKEN_SHA256` em variável protegida, definir o gate `NIVON_MVP_BQ_READ_APPROVED` após autorização financeira. Nunca imprimir a credencial em logs nem colocar no repositório.
6. Testar /healthz, negar API sem token, executar query real limitada e comparar proveniência com BigQuery; confirmar ausências e períodos sem simular zeros.
7. Acesso via proxy IAM ou solução de identidade corporativa existente; **um endereço Cloud Run privado não equivale a login web direto**. Não torná-lo público só para facilitar acesso.

## Escopo pós-MVP
CEPEA, IMEA, CONAB, safra argentina, clima, fretes WhatsApp, CBOT, tendência quantitativa, AIS/ETA e histórico comercial ampliado entram somente após fontes/licenças/integrações efetivamente homologadas. Não atrasam o teste técnico da interface inicial, nem são anunciados como funcionalidades prontas.

## Critério de aceite
- Build Docker CI verde, testes de auth/erro/validação verdes.
- Deploy privado efetivo confirmado por identidade autorizada.
- Pelo menos uma leitura de ANTT e PortWatch com fonte e janela verificadas; vazio permanece vazio.
- Evidência de custo controlado, freshness e proveniência no mesmo ambiente.
- **Somente depois disso** pode-se anunciar `GO-LIVE INTERNO LIMITADO`. O produto integral Bloomberg do Agro permanece evolução posterior.
