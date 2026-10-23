"""Line-up nacional: escopo, normalização e consolidação offline, sem inventar dados.

Fontes oficiais, licenças e adaptadores específicos são homologados separadamente.
Uma observação de line-up não é prova de operação ou de carga realizada.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REGISTRO = Path(__file__).resolve().parents[2] / "config" / "lineup_escopo_nacional.v1.json"
SITUACOES = {"ESPERADO", "PROGRAMADO", "AO_LARGO", "ATRACADO", "OPERANDO",
             "DESPACHADO", "CONCLUIDO", "REALIZADO"}
EVIDENCIAS = {"LINEUP_INFORMADO", "EVENTO_FISICO_VERIFICADO", "CARGA_MOVIMENTADA_OFICIAL"}
SITUACAO_FISICA = {"ATRACADO", "OPERANDO", "DESPACHADO", "CONCLUIDO"}
ALIASES = {
    "SOJA": "SOJA", "SOJA EM GRAOS": "SOJA", "SOJA EM GRAOS.": "SOJA",
    "MILHO": "MILHO", "MILHO EM GRAOS": "MILHO",
    "FARELO DE SOJA": "FARELO_SOJA", "FARELO_SOJA": "FARELO_SOJA",
    "OLEO DE SOJA": "OLEO_SOJA", "ACUCAR": "ACUCAR", "ACUCAR VHP": "ACUCAR",
    "ALGODAO": "ALGODAO", "ALGODAO EM PLUMA": "ALGODAO",
    "UREIA": "FERTILIZANTES", "KCL": "FERTILIZANTES", "MAP": "FERTILIZANTES",
    "DAP": "FERTILIZANTES", "FERTILIZANTES": "FERTILIZANTES",
    "DIESEL": "DIESEL", "DIESEL S10": "DIESEL", "ETANOL": "ETANOL",
    "TRIGO": "TRIGO", "SORGO": "SORGO", "FRANGO CONGELADO": "FRANGO",
    "SUINOS": "SUINO", "SUINO": "SUINO", "CARNE SUINA": "SUINO",
    "FRANGO": "FRANGO", "CARNE DE FRANGO": "FRANGO",
    "GERGELIM": "GERGELIM",
}


class ErroLineupNacional(ValueError):
    pass


def instante(valor: str) -> datetime:
    if not isinstance(valor, str) or "T" not in valor:
        raise ErroLineupNacional("timestamp ISO completo com horário e fuso obrigatório")
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErroLineupNacional("timestamp inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroLineupNacional("timezone obrigatório")
    return dt


def carregar_escopo(path: Path = REGISTRO) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ErroLineupNacional("manifesto ausente, symlink ou excessivo")
    doc = json.loads(path.read_text(encoding="utf-8"))
    ports = doc.get("ports")
    if doc.get("project") != "NIVON" or not isinstance(ports, list):
        raise ErroLineupNacional("manifesto inválido")
    ids = [p["id"] for p in ports]
    organizados = [p for p in ports if p.get("kind") == "PORTO_ORGANIZADO"]
    if len(organizados) != 35 or len(ids) != len(set(ids)):
        raise ErroLineupNacional("35 portos organizados e IDs únicos obrigatórios")
    for p in ports:
        if p.get("live_enabled") is not False or p.get("parser_homologated") is not False:
            raise ErroLineupNacional("catálogo não autoriza declarar coleta homologada")
        if p.get("parent_port_id") and p["parent_port_id"] not in ids:
            raise ErroLineupNacional("terminal com porto pai desconhecido")
    return doc


def produto_canonico(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ErroLineupNacional("mercadoria ausente")
    chave = " ".join(raw.strip().upper().split())
    return ALIASES.get(chave, "OUTROS")


def normalizar_linha(row: dict, escopo: dict) -> dict:
    """Validação de linha previamente extraída por parser de fonte autorizada."""
    if not isinstance(row, dict):
        raise ErroLineupNacional("observação não é objeto")
    port_id = str(row.get("porto_id", "")).strip()
    if port_id not in {p["id"] for p in escopo["ports"]}:
        raise ErroLineupNacional("porto não cadastrado")
    status = str(row.get("situacao", "")).upper().strip()
    evidence = str(row.get("classe_evidencia", "")).upper().strip()
    if status not in SITUACOES or evidence not in EVIDENCIAS:
        raise ErroLineupNacional("situação ou evidência desconhecida")
    if evidence == "LINEUP_INFORMADO" and status in {"OPERANDO", "CONCLUIDO", "REALIZADO"}:
        raise ErroLineupNacional("line-up não comprova operação realizada")
    if status == "REALIZADO" and evidence != "CARGA_MOVIMENTADA_OFICIAL":
        raise ErroLineupNacional("realizado exige evidência de carga oficial")
    if status in {"ESPERADO", "PROGRAMADO", "AO_LARGO"} and evidence != "LINEUP_INFORMADO":
        raise ErroLineupNacional("previsão não é observação física")
    duv = str(row.get("duv") or "").strip()
    navio = str(row.get("navio") or "").strip()
    if not navio or not re.fullmatch(r"[A-Za-z0-9Á-ú ._/'-]{2,150}", navio):
        raise ErroLineupNacional("navio inválido")
    fonte = str(row.get("fonte_url") or "")
    if not fonte.startswith("https://") or "@" in fonte:
        raise ErroLineupNacional("fonte URL HTTPS obrigatória")
    publicado = instante(row.get("publicado_em"))
    coletado = instante(row.get("coletado_em"))
    if publicado > coletado:
        raise ErroLineupNacional("publicação posterior à coleta")
    previsto = row.get("toneladas_programadas")
    realizado = row.get("toneladas_realizadas")
    for nome, value in (("toneladas_programadas", previsto), ("toneladas_realizadas", realizado)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or value < 0 or value != value):
            raise ErroLineupNacional(nome + " inválidas")
    if status == "REALIZADO" and realizado is None:
        raise ErroLineupNacional("carga realizada exige tonelagem comprovada")
    if evidence != "CARGA_MOVIMENTADA_OFICIAL" and realizado is not None:
        raise ErroLineupNacional("tonelagem realizada sem evidência")
    return {
        "porto_id": port_id, "duv": duv or None, "navio": navio,
        "imo": str(row.get("imo") or "").strip() or None,
        "produto": produto_canonico(row.get("produto")),
        "produto_original": row["produto"], "situacao": status,
        "classe_evidencia": evidence, "toneladas_programadas": previsto,
        "toneladas_realizadas": realizado, "lote_id": str(row.get("lote_id") or "").strip() or None,
        "fonte_url": fonte, "publicado_em": publicado.isoformat(),
        "coletado_em": coletado.isoformat(),
    }


def consolidar(rows: list[dict], escopo: dict) -> dict:
    """Resumo por porto, produto, situação sem somar escala duplicada.

    DUV/escala identifica navio; lote_id, se houver, diferencia cargas.
    Falta de DUV ou lote_id mantém incerteza na soma de tonelagens.
    """
    grupos: dict[tuple[str, str, str], dict] = defaultdict(lambda: {
        "escalas_ids": set(), "linhas_sem_duv": 0,
        "toneladas_programadas": 0., "toneladas_realizadas": 0.,
        "registros_com_volume_desconhecido": 0
    })
    vistos: dict[tuple, dict] = {}
    for raw in rows:
        r = normalizar_linha(raw, escopo)
        chave_carga = (r["porto_id"], r["duv"], r["produto"], r["lote_id"], r["situacao"])
        if r["duv"] and chave_carga in vistos:
            if vistos[chave_carga] != r:
                raise ErroLineupNacional("escala/lote duplicado com dados conflitantes")
            continue
        if r["duv"]:
            vistos[chave_carga] = r
        chave = (r["porto_id"], r["produto"], r["situacao"])
        g = grupos[chave]
        if r["duv"]:
            g["escalas_ids"].add(r["duv"])
        else:
            g["linhas_sem_duv"] += 1
        valor = r["toneladas_realizadas"] if r["situacao"] == "REALIZADO" else r["toneladas_programadas"]
        if valor is None:
            g["registros_com_volume_desconhecido"] += 1
        elif r["duv"] and r["lote_id"]:
            g["toneladas_realizadas" if r["situacao"] == "REALIZADO" else "toneladas_programadas"] += valor
        else:
            # Sem ID do lote, não somar volumes: pode ser repetição da mesma carga.
            g["registros_com_volume_desconhecido"] += 1
    resultado = []
    for (porto, produto, situacao), g in sorted(grupos.items()):
        resultado.append({
            "porto_id": porto, "produto": produto, "situacao": situacao,
            "escalas_distintas_identificadas": len(g["escalas_ids"]),
            "linhas_sem_duv": g["linhas_sem_duv"],
            "toneladas_programadas_sem_duplicacao": g["toneladas_programadas"],
            "toneladas_realizadas_sem_duplicacao": g["toneladas_realizadas"],
            "volumes_nao_conciliaveis": g["registros_com_volume_desconhecido"],
        })
    return {"grupos": resultado, "linhas_entrada": len(rows),
            "aviso": "Contagem de escalas por DUV; movimentação só com evidência oficial; dados não homologados"}
