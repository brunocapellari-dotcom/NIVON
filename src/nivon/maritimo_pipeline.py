"""Coleta, versionamento e reconciliação operacional de line-ups do NIVON.

Camada persistente independente de plataforma. A inclusão em tabelas não
transforma informação programada em movimentação realizada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from nivon.lineup_portos import FONTES, extrair_lineup_html, verificar_cdp, inferir_presenca_amaggi, importar_gpv_csv

HTML_AUTORIZADO = frozenset(("suape", "imbituba", "santarem_cdp", "vila_conde_cdp"))
CDP = frozenset(("santarem_cdp", "vila_conde_cdp"))
MAX_HTML_BYTES = 2_000_000


class ColetaMaritimaErro(ValueError):
    pass


class _SemRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def agora_utc():
    return datetime.now(timezone.utc).isoformat()


def _utc(valor):
    try:
        value = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ColetaMaritimaErro("timestamp invalido") from exc
    if value.tzinfo is None:
        raise ColetaMaritimaErro("timestamp sem fuso")
    return value.astimezone(timezone.utc).isoformat()


def baixar_html(fonte, *, habilitar_rede=False, transporte=None, timeout=20):
    """Endpoint fixo em HTTPS, sem redirecionamento ou URL de entrada arbitraria."""
    if fonte not in HTML_AUTORIZADO:
        raise ColetaMaritimaErro("fonte sem coleta HTML publica configurada")
    if not habilitar_rede:
        raise PermissionError("coleta HTTP precisa de habilitacao explicita")
    if not isinstance(timeout, (int, float)) or not 2 <= timeout <= 40:
        raise ColetaMaritimaErro("timeout fora do limite")
    url = FONTES[fonte]["url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ColetaMaritimaErro("URL da fonte nao e HTTPS valida")
    request = Request(url, headers={
        "User-Agent": "NIVON/0.1 (+coleta publica; contato via repositorio)",
        "Accept": "text/html,application/xhtml+xml;q=0.9",
    })
    opener = transporte or build_opener(_SemRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ColetaMaritimaErro("HTTP nao confirmou pagina")
            final_url = getattr(response, "url", None) or response.geturl()
            if final_url != url:
                raise ColetaMaritimaErro("fonte redirecionou; revisao necessaria")
            mime = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
            if mime not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise ColetaMaritimaErro("tipo de resposta nao e HTML")
            content = response.read(MAX_HTML_BYTES + 1)
    except ColetaMaritimaErro:
        raise
    except Exception as exc:
        raise ColetaMaritimaErro("falha HTTP na fonte; verifique disponibilidade") from None
    if not content or len(content) > MAX_HTML_BYTES:
        raise ColetaMaritimaErro("pagina vazia ou excede limite de bytes")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Portais brasileiros antigos podem usar ISO-8859-1.
        return content.decode("iso-8859-1")


def _identidade(r):
    """DUV tem prioridade; sem DUV, a chave de escala e PROVISORIA."""
    if r.get("natureza") == "INFERIDO_AIS" and r.get("primeira_posicao"):
        key = [r.get("porto"), r.get("imo") or r.get("mmsi"), r["primeira_posicao"]]
        return "VISITA_AIS:" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:24], True
    duv = str(r.get("duv") or "").strip()
    if duv:
        return "DUV:" + duv, False
    vessel = str(r.get("imo") or r.get("mmsi") or r.get("navio") or "").strip().upper()
    berth = str(r.get("berco") or "-").strip().upper()
    ref = str(r.get("data_referencia") or "")
    month = ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            month = datetime.strptime(ref[:10], fmt).strftime("%Y-%m")
            break
        except ValueError:
            continue
    # Sem DUV, retornos do mesmo navio no mesmo mes podem colidir:
    # preservamos o historico; nao afirmamos contagem de escalas distintas.
    return "PROV:" + hashlib.sha256(
        json.dumps([r.get("porto"), vessel, berth, month], ensure_ascii=False).encode()
    ).hexdigest()[:24], True


def _revisao(r):
    payload = {k: v for k, v in r.items() if k not in ("coletado_em", "flags_qualidade")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HistoricoMaritimo:
    def __init__(self, caminho=":memory:"):
        self.con = sqlite3.connect(str(caminho))
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS capturas (
          fonte TEXT NOT NULL,
          hash_conteudo TEXT NOT NULL,
          primeiro_visto TEXT NOT NULL,
          ultimo_visto TEXT NOT NULL,
          quantidade INTEGER NOT NULL,
          qualidade TEXT NOT NULL,
          PRIMARY KEY (fonte, hash_conteudo)
        );
        CREATE TABLE IF NOT EXISTS revisoes (
          fonte TEXT NOT NULL,
          escala TEXT NOT NULL,
          revisao TEXT NOT NULL,
          primeiro_visto TEXT NOT NULL,
          conteudo_json TEXT NOT NULL,
          publicavel INTEGER NOT NULL,
          PRIMARY KEY (fonte, escala, revisao)
        );
        CREATE TABLE IF NOT EXISTS atuais (
          fonte TEXT NOT NULL,
          escala TEXT NOT NULL,
          revisao TEXT NOT NULL,
          visto_em TEXT NOT NULL,
          PRIMARY KEY (fonte, escala)
        );
        CREATE INDEX IF NOT EXISTS idx_revisoes_escala ON revisoes(fonte, escala);
        """)
    def fechar(self):
        self.con.close()

    def registrar(self, fonte, dados, registros, *, coletado_em, qualidade):
        coleta = _utc(coletado_em)
        digest = hashlib.sha256(dados if isinstance(dados, bytes) else dados.encode()).hexdigest()
        qtd = 0
        quarantena = bool(qualidade.get("quarentena", False))
        with self.con:
            self.con.execute("""
                INSERT INTO capturas VALUES (?,?,?,?,?,?)
                ON CONFLICT(fonte,hash_conteudo) DO UPDATE SET
                    ultimo_visto = excluded.ultimo_visto
                WHERE capturas.ultimo_visto < excluded.ultimo_visto
            """, (fonte, digest, coleta, coleta, len(registros), json.dumps(qualidade, sort_keys=True)))
            for entry in registros:
                r = dict(entry)
                escala, precaria = _identidade(r)
                if precaria:
                    r["flags_qualidade"] = sorted(set(r.get("flags_qualidade", [])) | {"IDENTIDADE_ESCALA_PROVISORIA"})
                if quarantena:
                    r["flags_qualidade"] = sorted(set(r.get("flags_qualidade", [])) | {"QUARENTENA_NAO_PUBLICAR"})
                rev = _revisao(r)
                publicavel = int(not quarantena and r.get("natureza") == "INFORMADO_PELA_FONTE")
                cur = self.con.execute(
                    "INSERT OR IGNORE INTO revisoes VALUES (?,?,?,?,?,?)",
                    (fonte, escala, rev, coleta, json.dumps(r, ensure_ascii=False, sort_keys=True), publicavel),
                )
                qtd += cur.rowcount
                if publicavel:
                    self.con.execute("""
                        INSERT INTO atuais VALUES (?,?,?,?)
                        ON CONFLICT(fonte,escala) DO UPDATE SET
                          revisao=excluded.revisao, visto_em=excluded.visto_em
                        WHERE atuais.visto_em <= excluded.visto_em
                    """, (fonte, escala, rev, coleta))
        return {"fonte": fonte, "captura_sha256": digest, "registros": len(registros),
                "revisoes_novas": qtd, "publicaveis": sum(
                    int(not quarantena and r.get("natureza") == "INFORMADO_PELA_FONTE") for r in registros
                ), "qualidade": qualidade}

    def atuais(self, fonte=None):
        query = """SELECT r.conteudo_json FROM atuais a
                   JOIN revisoes r ON r.fonte=a.fonte AND r.escala=a.escala AND r.revisao=a.revisao"""
        params = []
        if fonte:
            query += " WHERE a.fonte=?"
            params.append(fonte)
        return [json.loads(row[0]) for row in self.con.execute(query, params).fetchall()]

    def contagens(self):
        return {table: self.con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in ("capturas", "revisoes", "atuais")}


