"""Serie de trafego agregado do FMI PortWatch; NAO e line-up individual.

ArcGIS FeatureServer publico documentado pelo FMI. Janela curta e opt-in
explicito; não realizar crawling de toda a base.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
        "Daily_Chokepoints_Data/FeatureServer/0/query")
PASSAGENS = {
    "hormuz": "Strait of Hormuz",
    "bab_el_mandeb": "Bab el-Mandeb Strait",
    "suez": "Suez Canal",
    "panama": "Panama Canal",
    "malaca": "Malacca Strait",
    "cabo_boa_esperanca": "Cape of Good Hope",
}
MAX_BYTES = 1_000_000
MAX_REGISTROS = 1000


class PortWatchErro(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _dia(raw):
    try:
        value = date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise PortWatchErro("data invalida") from exc
    if value < date(2019, 1, 1):
        raise PortWatchErro("data anterior a serie disponivel")
    return value


def consulta_url(*, passagens, inicio, fim, offset=0):
    """Consulta pequena, com aliases fixos; sem SQL ou endpoint arbitrario."""
    names = sorted(set(passagens))
    if not names or any(name not in PASSAGENS for name in names):
        raise PortWatchErro("passagem nao cadastrada")
    start, end = _dia(inicio), _dia(fim)
    if end < start or (end - start).days > 30:
        raise PortWatchErro("janela maxima 31 dias")
    if not isinstance(offset, int) or offset < 0 or offset > 5000:
        raise PortWatchErro("paginacao fora dos limites")
    quoted = ",".join("'" + PASSAGENS[name].replace("'", "''") + "'" for name in names)
    where = ("portname IN (" + quoted + ") AND date >= DATE '" + start.isoformat()
             + "' AND date <= DATE '" + end.isoformat() + "'")
    args = {
        "where": where, "outFields": "date,portid,portname,n_total,capacity,n_dry_bulk,n_tanker",
        "returnGeometry": "false", "orderByFields": "date ASC,portname ASC",
        "resultOffset": str(offset), "resultRecordCount": str(MAX_REGISTROS), "f": "json",
    }
    return BASE + "?" + urlencode(args)


def baixar_pagina(url, *, permitir_rede=False, transporte=None):
    """Aceita somente URL construida pelo adaptador no host fixo."""
    if not permitir_rede:
        raise PermissionError("PortWatch requer opt-in de rede")
    if not isinstance(url, str) or not url.startswith(BASE + "?"):
        raise PortWatchErro("URL nao e do endpoint canonico")
    req = Request(url, headers={"Accept": "application/json",
                                  "User-Agent": "NIVON/0.1 (maritime observation)"})
    opener = transporte or build_opener(_SemRedirect())
    try:
        with opener.open(req, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise PortWatchErro("status ou URL de resposta nao confirmados")
            body = response.read(MAX_BYTES + 1)
    except PortWatchErro:
        raise
    except Exception:
        raise PortWatchErro("falha de transporte PortWatch") from None
    if not body or len(body) > MAX_BYTES:
        raise PortWatchErro("resposta vazia ou muito grande")
    return body


def normalizar(resposta, *, consultadas, coletado_em):
    """n_total e contagem AIS; capacity e estimativa de carga em transito, nao volume operacional certificado."""
    try:
        raw = json.loads(resposta)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PortWatchErro("JSON invalido") from exc
    if not isinstance(raw, dict) or "error" in raw or not isinstance(raw.get("features"), list):
        raise PortWatchErro("resposta ArcGIS sem features validas")
    if len(raw["features"]) > MAX_REGISTROS:
        raise PortWatchErro("pagina excedeu limite")
    try:
        collected = datetime.fromisoformat(coletado_em.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise PortWatchErro("coleta invalida") from exc
    if collected.tzinfo is None:
        raise PortWatchErro("coleta sem fuso")
    names = {PASSAGENS[k]: k for k in consultadas}
    saida = []
    ids = set()
    for f in raw["features"]:
        if not isinstance(f, dict) or not isinstance(f.get("attributes"), dict):
            raise PortWatchErro("atributos ausentes")
        a = f["attributes"]
        name = a.get("portname")
        if name not in names:
            raise PortWatchErro("passagem fora do escopo solicitado")
        reference = _dia(a.get("date")).isoformat()
        count = a.get("n_total")
        if type(count) is not int or count < 0:
            raise PortWatchErro("contagem AIS invalida")
        cap = a.get("capacity")
        if cap is not None and (type(cap) not in (int, float) or cap < 0 or cap != cap):
            raise PortWatchErro("volume de transito estimado invalido")
        dry, tank = a.get("n_dry_bulk"), a.get("n_tanker")
        if any(v is not None and (type(v) is not int or v < 0 or v > count) for v in (dry, tank)):
            raise PortWatchErro("categorias de navio invalidas")
        identifier = str(a.get("portid") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
            raise PortWatchErro("identificador PortWatch invalido")
        key = (names[name], reference)
        if key in ids:
            raise PortWatchErro("registro diario duplicado")
        ids.add(key)
        lag = (collected.date() - date.fromisoformat(reference)).days
        saida.append({
            "fonte": "FMI_PORTWATCH", "passagem": names[name],
            "nome_oficial": name, "portid": identifier, "data_referencia": reference,
            "transitos_ais": count, "navios_graneleiros_ais": dry, "navios_tanque_ais": tank,
            "volume_transito_estimado_t": cap, "natureza_transitos": "OBSERVADO_SINAL_AIS",
            "natureza_volume_estimado": "ESTIMADO_MODELO_FMI",
            "operacoes_confirmadas": False, "volume_realizado_t": None,
            "coletado_em": collected.astimezone(timezone.utc).isoformat(),
            "flags_qualidade": ["SOURCE_LAG"] if lag > 14 else [],
        })
    return saida, bool(raw.get("exceededTransferLimit", False))


class HistoricoPortWatch:
    def __init__(self, caminho=":memory:"):
        self.con = sqlite3.connect(str(caminho))
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS portwatch_diario (
              passagem TEXT NOT NULL,
              data_referencia TEXT NOT NULL,
              revisao_sha256 TEXT NOT NULL,
              coletado_em TEXT NOT NULL,
              dados_json TEXT NOT NULL,
              PRIMARY KEY(passagem, data_referencia, revisao_sha256)
            )""")
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_pw_data ON portwatch_diario(data_referencia)")

    def inserir(self, linhas):
        count = 0
        with self.con:
            for item in linhas:
                p = dict(item)
                if p.get("fonte") != "FMI_PORTWATCH" or p.get("volume_realizado_t") is not None:
                    raise PortWatchErro("contrato PortWatch violado")
                version = {k: v for k, v in p.items() if k not in ("coletado_em", "flags_qualidade")}
                digest = hashlib.sha256(json.dumps(version, sort_keys=True).encode()).hexdigest()
                result = self.con.execute(
                    "INSERT OR IGNORE INTO portwatch_diario VALUES (?,?,?,?,?)",
                    (p["passagem"], p["data_referencia"], digest, p["coletado_em"],
                     json.dumps(p, ensure_ascii=False, sort_keys=True)),
                )
                count += result.rowcount
        return count

    def quantidade(self):
        return self.con.execute("SELECT COUNT(*) FROM portwatch_diario").fetchone()[0]

    def fechar(self):
        self.con.close()


def consultar_janela(passagens, inicio, fim, *, permitir_rede=False, transporte=None):
    """Paginar apenas uma janela curta; falha em paginas inesperadas."""
    records = []
    for offset in range(0, 6000, MAX_REGISTROS):
        url = consulta_url(passagens=passagens, inicio=inicio, fim=fim, offset=offset)
        content = baixar_pagina(url, permitir_rede=permitir_rede, transporte=transporte)
        daily, more = normalizar(content, consultadas=passagens, coletado_em=datetime.now(timezone.utc).isoformat())
        records.extend(daily)
        if not more:
            return records
    raise PortWatchErro("limite de paginas alcançado; reduzir a janela")
