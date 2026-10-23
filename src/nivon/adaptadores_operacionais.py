"""Pontes somente-leitura para os ledgers existentes de fretes e AIS.

As entradas vêm dos módulos NIVON `consolidar_ofertas` e
`MaritimeStore.save_ais`. Não criam coletores, dados, tabelas ou permissões.
Não convertem ofertas em fretes realizados nem AIS em escala/DUV/terminal.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from .painel_operacional import ErroMotor, _decimal, _tempo


PORTO_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
MMSI = re.compile(r"^[0-9]{9}$")
IBGE = re.compile(r"^[0-9]{7}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
QUALIDADE = {"CONFIRMED_SEQUENCE", "UNCONFIRMED_SINGLE", "QUARANTINE", "UNVALIDATED"}
CAMPOS_SERIE = ("origem", "destino", "ponto_embarque", "transportadora",
                "terminal", "produto", "equipamento", "regime",
                "pedagio", "tipo_preco", "provedor")


def adaptar_fretes_consolidados(consolidado: dict, *, as_of: str) -> dict:
    """Agrupa anúncios por identidade econômica, nunca por média municipal.

    Mantém o preço BASE e o pedágio em campo próprio. Sem SHA da
    publicação bruta, o indicador Theil-Sen de revisões permanece gated.
    """
    corte = _tempo(as_of)
    if not isinstance(consolidado, dict) or consolidado.get("natureza") != "FRETE_ANUNCIADO_NAO_CONTRATADO":
        raise ErroMotor("consolidado deve declarar fretes anunciados, não contratados")
    linhas = consolidado.get("registros")
    if not isinstance(linhas, list) or not 1 <= len(linhas) <= 10000:
        raise ErroMotor("registros de fretes ausentes ou acima do limite")
    if (type(consolidado.get("total_registros_individuais_deduplicados")) is not int
            or consolidado["total_registros_individuais_deduplicados"] != len(linhas)):
        raise ErroMotor("consolidado de fretes com contagem divergente")
    grupos: dict[tuple, list[dict]] = {}
    ids: set[tuple[str, str, str]] = set()
    ignorados = 0
    for row in linhas:
        if not isinstance(row, dict):
            raise ErroMotor("registro de frete malformado")
        ident = {}
        for chave, fonte in (
            ("origem", "municipio_ibge"), ("destino", "destino_ibge"),
            ("ponto_embarque", "pickup_entity_id"), ("transportadora", "transportadora_id"),
            ("terminal", "descarga_entity_id"), ("produto", "produto"),
            ("equipamento", "equipamento"), ("regime", "regime"),
        ):
            valor = row.get(fonte)
            if not isinstance(valor, str) or not valor.strip() or len(valor) > 180:
                raise ErroMotor("identidade comercial incompleta: " + fonte)
            ident[chave] = valor
        if not IBGE.fullmatch(ident["origem"]) or not IBGE.fullmatch(ident["destino"]):
            raise ErroMotor("IBGE de origem/destino inválido")
        if ident["regime"] not in {"PF", "PJ", "NAO_INFORMADO"}:
            raise ErroMotor("regime de frete inválido")
        ident["pedagio"] = "ADICIONAL" if row.get("pedagio_brl_t") is not None else "NAO_INFORMADO"
        ident["tipo_preco"] = "BASE"
        provedor = row.get("provedor_id") or "LEGADO_SEM_PROVEDOR"
        if not isinstance(provedor, str) or len(provedor) > 180:
            raise ErroMotor("provedor inválido")
        ident["provedor"] = provedor
        origem_id = row.get("fonte_id")
        reg_id = row.get("registro_id")
        if any(not isinstance(v, str) or not v.strip() or len(v)>180
               for v in (origem_id, reg_id)):
            raise ErroMotor("origem ou registro de anúncio não identificável")
        chave_id = (origem_id, provedor, reg_id)
        if chave_id in ids:
            raise ErroMotor("mesmo registro de anúncio duplicado")
        ids.add(chave_id)
        try:
            referencia = date.fromisoformat(row["data_referencia"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ErroMotor("data_referencia de anúncio inválida") from exc
        publicacao = _tempo(row.get("data_publicacao"))
        coleta = _tempo(row.get("data_coleta"))
        if publicacao > coleta or referencia > publicacao.date():
            raise ErroMotor("linha do tempo da divulgação inconsistente")
        valor = _decimal(row.get("frete_base_brl_t"), positivo=True)
        if row.get("pedagio_brl_t") is not None:
            _decimal(row["pedagio_brl_t"])
        if row.get("frete_cheio_brl_t") is not None:
            _decimal(row["frete_cheio_brl_t"])
        if publicacao > corte or coleta > corte or referencia > corte.date():
            ignorados += 1
            continue
        assinatura = tuple(ident[campo] for campo in CAMPOS_SERIE)
        token = hashlib.sha256(
            json.dumps(assinatura, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
        serie_id = "FRETE_" + token.upper()
        campos = {k: v for k, v in ident.items() if k != "provedor"}
        campos.update({
            "serie_id": serie_id, "classe": "FRETE_ANUNCIADO",
            "modal": "RODOVIARIO", "contrato": None,
            "fonte_original": origem_id, "provedor_id": provedor,
            "pedagio_brl_t": row.get("pedagio_brl_t"),
            "oferta_id": row.get("oferta_id"),
            "publicacoes_origem": row.get("publicacoes_origem", []),
        })
        grupos.setdefault(assinatura, []).append({
            "dataset_id": "NIVON_FRETES_ANUNCIADOS",
            "identidade": reg_id,
            "data_referencia": referencia.isoformat(),
            "data_publicacao": publicacao.isoformat(),
            "data_coleta": coleta.isoformat(),
            "natureza": "INFORMADO",
            "unidade": "BRL/T",
            "valor": str(valor),
            "campos": campos,
            # Nunca simular uma prova criptográfica da publicação original.
            "fingerprint": None,
        })
    if len(grupos) > 50:
        raise ErroMotor("mais de 50 séries de fretes; particionar por recorte")
    series = [
        {"classe": "FRETE_ANUNCIADO", "serie_id": linhas[0]["campos"]["serie_id"],
         "observacoes": linhas}
        for _, linhas in sorted(grupos.items())
    ]
    return {
        "status": "FRETES_ANUNCIADOS_LIDOS_NAO_HOMOLOGADOS",
        "series": series,
        "registros_elegiveis": sum(len(x["observacoes"]) for x in series),
        "registros_futuros_excluidos": ignorados,
        "series_distintas": len(series),
        "proveniencia_completa_raw": False,
        "negociacoes_confirmadas": False,
    }


def ler_replay_ais_sqlite(*, banco: str, porto_id: str, inicio: str,
                          fim: str, as_of: str, limite: int = 2000) -> dict:
    """Lê eventos `MaritimeStore` com SQLite RO e SHA individual verificado.

    Conta MMSIs que têm evidência CONFIRMED_SEQUENCE no recorte; não
    classifica AGUARDANDO, FUNDEADO, ATRACADO ou navios operados.
    """
    if not isinstance(porto_id, str) or not PORTO_ID.fullmatch(porto_id):
        raise ErroMotor("porto_id canônico inválido")
    if type(limite) is not int or not 1 <= limite <= 5000:
        raise ErroMotor("limite de eventos inválido")
    start, end, corte = _tempo(inicio), _tempo(fim), _tempo(as_of)
    if start > end or end > corte or (end-start).total_seconds()>7*86400:
        raise ErroMotor("janela AIS inválida ou maior que sete dias")
    if not isinstance(banco, str):
        raise ErroMotor("banco deve ser caminho local")
    path = Path(banco)
    if path.is_symlink() or not path.is_file():
        raise ErroMotor("SQLite AIS precisa existir e não pode ser symlink")
    # mode=ro nunca cria/atualiza o arquivo do coletor.
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as con:
        con.execute("PRAGMA query_only=ON")
        try:
            eventos = con.execute(
                """SELECT event_id, source_id, observed_at, collected_at,
                          quality_status, mmsi, payload_sha256, payload_json
                   FROM maritime_ais
                   WHERE port_id=? AND observed_at>=? AND observed_at<=?
                     AND collected_at<=?
                   ORDER BY observed_at,event_id LIMIT ?""",
                (porto_id, start.isoformat(), end.isoformat(), corte.isoformat(), limite+1)
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise ErroMotor("ledger AIS não corresponde ao schema MaritimeStore") from exc
    if len(eventos)>limite:
        raise ErroMotor("replay AIS truncado; dividir a janela para não subcontar")
    fontes=set()
    unicos=set()
    identidades=set()
    qualidades=Counter()
    ultima = None
    for event_id, source_id, observed_at, collected_at, quality, mmsi, raw_sha, raw_json in eventos:
        if (not isinstance(event_id, str) or not SHA.fullmatch(event_id)
                or not isinstance(raw_sha, str) or not SHA.fullmatch(raw_sha)
                or not isinstance(raw_json, str) or len(raw_json.encode("utf-8"))>2_000_000
                or hashlib.sha256(raw_json.encode("utf-8")).hexdigest()!=raw_sha):
            raise ErroMotor("hash ou payload do evento AIS corrompido")
        if not isinstance(source_id, str) or not source_id:
            raise ErroMotor("AIS sem fonte")
        identidade_esperada = hashlib.sha256(
            (source_id + "|" + raw_sha).encode("utf-8")
        ).hexdigest()
        if event_id != identidade_esperada:
            raise ErroMotor("identidade AIS não corresponde à fonte e ao payload")
        if event_id in identidades:
            raise ErroMotor("evento AIS duplicado")
        identidades.add(event_id)
        obs, col = _tempo(observed_at), _tempo(collected_at)
        if not (start<=obs<=end and obs<=col<=corte):
            raise ErroMotor("cronologia AIS inconsistente")
        if quality not in QUALIDADE:
            raise ErroMotor("qualidade AIS desconhecida")
        try:
            payload=json.loads(raw_json)
        except ValueError as exc:
            raise ErroMotor("payload AIS não é JSON") from exc
        if not isinstance(payload, dict) or _tempo(payload.get("observed_at"))!=obs:
            raise ErroMotor("payload AIS sem horário coerente")
        if str(payload.get("mmsi") or "")!=str(mmsi or ""):
            raise ErroMotor("MMSI do payload diverge do índice")
        if not isinstance(source_id, str) or not source_id:
            raise ErroMotor("AIS sem fonte")
        fontes.add(source_id)
        qualidades[quality]+=1
        if quality=="CONFIRMED_SEQUENCE" and MMSI.fullmatch(str(mmsi or "")) and mmsi!="000000000":
            unicos.add(mmsi)
        ultima = obs if ultima is None or obs>ultima else ultima
    return {
        "porto_id": porto_id, "status": "REPLAY_AIS_CONCILIADO_SEM_ESTADO_FISICO",
        "eventos_lidos": len(eventos),
        "eventos_confirmados_sequencia": qualidades["CONFIRMED_SEQUENCE"],
        "mmsi_distintos_confirmados": len(unicos),
        "qualidade_eventos": dict(sorted(qualidades.items())),
        "fontes": sorted(fontes), "ultima_observacao": ultima.isoformat() if ultima else None,
        "inicio":start.isoformat(), "fim":end.isoformat(), "as_of":corte.isoformat(),
        "navios_aguardando":None, "navios_operados":None,
        "duv_confirmadas":None, "tonelagem_realizada":None,
        "apto_para_indice_fila":False,
        "nota":"MMSI confirmado por sequencia nao comprova chegada, geocerca, berco ou carga.",
    }