def processar_html(fonte, html, repositorio, *, coletado_em):
    coleta = _utc(coletado_em)
    if fonte not in HTML_AUTORIZADO:
        raise ColetaMaritimaErro("fonte fora do catalogo de HTML")
    registros = extrair_lineup_html(html, fonte, coletado_em=coleta)
    qualidade = {"quarentena": False, "flags": []}
    if not registros:
        qualidade = {"quarentena": True, "flags": ["PARSER_SEM_DADOS"]}
    elif fonte in CDP:
        quality = verificar_cdp(registros, corte=coleta[:10])
        # Divergencias conhecidas: nunca promover CDP sem comparador independente.
        qualidade = {"quarentena": True, "flags": sorted(set(quality["flags"]) | {"RECONCILIACAO_INDEPENDENTE_PENDENTE"})}
    return repositorio.registrar(fonte, html, registros, coletado_em=coleta, qualidade=qualidade)


def processar_ais_amaggi(eventos, repo, *, geocerca_auditada, coletado_em,
                         separar_intervalo_horas=8, min_pontos=3, min_permanencia_minutos=60):
    """Registra visitas AIS separadas, mas nao promove inferencia a embarque."""
    if not geocerca_auditada or len(geocerca_auditada) < 3:
        raise ColetaMaritimaErro("geocerca auditada ausente")
    by_ship = {}
    for e in eventos:
        try:
            ts = _utc(e["timestamp"])
        except (KeyError, ColetaMaritimaErro):
            continue
        by_ship.setdefault(str(e.get("imo") or e.get("mmsi") or ""), []).append((ts, dict(e)))
    result = []
    gap = timedelta(hours=separar_intervalo_horas)
    for _, seq in by_ship.items():
        seq.sort(key=lambda x: x[0])
        visits = []
        for ts, event in seq:
            when = datetime.fromisoformat(ts)
            if not visits or when - visits[-1][-1][0] > gap:
                visits.append([])
            visits[-1].append((when, event))
        for visit in visits:
            inferred = inferir_presenca_amaggi(
                [r for _, r in visit], geocerca_terminal=geocerca_auditada,
                min_pontos=min_pontos, min_permanencia_minutos=min_permanencia_minutos)
            for r in inferred:
                r["flags_qualidade"] = sorted(set(r["flags_qualidade"]) | {"ESCALA_AIS_NAO_CONFIRMADA"})
            result.extend(inferred)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
    summary = repo.registrar("itacoatiara_amaggi", payload, result, coletado_em=coletado_em,
                            qualidade={"quarentena": True, "flags": ["SOMENTE_INFERENCIA_AIS"]})
    return summary



