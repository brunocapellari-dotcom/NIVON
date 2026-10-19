"""Parser ANP PPI (XLSX) com layout declarado, sem adivinhar colunas.

Fonte: ANP publica PPI estimado por S&P Global Commodity Insights.
A planilha NÃO é preço de bomba ou transação física realizada; nunca confrontar
automaticamente com preço do produtor sem reconciliação tributária e temporal.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime
from zipfile import BadZipFile, ZipFile

from .lineup_nacional import instante


class ErroPPI(ValueError):
    pass


@dataclass(frozen=True)
class LayoutPPI:
    aba: str
    produto: str
    cabecalho_linha: int
    coluna_data: str
    colunas_pontos: dict[str, str]
    unidade: str = "BRL/L"

    def __post_init__(self):
        if self.produto not in {"DIESEL_S10", "GASOLINA_A", "QAV", "GLP"}:
            raise ErroPPI("produto desconhecido")
        if self.unidade not in {"BRL/L", "BRL/KG", "BRL/13KG"}:
            raise ErroPPI("unidade desconhecida")
        if not self.aba or not self.coluna_data or not 1 <= self.cabecalho_linha <= 40:
            raise ErroPPI("layout incompleto")
        if not self.colunas_pontos or len(set(self.colunas_pontos.values())) != len(self.colunas_pontos):
            raise ErroPPI("pontos duplicados ou ausentes")


def _data(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                pass
    raise ErroPPI("data semanal fora do formato")


def ler_ppi_xlsx(
    payload: bytes, layout: LayoutPPI, *, publicado_em: str,
    coletado_em: str, fonte_url: str,
) -> list[dict]:
    """Retorna pontos ANP por semana, local e produto, sob direitos ainda sujeitos a gate."""
    if not isinstance(payload, bytes) or len(payload) > 12_000_000 or not payload.startswith(b"PK"):
        raise ErroPPI("arquivo XLSX inválido ou grande demais")
    try:
        with ZipFile(io.BytesIO(payload)) as arq:
            if len(arq.infolist()) > 400 or sum(x.file_size for x in arq.infolist()) > 70_000_000:
                raise ErroPPI("expansão XLSX excessiva")
            if any(x.filename.lower().endswith(("vbaproject.bin", ".exe", ".dll")) for x in arq.infolist()):
                raise ErroPPI("arquivo com conteúdo executável")
    except BadZipFile as exc:
        raise ErroPPI("XLSX corrompido") from exc
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ErroPPI("instale nivon[excel] para ler PPI") from exc

    pub = instante(publicado_em)
    col = instante(coletado_em)
    if pub > col:
        raise ErroPPI("data de publicação após coleta")
    if not fonte_url.startswith("https://www.gov.br/anp/"):
        raise ErroPPI("fonte ANP incompatível")
    wb = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        if layout.aba not in wb.sheetnames:
            raise ErroPPI("aba esperada não localizada")
        ws = wb[layout.aba]
        if ws.max_column > 70 or ws.max_row > 6000:
            raise ErroPPI("tabela excede tamanho esperado")
        rows = ws.iter_rows(values_only=True)
        header = None
        for pos, row in enumerate(rows, start=1):
            if pos == layout.cabecalho_linha:
                header = [str(x).strip() if x is not None else "" for x in row]
                break
        if header is None or len(header) != len(set(x for x in header if x)):
            raise ErroPPI("cabeçalho repetido ou não localizado")
        wanted = [layout.coluna_data, *layout.colunas_pontos.values()]
        if any(x not in header for x in wanted):
            raise ErroPPI("colunas ANP não correspondem ao layout homologado")
        idx_data = header.index(layout.coluna_data)
        indices = {local: header.index(name) for local, name in layout.colunas_pontos.items()}
        output = []
        keys = set()
        for row in rows:
            if not row or all(x in (None, "") for x in row):
                continue
            data = _data(row[idx_data])
            if data > col.date():
                raise ErroPPI("semana futura")
            for local, idx in indices.items():
                valor = row[idx] if idx < len(row) else None
                if valor in (None, ""):
                    continue
                if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0 < valor < 100_000:
                    raise ErroPPI("preço numérico PPI inconsistente")
                key = (data, local, layout.produto)
                if key in keys:
                    raise ErroPPI("edição PPI com mesma semana/local duplicado")
                keys.add(key)
                output.append({
                    "fonte": "ANP_PPI", "classe": "ESTIMATIVA_PUBLICADA",
                    "produto": layout.produto, "ponto_entrega": local,
                    "preco_paridade": float(valor), "unidade": layout.unidade,
                    "data_referencia": data.isoformat(), "data_publicacao": pub.isoformat(),
                    "data_coleta": col.isoformat(), "url": fonte_url,
                    "tributos_inclusos": False,
                })
        if not output:
            raise ErroPPI("tabela ANP sem observações")
        return output
    finally:
        wb.close()


def comparar_ppi_com_produtor(ppi: dict, produtor: dict, *, imposto_federal_brl_unidade: float | None) -> dict:
    """Só compara preço do produtor quando calendário/unidade/tributos são harmonizados."""
    if imposto_federal_brl_unidade is None or imposto_federal_brl_unidade < 0:
        raise ErroPPI("tributação vigente e verificada obrigatória")
    if ppi["produto"] != produtor.get("produto") or ppi["unidade"] != produtor.get("unidade"):
        raise ErroPPI("produto ou unidade diferentes")
    if ppi["data_referencia"] != produtor.get("data_referencia"):
        raise ErroPPI("semanas não comparáveis")
    interno_sem_federal = float(produtor["preco_produtor"]) - imposto_federal_brl_unidade
    if interno_sem_federal <= 0:
        raise ErroPPI("preço tributário incompatível")
    spread = interno_sem_federal - float(ppi["preco_paridade"])
    return {"produto": ppi["produto"], "referencia": ppi["data_referencia"],
            "spread_interno_menos_paridade": round(spread, 6),
            "base": "MESMA_SEMANA_UNIDADE_E_TRIBUTOS_FEDERAIS_DEDUZIDOS",
            "nao_e_margem_de_lucro": True}
