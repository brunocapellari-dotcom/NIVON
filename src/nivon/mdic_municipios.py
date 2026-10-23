"""CSV municipal SH4 do Comex Stat, importação/exportação, apenas parser offline.

O município é DOMICÍLIO FISCAL da empresa. Jamais é origem da carga,
destino físico, porto, fazenda, ou observação por NCM de oito dígitos.
"""
from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CABECALHO = ("CO_ANO", "CO_MES", "SH4", "CO_PAIS", "SG_UF_MUN",
             "CO_MUN", "KG_LIQUIDO", "VL_FOB")
_UFS = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())


class ErroMDICMunicipios(ValueError):
    pass


def _int(campo: str, nome: str) -> int:
    if not isinstance(campo, str) or not re.fullmatch(r"\d+", campo.strip()):
        raise ErroMDICMunicipios(f"{nome}: inteiro não negativo obrigatório")
    return int(campo)


def resumir_municipios_sh4(caminho: str | Path, *, direcao: str,
                           posicoes_sh4: frozenset[str],
                           limite_bytes: int = 75_000_000,
                           limite_linhas: int = 2_000_000) -> dict:
    """Importa CSV local autorizado, filtra SH4 e agrega por domicilio fiscal.

    Somente um arquivo do tipo municipal, que nao compartilha chaves ou
    significado com base NCM/UF. Não valida presença histórica de município.
    """
    if direcao not in ("EXPORTACAO", "IMPORTACAO"):
        raise ErroMDICMunicipios("direção não homologada")
    if (not isinstance(posicoes_sh4, frozenset) or not posicoes_sh4 or
            any(not isinstance(x, str) or not re.fullmatch(r"\d{4}", x)
                for x in posicoes_sh4)):
        raise ErroMDICMunicipios("lista SH4 de quatro dígitos obrigatória")
    if type(limite_bytes) is not int or not 0 < limite_bytes <= 100_000_000:
        raise ErroMDICMunicipios("limite de bytes inválido")
    if type(limite_linhas) is not int or not 0 < limite_linhas <= 5_000_000:
        raise ErroMDICMunicipios("limite de linhas inválido")
    p = Path(caminho)
    if p.is_symlink() or not p.is_file() or p.suffix.lower() != ".csv":
        raise ErroMDICMunicipios("CSV local regular obrigatório")
    if not 0 < p.stat().st_size <= limite_bytes:
        raise ErroMDICMunicipios("CSV vazio ou grande demais")
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(262144), b""):
            h.update(b)
    agregados = defaultdict(lambda: [0, 0, 0])
    linhas = filtradas = 0
    try:
        with p.open("r", encoding="utf-8-sig", newline="", errors="strict") as f:
            rd = csv.DictReader(f, delimiter=";")
            if tuple(rd.fieldnames or ()) != CABECALHO:
                raise ErroMDICMunicipios("layout oficial SH4 municipal alterado")
            for x in rd:
                linhas += 1
                if linhas > limite_linhas:
                    raise ErroMDICMunicipios("limite de linhas excedido")
                if None in x or any(x.get(c) is None for c in CABECALHO):
                    raise ErroMDICMunicipios("linha desalinhada")
                sh4 = x["SH4"].strip()
                if not re.fullmatch(r"\d{4}", sh4):
                    raise ErroMDICMunicipios("SH4 inválido")
                if sh4 not in posicoes_sh4:
                    continue
                ano, mes = _int(x["CO_ANO"], "ano"), _int(x["CO_MES"], "mês")
                if not 1997 <= ano <= 2100 or not 1 <= mes <= 12:
                    raise ErroMDICMunicipios("competência incorreta")
                uf = x["SG_UF_MUN"].strip().upper()
                cod = x["CO_MUN"].strip()
                pais = x["CO_PAIS"].strip()
                if not re.fullmatch(r"[A-Z]{2}", uf):
                    raise ErroMDICMunicipios("UF declarada incorreta")
                if not re.fullmatch(r"\d{1,7}", cod) or not re.fullmatch(r"\d{1,3}", pais):
                    raise ErroMDICMunicipios("município/país fiscal inválido")
                kg = _int(x["KG_LIQUIDO"], "KG_LIQUIDO")
                usd = _int(x["VL_FOB"], "VL_FOB")
                chave = (f"{ano:04d}-{mes:02d}", sh4, uf, cod.zfill(7), pais.zfill(3))
                a = agregados[chave]
                a[0] += kg
                a[1] += usd
                a[2] += 1
                filtradas += 1
    except UnicodeError as exc:
        raise ErroMDICMunicipios("CSV fora de UTF-8") from exc
    if not filtradas:
        raise ErroMDICMunicipios("sem SH4 solicitado; não reportar zero")
    saida = []
    for (competencia, sh4, uf, cod, pais), (kg, usd, linhas_agregadas) in sorted(agregados.items()):
        saida.append({
            "competencia": competencia, "sh4": sh4, "uf_domicilio_fiscal": uf,
            "codigo_municipio_declarado": cod, "pais": pais,
            "uf_brasileira": uf in _UFS,
            "codigo_ibge_nao_validado": True,
            "peso_kg": kg, "toneladas": kg / 1000,
            "valor_fob_usd": usd, "valor_medio_usd_t": usd * 1000 / kg if kg else None,
            "linhas_agregadas": linhas_agregadas,
            "natureza": "ESTATISTICA_COMEX_MUNICIPIO_FISCAL",
        })
    return {
        "dataset_id": "MDIC_COMEX_MUNICIPIO_SH4", "direcao": direcao,
        "sha256_original": h.hexdigest(),
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        "linhas_total": linhas, "linhas_filtradas": filtradas,
        "recortes": saida, "status": "PARSER_LOCAL_SEM_COLETA_AUTOMATICA",
        "limite_semantico": "domicilio fiscal da empresa; SH4, não NCM, embarque ou consumo",
    }
