"""Escopo comprovável de credenciais — não confundir instituição com dataset.

Este diagnóstico é documental, offline, imutável e derivado do catálogo/rotas
canônicos do NIVON. Não autentica, não coleta, não lê segredos nem habilita jobs.
"""
from __future__ import annotations

import argparse
import json

from .catalogo_fontes import carregar_catalogo, validar_catalogo
from .rotas_coleta import carregar_rotas, validar_rotas

# Apenas identidades de *serviço* e seus possíveis datasets canônicos.
# Um email de chave USDA FAS não é uma chave USDA NASS, nem prova WASDE.
# BDMEP histórico de arquivo não é o serviço de dados horários contínuos.
_CONTRATOS = (
    {
        "fonte": "USDA",
        "servico": "USDA_FAS_PSD_GATEWAY",
        "credencial": "API_DATA_GOV_RECEBIDA_POR_EMAIL_NAO_TESTADA",
        "dataset_id": "USDA_PSD",
        "escopo": "CATALOGO_E_API_PSD_CANDIDATA",
        "nao_cobertos": (
            "USDA_NASS", "USDA_EXPORT_SALES", "USDA_WASDE_RELEASE_VINTAGES"
        ),
        "proximo_gate": "AUTENTICACAO_FAS_PSD_E_AMOSTRA_OFICIAL_REAL",
    },
    {
        "fonte": "ANA",
        "servico": "ANA_HIDROWEB_TELEMETRIA_ADOTADA",
        "credencial": "IDENTIFICADOR_E_SENHA_RECEBIDOS_POR_EMAIL_NAO_TESTADOS",
        "dataset_id": "ANA_HIDRO",
        "escopo": "SOMENTE_SERIE_TELEMETRICA_ADOTADA",
        "nao_cobertos": (),
        "proximo_gate": "TOKEN_SSO_E_LEITURA_REAL_COM_ESTACAO_E_QC",
    },
    {
        "fonte": "INMET",
        "servico": "INMET_BDMEP_ARQUIVO_POR_SOLICITACAO",
        "credencial": "LINK_ZIP_RECEBIDO_POR_EMAIL_NAO_TESTADO",
        "dataset_id": "INMET_ESTACOES",
        "escopo": "APENAS_ARQUIVO_HISTORICO_BDMEP_NAO_API_CONTINUA",
        "nao_cobertos": (),
        "proximo_gate": "VALIDAR_LINK_ZIP_REAL_ESQUEMA_QC_E_DIREITOS",
    },
)


class ErroEscopoAcesso(ValueError):
    """O diagnóstico encontrou divergência no contrato de datasets."""


def auditar_escopo(catalogo: dict, rotas: dict) -> dict:
    """Restringe as afirmações a um serviço específico, nunca à fonte inteira."""
    validar_catalogo(catalogo)
    validar_rotas(rotas, catalogo)
    datasets = {d["id"]: d for d in catalogo["datasets"]}
    entradas = {r["dataset_id"]: r for r in rotas["entries"]}
    saida = []
    for item in _CONTRATOS:
        dataset_id = item["dataset_id"]
        ds = datasets.get(dataset_id)
        rota = entradas.get(dataset_id)
        if ds is None or rota is None or ds["source_id"] != item["fonte"]:
            raise ErroEscopoAcesso("escopo documental divergente do catalogo/rota")
        if ds["enabled"] or ds["collection_authorized"]:
            raise ErroEscopoAcesso("dataset indevidamente habilitado pelo catalogo")
        if rota["runtime_enabled"] or rota["scheduled_enabled"]:
            raise ErroEscopoAcesso("rota indevidamente habilitada")
        if rota["last_verified_data"] is not None:
            raise ErroEscopoAcesso("amostra real atribuida sem evidencia")
        for sibling in item["nao_cobertos"]:
            other = datasets.get(sibling)
            if other is None or other["source_id"] != item["fonte"]:
                raise ErroEscopoAcesso("dataset excluido inexistente ou de outra origem")
            if other["enabled"] or other["collection_authorized"]:
                raise ErroEscopoAcesso("escopo excluido foi habilitado indevidamente")
        if ds["data_dates_required"] != [
            "competencia", "referencia", "publicacao", "coleta"
        ]:
            raise ErroEscopoAcesso("contrato temporal canonico divergente")
        saida.append({
            "fonte_id": item["fonte"],
            "servico": item["servico"],
            "credencial_documentada": item["credencial"],
            "dataset_canonico_potencial": dataset_id,
            "escopo_tecnico": item["escopo"],
            "outros_datasets_nao_habilitados_pela_credencial": list(
                item["nao_cobertos"]
            ),
            "prioridade": ds["priority"],
            "autenticacao_real_verificada": False,
            "amostra_real_verificada": False,
            "api_ou_link_continuo_homologado": False,
            "direitos_por_operacao_verificados": False,
            "ingestao_historica_verificada": False,
            "habilitar_coleta": False,
            "publicavel": False,
            "proximo_gate": item["proximo_gate"],
        })
    return {
        "estado": "ESCOPO_DOCUMENTAL_SEM_AUTENTICACAO",
        "fonte_de_verdade": "CATALOGO_E_ROTAS_NIVON_V1",
        "servicos_auditados": len(saida),
        "autenticados": 0,
        "habilitados": 0,
        "resumo": saida,
        "limites": (
            "Credencial recebida nao demonstra validade, cobertura de outros "
            "servicos, amostra, licenca, persistencia ou uso continuo."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Escopo de credenciais USDA/ANA/INMET: somente auditoria offline"
    )
    parser.add_argument("--resumo", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = auditar_escopo(carregar_catalogo(), carregar_rotas())
        if args.resumo:
            result.pop("resumo")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "estado": "BLOQUEADO",
            "motivo": str(exc),
        }, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
