"""Testes pontuais de acesso privado: USDA FAS, ANA e INMET.

SEM coleta por padrão. Credenciais exclusivamente por variáveis de ambiente do
executor privado; nunca buscar o Gmail no runtime, imprimir URLs tokenizadas,
tokens ou corpos de erro de provedores. Usa apenas biblioteca padrão.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

_USDA_URL = "https://api.fas.usda.gov/api/psd/commodities"
_FONTES = ("usda", "ana", "inmet")


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _status(fonte: str, estado: str, *, evidencias: dict | None = None) -> dict:
    # Somente campos explicitamente permitidos entram em relatórios e logs.
    return {"fonte": fonte.upper(), "estado": estado,
            "evidencias": evidencias or {}, "homologado": False,
            "coleta_agendada": False, "publicavel": False}


def _usda(*, opener=None) -> dict:
    key = os.environ.get("AGROBR_USDA_API_KEY", "")
    if not key or not 20 <= len(key) <= 256 or any(c.isspace() for c in key):
        return _status("usda", "SEGREDO_INDISPONIVEL")
    req = Request(_USDA_URL, method="GET",
                  headers={"X-Api-Key": key, "Accept": "application/json"})
    client = opener or build_opener(_SemRedirect)
    try:
        with client.open(req, timeout=12) as res:
            if getattr(res, "status", None) != 200:
                return _status("usda", "STATUS_HTTP_NAO_VALIDADO")
            raw = res.read(262145)
        if not 0 < len(raw) <= 262144:
            return _status("usda", "JSON_FORA_DO_LIMITE")
        doc = json.loads(raw.decode("utf-8-sig"))
        # HTTP 200 pode ser JSON de erro/proxy. Validar os campos do catálogo
        # oficial FAS; não classificar qualquer lista de objetos como sucesso.
        if not isinstance(doc, list) or not doc or len(doc) > 1000:
            return _status("usda", "SCHEMA_INESPERADO")
        for item in doc:
            if not isinstance(item, dict):
                return _status("usda", "SCHEMA_INESPERADO")
            codigo = item.get("commodityCode")
            nome = item.get("commodityName")
            if (not isinstance(codigo, str) or not re.fullmatch(r"[0-9]{7}", codigo)
                    or not isinstance(nome, str) or not nome.strip() or len(nome) > 200):
                return _status("usda", "SCHEMA_INESPERADO")
        return _status("usda", "AUTENTICACAO_E_SCHEMA_OK",
                       evidencias={"endpoint": "/api/psd/commodities",
                                   "estrutura": "LISTA_DE_OBJETOS",
                                   "registros_lidos": len(doc)})
    except HTTPError as exc:
        if exc.code in (401, 403):
            return _status("usda", "CHAVE_RECUSADA")
        if exc.code == 429:
            return _status("usda", "LIMITE_API_ATINGIDO")
        if exc.code in (502, 503, 504):
            return _status("usda", "SERVICO_TEMPORARIAMENTE_INDISPONIVEL")
        return _status("usda", "STATUS_HTTP_NAO_VALIDADO")
    except (URLError, OSError, ValueError, UnicodeError, TypeError):
        return _status("usda", "FALHA_REDE_OU_PARSER")


def _ana(*, transport=None) -> dict:
    from .ana_hidrowebservice import (
        ErroANAAPI, construir_login, credenciais_ambiente,
        efetuar_request, extrair_token, construir_consulta_adotada,
        normalizar_adotada,
    )
    import hashlib
    from datetime import datetime, timezone
    try:
        identificador, senha = credenciais_ambiente()
    except ErroANAAPI:
        return _status("ana", "SEGREDO_INDISPONIVEL")
    try:
        req = construir_login(identificador=identificador, senha=senha)
        payload = efetuar_request(req, habilitar_rede=True,
                                  transporte=transport, limite_bytes=32768)
        token = extrair_token(payload)
    except (ErroANAAPI, OSError, ValueError):
        return _status("ana", "AUTENTICACAO_NAO_COMPROVADA")
    # Nunca imprimir o token ou a URL de consulta.
    estacao = os.environ.get("NIVON_ANA_ESTACAO", "")
    data = os.environ.get("NIVON_ANA_DATA_BUSCA", "")
    zona = os.environ.get("NIVON_ANA_ZONA_ESTACAO", "")
    if not (estacao and data and zona):
        return _status("ana", "AUTENTICACAO_OK_CONSULTA_PENDENTE")
    try:
        req = construir_consulta_adotada(
            estacao=estacao, data_busca=data, token=token)
        raw = efetuar_request(req, habilitar_rede=True,
                             transporte=transport, limite_bytes=2_000_000)
        rows = normalizar_adotada(
            raw, estacao=estacao, zona_estacao=zona,
            coletado_em=datetime.now(timezone.utc).isoformat(),
            origem_sha256=hashlib.sha256(raw).hexdigest())
        if not rows:
            return _status("ana", "AUTENTICACAO_OK_SEM_MEDICOES",
                           evidencias={"medicoes_normalizadas": 0})
        return _status("ana", "AUTENTICACAO_E_LEITURA_OK",
                       evidencias={"medicoes_normalizadas": len(rows),
                                   "medicoes_aprovadas_qc": sum(bool(x["utilizar_para_modelo"]) for x in rows)})
    except (ErroANAAPI, OSError, ValueError):
        return _status("ana", "AUTENTICACAO_OK_CONSULTA_NAO_VALIDADA")


def _inmet(*, transport=None) -> dict:
    from pathlib import Path
    from .inmet_bdmep import ErroBDMEP, link_privado_do_ambiente, receber_bdmep
    try:
        link_privado_do_ambiente()
    except ErroBDMEP:
        return _status("inmet", "LINK_PRIVADO_AUSENTE_OU_INVALIDO")
    dest = os.environ.get("NIVON_INMET_DIRETORIO_PRIVADO", "")
    if not dest or not Path(dest).is_dir():
        return _status("inmet", "DIRETORIO_PRIVADO_NAO_CONFIGURADO")
    try:
        result = receber_bdmep(
            pasta_privada=dest, habilitar_rede=True, transporte=transport)
        inv = result["inventario"]
        return _status("inmet", "ZIP_RECEBIDO_E_INSPECIONADO",
                       evidencias={"csv_no_zip": inv["csv"],
                                   "arquivos_no_zip": inv["membros"],
                                   "bytes_transferidos": result["bytes"]})
    except (ErroBDMEP, OSError, ValueError):
        # Um link vencido não deve ser classificado sem verificar a resposta.
        return _status("inmet", "LINK_OU_DOWNLOAD_NAO_VALIDADO")


def preflight(fonte: str) -> dict:
    """Valida formato/disponibilidade de secrets SEM rede e SEM revelar valores."""
    if fonte not in _FONTES:
        raise ValueError("fonte não permitida")
    try:
        if fonte == "usda":
            key = os.environ.get("AGROBR_USDA_API_KEY", "")
            if not 20 <= len(key) <= 256 or any(c.isspace() for c in key):
                return _status(fonte, "SEGREDO_INDISPONIVEL")
        elif fonte == "ana":
            from .ana_hidrowebservice import credenciais_ambiente, ErroANAAPI
            try:
                credenciais_ambiente()
            except ErroANAAPI:
                return _status(fonte, "SEGREDO_INDISPONIVEL")
        else:
            from .inmet_bdmep import link_privado_do_ambiente, ErroBDMEP
            try:
                link_privado_do_ambiente()
            except ErroBDMEP:
                return _status(fonte, "LINK_PRIVADO_AUSENTE_OU_INVALIDO")
    except (OSError, UnicodeError, ValueError):
        # Nunca serializar os valores capturados em exceções.
        return _status(fonte, "PREFLIGHT_NAO_VALIDADO")
    return _status(fonte, "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA")


def executar(fonte: str, *, habilitar_rede: bool = False, transporte=None) -> dict:
    if fonte not in _FONTES:
        raise ValueError("fonte não permitida")
    if not habilitar_rede:
        return _status(fonte, "REDE_DESATIVADA")
    if fonte == "usda":
        return _usda(opener=transporte)
    if fonte == "ana":
        return _ana(transport=transporte)
    return _inmet(transport=transporte)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NIVON: verificacao privada controlada, sem publicacao")
    parser.add_argument("--fonte", required=True, choices=_FONTES)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true",
                      help="verifica presença/formato de credenciais sem rede")
    mode.add_argument("--live", action="store_true",
                      help="habilita UMA verificação real, somente em executor privado")
    args = parser.parse_args(argv)
    result = preflight(args.fonte) if args.preflight else executar(
        args.fonte, habilitar_rede=args.live
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["estado"] in (
        "REDE_DESATIVADA", "CREDENCIAL_FORMATO_OK_NAO_AUTENTICADA",
        "AUTENTICACAO_E_SCHEMA_OK",
        "AUTENTICACAO_OK_CONSULTA_PENDENTE", "AUTENTICACAO_E_LEITURA_OK",
        "ZIP_RECEBIDO_E_INSPECIONADO",
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
