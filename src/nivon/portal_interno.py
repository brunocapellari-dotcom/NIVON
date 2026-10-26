"""Portal operacional privado NIVON, sem dependencias ou rede externa.

Consome apenas readbacks REAIS pre-validados dos leitores existentes.
Nenhum sinal sintético, cotacao restrita ou estimativa vira fato publicado.
O servidor e local por padrao; exposicao externa exige infraestrutura autenticada.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import partial
from http import HTTPStatus
from importlib.resources import files
import json
import os
from pathlib import Path
import re
from wsgiref.simple_server import make_server

MAX_INPUT = 2_000_000
_SHA = re.compile(r"^[a-f0-9]{64}$")
_COMP = re.compile(r"^20[0-9]{2}-(0[1-9]|1[0-2])$")
_SCHEMA = "nivon.portal.interno.v1"
_ESTADO = "DADOS_REAIS_EM_REVISAO_INTERNA_NAO_HOMOLOGADOS"


class ErroPortal(ValueError):
    pass


def _json_unico(items):
    d = {}
    for k, v in items:
        if k in d:
            raise ErroPortal("campo JSON duplicado")
        d[k] = v
    return d


def _tempo(t):
    if not isinstance(t, str):
        raise ErroPortal("timestamp com fuso obrigatorio")
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroPortal("timestamp invalido") from exc
    if dt.utcoffset() is None:
        raise ErroPortal("timestamp sem fuso")
    return dt.astimezone(timezone.utc)


def _quantia(v):
    if isinstance(v, bool) or v is None:
        raise ErroPortal("medida numerica ausente")
    try:
        x = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ErroPortal("medida nao numerica") from exc
    if not x.is_finite() or x < 0 or len(x.as_tuple().digits) > 30:
        raise ErroPortal("medida numerica invalida")
    return x


def _contagem(v):
    if type(v) is not int or v < 0:
        raise ErroPortal("contagem invalida")
    return v


def _item(*, id, grupo, titulo, valor, unidade, referencia, fonte,
          natureza, ressalva):
    return {
        "id": id, "grupo": grupo, "titulo": titulo,
        "valor": str(valor), "unidade": unidade, "referencia": referencia,
        "fonte": fonte, "natureza": natureza, "ressalva": ressalva,
        "publicavel": False,
    }


def montar_snapshot(readback: dict, *, gerado_em: str) -> dict:
    """Transforma somente o contrato de readback BigQuery existente.

    O retorno e um painel INTERNO, nao autorizacao para publicar. A veracidade
    requer executar os conectores sob identidade confiavel e revisar a origem.
    """
    corte = _tempo(gerado_em)
    if (not isinstance(readback, dict)
            or readback.get("status") != "ANALISE_SHADOW_NAO_HOMOLOGADA"
            or readback.get("executou_bigquery") is not True):
        raise ErroPortal("readback real BigQuery nao comprovado")
    indicadores, avisos, fontes = [], [], []
    ferrovia = readback.get("ferrovia")
    if ferrovia is not None:
        if (not isinstance(ferrovia, dict) or ferrovia.get("executado") is not True
                or ferrovia.get("publicavel") is not False
                or ferrovia.get("historico_pit_reconstruido") is not False
                or ferrovia.get("transbordo_confirmado") is not False
                or ferrovia.get("fonte") != "ANTT_SIADE_ORIGEM_DESTINO"
                or not _COMP.fullmatch(str(ferrovia.get("competencia", "")))
                or _tempo(ferrovia.get("as_of")) != corte):
            raise ErroPortal("leitura ferroviaria nao confiavel")
        fontes.append("ANTT_SIADE_ORIGEM_DESTINO")
        if ferrovia.get("estado") == "REVISAO_ATUAL_CONSULTADA_NAO_HOMOLOGADA":
            hashes = ferrovia.get("arquivos_sha256")
            polos = ferrovia.get("polos_ferroviarios")
            if (not isinstance(hashes, list) or not hashes
                    or not all(isinstance(h, str) and _SHA.fullmatch(h) for h in hashes)
                    or not isinstance(polos, list) or not 1 <= len(polos) <= 100):
                raise ErroPortal("SIADE sem hashes ou polos validos")
            if _contagem(ferrovia.get("linhas_view")) < 1:
                raise ErroPortal("SIADE sem linhas validadas")
            total = Decimal("0")
            seen = set()
            for polo in polos:
                pid = polo.get("polo", {}).get("id") if isinstance(polo, dict) else None
                if not isinstance(pid, str) or not re.fullmatch(r"MT_[A-Z0-9_]{3,90}", pid) or pid in seen:
                    raise ErroPortal("polo SIADE duplicado ou invalido")
                seen.add(pid)
                tu = _quantia(polo.get("toneladas_ferroviarias"))
                total += tu
            indicadores.append(_item(id="ferrovia_tu", grupo="logistica",
                titulo="Ferrovia MT — tonelagem útil", valor=total,
                unidade="TU", referencia=ferrovia["competencia"],
                fonte="ANTT / SIADE", natureza="OBSERVADO_DECLARADO",
                ressalva="Recorte ferroviario por estacao de origem; nao equivale a transbordos nem a movimentacao rodoviaria. Revisao atual, nao point-in-time historico."))
            indicadores.append(_item(id="ferrovia_polos", grupo="logistica",
                titulo="Polos ferroviários do recorte", valor=len(polos),
                unidade="polos", referencia=ferrovia["competencia"],
                fonte="ANTT / SIADE", natureza="CONTAGEM_DERIVADA",
                ressalva="Polos identificados por nome de estacao, nao terminais comprovados."))
        elif ferrovia.get("estado") == "SEM_REGISTROS_NAO_SIGNIFICA_ZERO":
            avisos.append("ANTT/SIADE: sem registros no recorte; nao presumir zero.")
        else:
            raise ErroPortal("estado ferroviario desconhecido")
    maritimo = readback.get("fontes_maritimas_bigquery", [])
    if not isinstance(maritimo, list) or len(maritimo) > 8:
        raise ErroPortal("leituras maritimas malformadas")
    vistos = set()
    for m in maritimo:
        if (not isinstance(m, dict) or m.get("executado") is not True
                or m.get("publicavel") is not False
                or _tempo(m.get("as_of")) != corte):
            raise ErroPortal("readback maritimo nao comprovado")
        fonte, passagem = m.get("fonte"), m.get("passagem")
        if (fonte is None) == (passagem is None):
            raise ErroPortal("fonte maritima ambigua")
        ident = ("fonte", fonte) if fonte else ("passagem", passagem)
        if ident in vistos:
            raise ErroPortal("fonte maritima repetida")
        vistos.add(ident)
        if fonte:
            if fonte not in {"imbituba", "suape", "santarem_cdp", "vila_conde_cdp"}:
                raise ErroPortal("fonte maritima fora do catalogo")
            fontes.append("LINEUP_" + fonte.upper())
            if m.get("estado") == "SEM_REVISOES_NAO_EQUIVALE_A_ZERO":
                avisos.append(f"{fonte}: sem revisoes de programacao conhecidas.")
                continue
            if m.get("estado") != "PROGRAMACAO_HISTORICA_READONLY_SHADOW":
                raise ErroPortal("estado de programacao invalido")
            n = _contagem(m.get("ids_programacao_distintos"))
            rev = _contagem(m.get("revisoes_visiveis"))
            if n > rev:
                raise ErroPortal("programacoes excedem revisoes")
            indicadores.append(_item(
                id="lineup_" + fonte, grupo="maritimo",
                titulo=fonte.replace("_", " ").title() + " — IDs de programação",
                valor=n, unidade="IDs", referencia=f"{m['inicio']} a {m['fim']}",
                fonte="Line-up institucional / NIVON",
                natureza="INFORMADO_PROGRAMADO",
                ressalva="Nao representam navios operados, DUV, carga embarcada ou fila AIS."))
        else:
            if passagem not in {"panama", "suez", "hormuz", "bab_el_mandeb"}:
                raise ErroPortal("passagem fora do catalogo")
            fontes.append("FMI_PORTWATCH_" + passagem.upper())
            if m.get("estado") == "SEM_DADOS_NAO_EQUIVALE_A_ZERO":
                avisos.append(f"PortWatch {passagem}: dados ausentes; nao presumir zero.")
                continue
            if m.get("estado") != "PORTWATCH_TRANSITOS_ESTIMADOS_SHADOW":
                raise ErroPortal("estado PortWatch invalido")
            if (m.get("volume_movimentado_real") is not None
                    or m.get("transitos_portuarios_confirmados") is not None):
                raise ErroPortal("PortWatch nao comprova movimentacao realizada")
            n = _contagem(m.get("transitos_ais_reportados"))
            indicadores.append(_item(
                id="portwatch_" + passagem, grupo="maritimo",
                titulo=passagem.replace("_", " ").title() + " — trânsitos AIS reportados",
                valor=n, unidade="trânsitos", referencia=f"{m['inicio']} a {m['fim']}",
                fonte="FMI / PortWatch", natureza="INFORMADO_AIS",
                ressalva="Passagens reportadas no recorte; nao navios aportados nem carga efetiva."))
    if not fontes:
        raise ErroPortal("nenhuma fonte real consultada")
    return {
        "schema": _SCHEMA, "modo": "INTERNO_SHADOW",
        "estado": _ESTADO, "gerado_em": corte.isoformat(timespec="seconds"),
        "fontes_consultadas": fontes,
        "indicadores": indicadores, "avisos": avisos,
        "publicavel": False, "redistribuicao_autorizada": False,
        "precos_homologados": False, "go_live_publico": False,
        "nota": "Dados observados/informados no readback; sem homologacao editorial, comercial ou publicacao automatica.",
    }


def validar_snapshot(doc):
    if (not isinstance(doc, dict) or doc.get("schema") != _SCHEMA
            or doc.get("modo") != "INTERNO_SHADOW"
            or doc.get("estado") != _ESTADO
            or doc.get("publicavel") is not False
            or doc.get("go_live_publico") is not False
            or doc.get("redistribuicao_autorizada") is not False):
        raise ErroPortal("snapshot fora do contrato privado")
    _tempo(doc.get("gerado_em"))
    fontes, items = doc.get("fontes_consultadas"), doc.get("indicadores")
    if (not isinstance(fontes, list) or not fontes or
            not isinstance(items, list) or len(items) > 30
            or not isinstance(doc.get("avisos"), list)):
        raise ErroPortal("payload de indicadores invalido")
    ids = set()
    for it in items:
        if not isinstance(it, dict) or it.get("publicavel") is not False:
            raise ErroPortal("indicador publicavel incorretamente")
        iid = it.get("id")
        if not isinstance(iid, str) or not re.fullmatch(r"[a-z0-9_]{3,100}", iid) or iid in ids:
            raise ErroPortal("identificador invalido ou repetido")
        ids.add(iid)
        if it.get("grupo") not in {"logistica", "maritimo", "mercado", "clima"}:
            raise ErroPortal("grupo nao suportado")
        for k in ("titulo", "valor", "unidade", "referencia", "fonte", "natureza", "ressalva"):
            if not isinstance(it.get(k), str) or not 1 <= len(it[k]) <= 700:
                raise ErroPortal("campo de indicador ausente")
    return doc


def carregar_snapshot(caminho: Path):
    if caminho.is_symlink() or not caminho.is_file() or not 0 < caminho.stat().st_size <= MAX_INPUT:
        raise ErroPortal("snapshot ausente, inseguro ou excessivo")
    try:
        raw = caminho.read_text(encoding="utf-8")
        doc = json.loads(raw, object_pairs_hook=_json_unico,
                         parse_constant=lambda x: (_ for _ in ()).throw(ErroPortal("NaN proibido")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ErroPortal("JSON de snapshot invalido") from exc
    return validar_snapshot(doc)


def criar_app(caminho: str | Path | None, *, leitor_snapshot=None):
    """API privada: snapshot de arquivo local ou leitor GCS injetado."""
    if leitor_snapshot is None:
        if caminho is None:
            raise ErroPortal("caminho ou leitor do snapshot obrigatorio")
        caminho = Path(caminho)
    elif not callable(leitor_snapshot):
        raise ErroPortal("leitor do snapshot nao e callable")
    assets = {
        "/": ("text/html; charset=utf-8", "index.html"),
        "/assets/portal.css": ("text/css; charset=utf-8", "portal.css"),
        "/assets/portal.js": ("text/javascript; charset=utf-8", "portal.js"),
    }

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        headers = [
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy",
             "default-src 'none'; connect-src 'self'; script-src 'self'; style-src 'self'; "
             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
        ]
        def response(code, mime, body):
            start_response(code, headers + [("Content-Type", mime), ("Content-Length", str(len(body)))])
            return [body]
        if method != "GET":
            return response("405 Method Not Allowed", "text/plain; charset=utf-8", b"Metodo nao permitido")
        if path == "/healthz":
            return response("200 OK", "application/json", b'{"status":"PROCESSO_ATIVO"}')
        if path in ("/api/v1/painel", "/readyz"):
            try:
                doc = (carregar_snapshot(caminho) if leitor_snapshot is None
                       else validar_snapshot(leitor_snapshot()))
                age = datetime.now(timezone.utc) - _tempo(doc["gerado_em"])
                if age < timedelta(minutes=-5):
                    raise ErroPortal("snapshot do futuro")
            except (OSError, ValueError) as exc:
                reason = "SEM_SNAPSHOT_VALIDO"
                return response("503 Service Unavailable", "application/json",
                                json.dumps({"status": reason}, separators=(",", ":")).encode())
            fresh = age <= timedelta(hours=24)
            if path == "/readyz":
                status = "PRONTO_INTERNO" if fresh else "SNAPSHOT_DEFASADO"
                return response("200 OK" if fresh else "503 Service Unavailable", "application/json",
                                json.dumps({"status": status}).encode())
            out = {**doc, "frescor_snapshot": "ATUAL" if fresh else "DEFASADO"}
            return response("200 OK", "application/json; charset=utf-8",
                            json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if path in assets:
            mimetype, name = assets[path]
            body = files("nivon").joinpath("portal_static", name).read_bytes()
            return response("200 OK", mimetype, body)
        return response("404 Not Found", "text/plain; charset=utf-8", b"Rota nao encontrada")
    return app


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: portal exclusivamente interno read-only")
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    a = p.parse_args(argv)
    if not 0 < a.port < 65536:
        p.error("porta invalida")
    if a.host == "0.0.0.0" and os.environ.get("NIVON_PORTAL_PRIVATE_INGRESS_APPROVED") != "true":
        p.error("exposicao de rede bloqueada; exija ingresso privado e IAM Cloud Run")
    with make_server(a.host, a.port, criar_app(a.snapshot)) as server:
        print(f"NIVON_PORTAL_INTERNO http://{a.host}:{a.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