def processar_gpv(texto_csv, repositorio, *, acesso_autorizado, coletado_em):
    """Importacao controlada do arquivo GPV da Vale; nunca inclui login."""
    coleta = _utc(coletado_em)
    records = importar_gpv_csv(texto_csv, acesso_autorizado=acesso_autorizado, coletado_em=coleta)
    flags = ["GPV_IMPORTACAO_MANUAL_COM_ORIGEM_DECLARADA"]
    if not records:
        flags.append("SEM_REGISTROS_VALIDOS")
    return repositorio.registrar(
        "ponta_madeira", texto_csv, records, coletado_em=coleta,
        qualidade={"quarentena": not bool(records), "flags": flags})


def normalizar_eventos_ais_nivon(eventos):
    """Aceita saida normalizada NIVON ou envelope AISStream com hora de recepcao.

    MMSI e identidade de radio; IMO precisa de crosswalk independente, nao e
    calculado a partir do MMSI. Sem timestamp do receptor, nao inventar tempo.
    """
    normalized = []
    for item in eventos:
        if not isinstance(item, dict):
            continue
        if "MessageType" in item:
            if item.get("MessageType") != "PositionReport":
                continue
            meta = item.get("MetaData") or {}
            msg = (item.get("Message") or {}).get("PositionReport") or {}
            mmsi = str(meta.get("MMSI") or "")
            if str(msg.get("UserID") or "") != mmsi or msg.get("Valid") is False:
                continue
            ts = item.get("recebido_em")
            record = {"mmsi":mmsi, "latitude":meta.get("Latitude"),
                      "longitude":meta.get("Longitude"), "timestamp":ts}
        else:
            record = dict(item)
        try:
            _utc(record.get("timestamp"))
            lat, lon = float(record["latitude"]), float(record["longitude"])
        except (ValueError, TypeError, KeyError, ColetaMaritimaErro):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if not (re.fullmatch(r"\\d{7}",str(record.get("imo") or "")) or
                re.fullmatch(r"\\d{9}",str(record.get("mmsi") or ""))):
            continue
        normalized.append(record)
    return normalized


