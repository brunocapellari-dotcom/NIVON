# NIVON — ANA e INMET: credenciais localizadas no Gmail, sem replicação de segredos

**Data-base:** 19/10/2026. **Natureza:** inventário de evidências e código de aquisição segura; não é prova de coleta já executada.

## Gmail (consulta autorizada pelo usuário)

- ANA: foi encontrada mensagem oficial encaminhada de cadastramento de usuário, datada de julho de 2026. Contém identificador e senha de acesso à plataforma integrada. **Segredo não copiado para o repositório.** A mensagem é evidência de emissão, mas a autenticação na nova API HidroWebService ainda precisa ser testada.
- INMET: encontrada confirmação de processamento de solicitação BDMEP em agosto de 2026. Contém endereço individual para ZIP de dados. Endereço age como credencial/bearer, deve permanecer somente em armazenamento privado. **Nenhum endereço individual foi commitado.**
- Outra chave recebida no Gmail é para API USDA (confirmar escopo por serviço antes de utilizar); **não é** token da ANA.

## Contratos oficiais

Manual ANA de **20/02/2026**:
https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf/@@download/file

1. Requisição GET `/hidrowebservice/EstacoesTelemetricas/OAUth/v1` com headers `Identificador` e `Senha` (nunca query string).
2. Ler `items.tokenautenticacao`, válido por até 60 minutos. Usar token em `Authorization: Bearer ...`; expirar em 55 minutos por margem. Evitar autenticações frequentes.
3. Consulta telemétrica adotada por código de estação, `DataDaBusca`, `TipoFiltroData` e `RangeIntervaloDeBusca`; validar contrato exato em resposta autorizada, inclusive versão de parâmetros.
4. Payload de medição contém `codigoestacao`, `Data_Hora_Medicao`, `Chuva_Adotada`, `Cota_Adotada`, `Vazao_Adotada` e respectivas classes QC: 0=aceito, 1=suspeito, 2=ruim. Sem fuso explícito no exemplo oficial; timezone deve ser conhecido por estação.
5. A série telemétrica possui frequência intradiária. Não pode ser registrada como precipitação diária automaticamente, nem ser usada sem QC.

O código `src/nivon/ana_hidrowebservice.py` encapsula autenticação, validação, controle de token e normalização com testes sintéticos. Somente executa HTTP quando chamado explicitamente com `habilitar_rede=True`. **Não existe execução habilitada em CI ou deploy**.

## BDMEP do Gmail

`src/nivon/inmet_bdmep.py` recebe o link privado exclusivamente por `NIVON_INMET_BDMEP_URL` em secret vault/ambiente do executor. Impõe domínio oficial, HTTPS, sem redirects, tamanho máximo, hash, pasta privada, anti ZIP-slip/zip-bomb e proíbe sobrescrita automática. O ZIP não é incorporado ao Git.

Tentativa de adquirir a URL via ferramenta de download local nesta sessão não ocorreu: a ferramenta de download exige URL previamente acessível por fonte suportada. Uma tentativa direta por HTTPS falhou por DNS neste ambiente. **Logo, conteúdo e validade desse link ainda não foram conferidos.** Links BDMEP podem expirar; se não funcionar, uma nova requisição autorizada ao órgão será necessária.

## Escopo de autorização

O usuário autorizou uso interno dos dados recebidos. Isso não implica automaticamente direito de redistribuir dumps/arquivos de terceiros, compartilhá-los em artefatos CI, publicar tokens, executar coletas ilimitadas ou ativar funcionalidades comerciais antes de validar condições específicas. Registrar direitos por operação separadamente.

## Infraestrutura pendente

1. Disponibilizar as credenciais recebidas por canal secreto do próprio ambiente de execução em nuvem; nunca em arquivos versionados, prompts ou logs.
2. Validar uma autenticação real ANA, a lista de permissões e um único exemplo de estação antes de completar o backfill.
3. Download BDMEP por executor com egress HTTPS, conferir ZIP real, layouts, timezone e licença; preservar o arquivo em storage privado.
4. Usar coleta incremental, SHA-256, qualidade, idempotência, backtest as-of e backups. Não atribuir qualidade observada a saída não homologada.
5. Não fazer merge, deploy ou contratação de serviço sem homologação.

**Resultado:** credenciais encontradas, contratos implementados e teste offline; autenticação real ANA e dados brutos INMET continuam não verificados neste ambiente.

## Revalidação dos três e-mails — 21/10/2026

A consulta à conta Gmail conectada confirmou **três mensagens**, sem copiar conteúdo sensível para esta documentação:

| Fonte | Mensagem/recebimento | Evidência de acesso | Estado operacional |
|---|---|---|---|
| USDA | `Fw: Your API key`; encaminhada em 19/08/2026, original de 17/07/2026, remetente `noreply@api.data.gov` | Chave da infraestrutura API.Data.gov recebida | Serviço e escopo USDA ainda não testados; não confundir uma chave genérica da plataforma com uma API USDA homologada |
| ANA | `Fw: Cadastramento de Usuário`; encaminhada em 19/08/2026, original de 17/07/2026, remetente `nao-responda@ana.gov.br` | Identificador e senha foram emitidos | Login real e token HidroWebService ainda não testados |
| INMET | `Fwd: Processamento Concluído - BDMEP - INMET`; recebida em 25/08/2026, original de 25/08/2026, remetente `bdmep@inmet.gov.br` | Requisição BDMEP concluída; link privado para baixar dados | Link e ZIP ainda não verificados; reemissão pode ser necessária se expirou |

O NIVON utiliza **exclusivamente finalidade não comercial**; isso não implica licença irrestrita de armazenamento ou redistribuição. Não se alteraram automaticamente os estados de `collection_authorized`, `runtime_enabled` ou `scheduled_enabled`.

### Contrato de transferência segura ao executor

- ANA: o adaptador já espera `NIVON_ANA_IDENTIFICADOR` e `NIVON_ANA_SENHA` fornecidos por secret vault/ambiente privado.
- INMET: o adaptador já espera `NIVON_INMET_BDMEP_URL` fornecida exclusivamente por secret vault/ambiente privado; a URL individual deve ser tratada como segredo.
- USDA: antes de definir uma variável/integração, identificar o **serviço exato** compatível com a chave API.Data.gov e validar autenticação, resposta, limite e termos de acesso sem registrar a chave. Não usar a chave em logs, PR, URLs públicas ou arquivos de teste.
- Não extrair senhas ou chaves do Gmail para o GitHub público, CI, variáveis de pull request, comentários, mensagens ou qualquer artefato versionado.

### Próximos testes de acesso (ainda não realizados)

1. Testar o serviço USDA específico por executor autorizado com segredo protegido e resposta sanitizada, registrando somente status, schema e proveniência.
2. Autenticar a ANA uma vez em executor privado, com headers conforme manual; validar permissão para uma estação, timestamps e qualidade das medições.
3. Verificar se o link BDMEP está válido; se sim, arquivar ZIP original em storage privado, calcular SHA-256 e homologar layout. Se expirou, renovar pela via oficial.
4. Executar ingestão histórica incremental e verificar direitos de coleta, armazenamento, processamento e exibição por dataset, sempre com fonte, publicação, referência e coleta.
