"""Entrada manual OFFLINE de ofertas de frete vindas de export autorizado.

O JSONL não é prova de direitos/consentimento nem substitui o adaptador
atestado WhatsApp AI -> NIVON. Não faz rede nem acessa Google Cloud.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Sequence

from .fretes_registros import OfertaFrete, ErroRegistroFrete


CAMPOS_OFERTA = frozenset(OfertaFrete.__dataclass_fields__)
DECIMAIS = ("frete_base_brl_t", "pedagio_brl_t", "frete_cheio_brl_t")
DATAS = ("data_referencia",)
HORARIOS = ("data_publicacao", "data_coleta")


def carregar_ofertas_frete_jsonl(
    caminho: str | Path, *, max_registros: int = 10000,
    max_bytes: int = 20_000_000,
) -> list[OfertaFrete]:
    """Carrega arquivos locais estritos sem macros, rede ou execução de scripts.

    Nenhum flag de licença/RAW validado é emitido; origem deve ser aprovada em
    separado e os retornos ficam bloqueados para publicação.
    """
    p=Path(caminho)
    if (p.is_symlink() or not p.is_file() or p.suffix.lower() != ".jsonl"
            or not 1 <= max_registros <= 10000 or not 1 <= max_bytes <= 20_000_000
            or p.stat().st_size > max_bytes):
        raise ErroRegistroFrete("arquivo JSONL local inválido, inseguro ou excessivo")
    saida=[]
    with p.open("r",encoding="utf-8") as f:
        for n,linha in enumerate(f,1):
            if n > max_registros:
                raise ErroRegistroFrete("limite de registros JSONL excedido")
            if len(linha.encode("utf-8")) > 65536 or not linha.strip():
                raise ErroRegistroFrete(f"linha JSONL inválida na posição {n}")
            try:
                def proibir_constante(v):
                    raise ValueError("NaN/Infinity não permitido")
                obj=json.loads(linha,parse_constant=proibir_constante)
                if not isinstance(obj,dict) or set(obj) != CAMPOS_OFERTA:
                    raise ValueError("colunas inconsistentes")
                dados={}
                for k,v in obj.items():
                    if k in DECIMAIS:
                        if v is not None and (type(v) is not str or len(v) > 42):
                            raise ValueError("valor decimal não é texto")
                        dados[k]=Decimal(v) if v is not None else None
                    elif k in DATAS:
                        if type(v) is not str or len(v) != 10:
                            raise ValueError("data não canônica")
                        parsed=date.fromisoformat(v)
                        if parsed.isoformat()!=v:
                            raise ValueError("data não canônica")
                        dados[k]=parsed
                    elif k in HORARIOS:
                        if type(v) is not str or len(v)>50:
                            raise ValueError("timestamp inválido")
                        hora=datetime.fromisoformat(v.replace("Z","+00:00"))
                        if hora.tzinfo is None or hora.utcoffset() is None:
                            raise ValueError("timestamp sem timezone")
                        dados[k]=hora
                    else:
                        if type(v) is not str:
                            raise ValueError("identificador não textual")
                        dados[k]=v
                saida.append(OfertaFrete(**dados))
            except (ValueError,TypeError,KeyError,InvalidOperation) as exc:
                raise ErroRegistroFrete(f"erro na linha JSONL {n}: contrato inválido") from exc
    if not saida:
        raise ErroRegistroFrete("JSONL vazio não constitui histórico")
    ids=[x.registro_id for x in saida]
    if len(set(ids)) != len(ids):
        raise ErroRegistroFrete("registro_id duplicado no JSONL; resolver antes de importar")
    return saida