def main(argv=None):
    p = argparse.ArgumentParser(description="NIVON: ingestao de line-up e historico local")
    p.add_argument("--fonte", choices=sorted(HTML_AUTORIZADO | {"ponta_madeira","itacoatiara_amaggi"}), required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--arquivo-html", type=Path)
    group.add_argument("--permitir-rede", action="store_true")
    group.add_argument("--arquivo-gpv-csv", type=Path)
    group.add_argument("--arquivo-ais-jsonl", type=Path)
    p.add_argument("--acesso-autorizado", action="store_true")
    p.add_argument("--geocerca-auditada-json", type=Path)
    p.add_argument("--banco", type=Path, required=True)
    args = p.parse_args(argv)
    db = HistoricoMaritimo(args.banco)
    try:
        when = agora_utc()
        if args.fonte in HTML_AUTORIZADO and (args.arquivo_html or args.permitir_rede):
            html = args.arquivo_html.read_text(encoding="utf-8") if args.arquivo_html else baixar_html(
                args.fonte, habilitar_rede=True)
            summary = processar_html(args.fonte, html, db, coletado_em=when)
        elif args.fonte == "ponta_madeira" and args.arquivo_gpv_csv:
            if not args.acesso_autorizado:
                raise PermissionError("arquivo GPV exige comprovacao de acesso autorizado")
            summary = processar_gpv(args.arquivo_gpv_csv.read_text(encoding="utf-8"),
                db, acesso_autorizado=True, coletado_em=when)
        elif args.fonte == "itacoatiara_amaggi" and args.arquivo_ais_jsonl:
            if not args.geocerca_auditada_json:
                raise ColetaMaritimaErro("arquivo de geocerca auditada obrigatorio")
            config = json.loads(args.geocerca_auditada_json.read_text(encoding="utf-8"))
            if config.get("estado") != "AUDITADA" or not config.get("evidencia"):
                raise ColetaMaritimaErro("geocerca sem auditoria e evidencia")
            polygon = [tuple(p) for p in config["poligono"]]
            lines = args.arquivo_ais_jsonl.read_text(encoding="utf-8").splitlines()
            if len(lines) > 100000:
                raise ColetaMaritimaErro("lote AIS ultrapassa limite")
            event_data = [json.loads(line) for line in lines if line.strip()]
            normalized = normalizar_eventos_ais_nivon(event_data)
            summary = processar_ais_amaggi(normalized,db,geocerca_auditada=polygon,coletado_em=when)
        else:
            raise ColetaMaritimaErro("formato de arquivo incompatível com fonte")
        print(json.dumps({**summary, "contagens_banco":db.contagens()},ensure_ascii=False))
        return 0 if not summary["qualidade"]["quarentena"] else 2
    finally:
        db.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
