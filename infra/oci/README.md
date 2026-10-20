# Candidato Oracle Cloud — NIVON

**Status: DOCUMENTADO, não implantado.** Não há conexão autenticada nesta
revisão com o OCI, nem identificação da região principal, recursos existentes,
quotas disponíveis, faturamento, autorização para criar VM ou IP.

## Dimensionamento inicial conservador

`infra/oci/capacidade-candidata.v1.json` registra somente hipótese
de implantação (não pedido de provisionamento):

| Recurso | Proposta NIVON | Referência pública de quota |
|---|---:|---:|
| OCI Ampere A1 | 1 OCPU | 2 OCPUs **na tenancy inteira** |
| RAM | 4 GB | 12 GB **na tenancy inteira** |
| Boot volume | 50 GB | 200 GB boot+block **na tenancy inteira** |
| Bloco adicional | 0 GB | dentro dos mesmos 200 GB |
| Object Storage | 5 GB de planejamento | 20 GB agregados, conforme condições do nível gratuito |
| Mês de cálculo | 744 h (31 dias) | até 1500 OCPU-h e 9000 GB-h por mês |
| Endereço público/portas abertas | nenhum | exposição somente após desenho de IAM/TLS |

Referência oficial consultada em 20/10/2026:
https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

O número para 31 dias é **limite superior de uma VM contínua**, não uma
medição de gasto, uma promessa de operação 24/7 ou prova de capacidade.
O Always Free A1 é elegível apenas na região home e poderá estar sem
capacidade disponível; VM inativa pode ser retomada/reclamada conforme regras
do provedor. Não aumentar carga só para evitar recuperação por inatividade.

## Validação somente offline

```sh
PYTHONPATH=src python -m nivon.infra_oci_quota
PYTHONPATH=src python -m nivon.infra_oci_quota --require-account-proof
PYTHONPATH=src python -m nivon.infra_health --require-operational
```

- Primeiro comando sai 0 se a **proposta isolada** cabe nas referências.
- Segundo e terceiro retornam 3 porque a conta e o ambiente não estão
  homologados. Essa reprovação é intencional. Nenhum chama APIs da Oracle.

## Evidências externas ainda necessárias

Antes de propor qualquer criação de recursos, verificar com acesso legítimo
à Console OCI ou API oficial, sem colar credenciais em chat/repositório:

1. Tenancy, região home e modalidade da conta; escopo de gastos existente.
2. Todas as VMs A1, OCPUs/RAM reservadas, volumes de boot/bloco, backups,
   objetos e quotas **somadas aos demais projetos da Holding**.
3. Elegibilidade e capacidade de A1 na região, imagens Ubuntu/Oracle Linux,
   opções de rede privada e condições de disponibilidade.
4. Previsão de retenção dos dados: backfill, crescimento diário e limites
   reais de object storage, API requests e egress.
5. Política de segregação/IAM/segredos, acesso administrativo e backup
   criptografado fora da VM, com restauração numa instância separada.
6. Regra explícita de não instalar componentes pagos ou fazer upgrade
   automático quando uma quota gratuita se esgotar.

Registre apenas metadados minimizados de evidência (datas, totais de
capacidade, políticas), jamais tokens, URLs assinadas, OCIDs privados
desnecessários ou material comercial restrito.

## Implantação posterior

A proposta foi intencionalmente entregue **sem Terraform apply,
OCI Resource Manager, cloud-init, credenciais, autorização de custo,
imagem de serviço exposta ou timer de coleta**. Primeiro é necessário
provar quotas e liberar os gates de persistência, segurança e recuperação.

O pacote pode ser adaptado a outra nuvem ou ao ambiente OCI já existente
sem replicar bancos, serviços da Holding ou do WhatsApp AI.

## Inventário automatizado (futuro e somente leitura)

Ferramentas de referência: [Oracle OCI CLI](https://github.com/oracle/oci-cli),
[OpenTofu](https://github.com/opentofu/opentofu) e
[Oracle Terraform Provider](https://github.com/oracle/terraform-provider-oci).
Nenhuma está instalada ou configurada por esta entrega.
A futura coleta autenticada de metadados da tenancy deverá usar permissões
mínimas de leitura, sem guardar chaves no GitHub e sem executar `apply`.
