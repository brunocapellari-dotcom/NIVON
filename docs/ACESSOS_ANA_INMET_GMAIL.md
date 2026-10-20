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
