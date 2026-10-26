# NIVON — Portal interno: primeiro vertical slice de go-live

Há consultas reais ANTT/SIADE e marítimas no BigQuery, porém o NIVON não tinha interface web.
Esta entrega cria servidor WSGI sem dependências extras, interface responsiva e contrato de snapshot somente leitura.

## Executar internamente

1. Produzir um readback autorizado usando scripts/rodar_painel_operacional.py com --executar-bigquery e WIF conforme workflows existentes. Não incluir dados restritos em PR público.
2. Gerar snapshot privado com: python scripts/gerar_painel_interno.py --entrada /privado/readback.json --saida /privado/painel.json --as-of 2026-10-25T23:00:00Z. O instante --as-of deve coincidir exatamente com o do readback.
3. Executar: python -m nivon.portal_interno --snapshot /privado/painel.json --host 127.0.0.1 --port 8080.
4. Abrir http://127.0.0.1:8080/ . Rotas: /healthz (processo), /readyz (snapshot de ate 24h), /api/v1/painel (somente leitura).

## Regras metodológicas

- Indicadores somente de SIADE ferroviário e revisões line-up/PortWatch que o backend já validou. Mercado físico e clima não serão inventados.
- Todo resultado fica em INTERNO_SHADOW e publicavel=false; nenhum preço restrito vira dado público automaticamente.
- IDs de programação não comprovam navios operados nem cargas realizadas; SIADE não comprova transbordo ou vintage PIT histórico.
- Ausência não vira zero, leitura de fonte sem evidence hashes é rejeitada, erros mostram painel indisponível.
- A interface tem CSP, não permite iframe, serve JSON no-store e usa textContent para exibir rótulos.
- O servidor escuta apenas 127.0.0.1 por padrão. Bind 0.0.0.0 exige variável NIVON_PORTAL_PRIVATE_INGRESS_APPROVED=true; esta variável isoladamente NÃO implementa autenticação ou isolamento.
- Nenhuma consulta BigQuery é feita por usuário do portal, evitando custo por clique.

## Gates restantes para o go-live externo

- Cloud Run privado com IAM e ingresso restrito, custo aprovado e orçamento; nunca permitir acesso público a séries restritas.
- Atualizar os snapshots em serviço autorizado, demonstrar consulta+persistência+visualização e alertas de falhas em dois ciclos reais.
- Habilitar CEPEA, IMEA e CONAB separadamente conforme licença, proveniência e qualidade; sem extrapolar feeds Neon para BigQuery.
- Não criar tabelas/datasets nem ativar agendamento sem o gate econômico e aprovação correspondente.

## CI

Workflow portal-interno-ci.yml testa contrato, snapshot atomico, UI servida no pacote, headers e bloqueios usando somente fixtures sintéticas.
CI não comprova autenticação real, permissão de licença, aplicação no Cloud Run ou disponibilidade pública.
