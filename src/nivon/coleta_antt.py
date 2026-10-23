"""Coletor incremental SIADE/ANTT. Nunca grava em banco ou envia dados ao Github.

Staging local: fontes brutas, JSONL normalizado e manifesto com SHA.
Executar somente apos habilitacao explicita da rede; nao publica series.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .transporte_multimodal import (
    _SemRedirecionamento, ErroTransporte, interpretar_csv_antt
)

CATALOGO = "https://dados.antt.gov.br/api/3/action/package_show?id=438a5184-09db-49a3-88c8-0bad418b4409"
_CSV = re.compile(r"/dataset/438a5184-09db-49a3-88c8-0bad418b4409/resource/"
                  r"[0-9a-f-]{36}/download/producao_origem_destino_(20\d{2})\.csv\Z")


def _http(url: str, *, transporte=None, limite=16_000_000, timeout=25) -> bytes:
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "dados.antt.gov.br":
        raise ErroTransporte("URL externa")
    if url != CATALOGO and (p.query or not _CSV.fullmatch(p.path)):
        raise ErroTransporte("recurso fora do catalogo oficial")
    req = Request(url, headers={"Accept": "application/json" if url == CATALOGO else "text/csv"}, method="GET")
    opener = transporte or build_opener(_SemRedirecionamento)
    try:
        with opener.open(req, timeout=timeout) as resp:
            if getattr(resp, "status", None) != 200:
                raise ErroTransporte("ANTT HTTP != 200")
            raw = resp.read(limite + 1)
    except ErroTransporte:
        raise
    except Exception:
        raise ErroTransporte("acesso real ANTT nao validado") from None
    if not 1 <= len(raw) <= limite:
        raise ErroTransporte("resposta vazia/excessiva")
    return raw


def _ler_catalogo(raw: bytes) -> dict[int, dict]:
    if not isinstance(raw, bytes) or len(raw) > 3_000_000:
        raise ErroTransporte("catalogo invalido")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ErroTransporte("catalogo CKAN invalido") from None
    if not isinstance(obj, dict) or obj.get("success") is not True:
        raise ErroTransporte("catalogo CKAN sem sucesso")
    result = obj.get("result")
    if not isinstance(result, dict):
        raise ErroTransporte("resultado CKAN nao e objeto")
    resources = result.get("resources")
    if not isinstance(resources, list) or len(resources) > 200:
        raise ErroTransporte("lista de recursos inesperada")
    anos = {}
    for r in resources:
        if not isinstance(r, dict) or str(r.get("format", "")).upper() != "CSV":
            continue
        u = r.get("url")
        if not isinstance(u, str):
            continue
        p = urlsplit(u)
        if p.scheme != "https" or p.netloc != "dados.antt.gov.br" or p.query or p.fragment:
            continue
        m = _CSV.fullmatch(p.path)
        if m:
            ano = int(m[1])
            if not 2006 <= ano <= 2100 or ano in anos:
                raise ErroTransporte("ano duplicado/invalido CKAN")
            anos[ano] = {"url": u, "id": r.get("id"),
                         "last_modified": r.get("last_modified"),
                         "revision_id": r.get("revision_id")}
    if not anos:
        raise ErroTransporte("catalogo sem recursos anuais de OD")
    return dict(sorted(anos.items()))


def catalogo_antt(*, habilitar_rede=False, transporte=None) -> dict[int, dict]:
    if not habilitar_rede:
        raise PermissionError("consulta CKAN exige opt-in")
    return _ler_catalogo(_http(CATALOGO, transporte=transporte, limite=3_000_000))


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".nivon-", delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _manifest(path: Path) -> dict:
    if not path.is_file():
        return {"formato": "nivon-antt-staging-v1", "anos": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        raise ErroTransporte("manifesto invalido") from None
    if not isinstance(obj, dict) or obj.get("formato") != "nivon-antt-staging-v1" or not isinstance(obj.get("anos"), dict):
        raise ErroTransporte("manifesto com estrutura inesperada")
    return obj


def coletar(*, destino: str | Path, anos: list[int], habilitar_rede=False,
            transporte=None, revalidar_dias=7, agora: datetime | None = None) -> list[dict]:
    if not habilitar_rede:
        raise PermissionError("coleta bloqueada sem --live")
    if type(revalidar_dias) is not int or not 1 <= revalidar_dias <= 365:
        raise ErroTransporte("periodicidade invalida")
    if not anos or len(anos) != len(set(anos)) or any(type(a) is not int or a < 2006 for a in anos):
        raise ErroTransporte("anos invalidos")
    agora = agora or datetime.now(timezone.utc)
    if agora.tzinfo is None:
        raise ErroTransporte("agora precisa de fuso")
    stamp = agora.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    recursos = catalogo_antt(habilitar_rede=True, transporte=transporte)
    if any(a not in recursos for a in anos):
        raise ErroTransporte("ano nao publicado no CKAN")
    destino = Path(destino)
    path = destino / "manifesto-antt.json"
    manifesto = _manifest(path)
    saida = []
    for ano in sorted(anos):
        recurso = recursos[ano]
        prev = manifesto["anos"].get(str(ano), {})
        try:
            ultima = datetime.fromisoformat(str(prev.get("verificado_utc", "")).replace("Z", "+00:00"))
            vencido = agora - ultima >= timedelta(days=revalidar_dias)
        except ValueError:
            vencido = True
        integra = all((destino / f"antt-od-{ano}.{s}").is_file() for s in ("csv", "jsonl"))
        igual = (prev.get("revision_id") == recurso.get("revision_id") and
                 prev.get("last_modified") == recurso.get("last_modified") and
                 prev.get("url") == recurso["url"])
        if not vencido and igual and integra:
            saida.append({"ano": ano, "estado": "SEM_REVISAO", "registros": prev["registros"]})
            continue
        bruto = _http(recurso["url"], transporte=transporte)
        linhas, meta = interpretar_csv_antt(bruto, ano=ano, coleta_utc=stamp)
        jsonl = b"".join((json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n").encode() for x in linhas)
        _atomic(destino / f"antt-od-{ano}.csv", bruto)
        _atomic(destino / f"antt-od-{ano}.jsonl", jsonl)
        manifesto["anos"][str(ano)] = {
            **recurso, "sha256": hashlib.sha256(bruto).hexdigest(),
            "verificado_utc": stamp, "competencia_maxima": meta.referencia_maxima,
            "registros": meta.registros, "status": "STAGING_NAO_HOMOLOGADO"
        }
        _atomic(path, json.dumps(manifesto, ensure_ascii=False, sort_keys=True, indent=2).encode())
        saida.append({"ano": ano, "estado": "STAGING_NAO_HOMOLOGADO",
                      "competencia_maxima": meta.referencia_maxima,
                      "registros": meta.registros, "sha256": meta.arquivo_sha256})
    return saida


def main() -> int:
    p = argparse.ArgumentParser(description="NIVON — ingestao ANTT SIADE em staging")
    p.add_argument("--inicio", type=int, default=2025)
    p.add_argument("--fim", type=int, default=2026)
    p.add_argument("--destino", required=True)
    p.add_argument("--live", action="store_true")
    a = p.parse_args()
    if a.inicio > a.fim or a.fim - a.inicio > 30:
        p.error("periodo invalido")
    try:
        resultados = coletar(destino=a.destino, anos=list(range(a.inicio, a.fim + 1)),
                            habilitar_rede=a.live)
    except (ErroTransporte, PermissionError) as e:
        print(json.dumps({"estado": "NAO_VALIDADO", "erro": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps({"estado": "STAGING_NAO_HOMOLOGADO", "resultados": resultados}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
