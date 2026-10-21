"""Catálogo e importação auditável de cotações autorizadas.

Não coleta widgets ou conteúdo de terceiros automaticamente.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode

BASE = Path(__file__).resolve().parents[1]
CATALOGO = BASE / "catalogo/widgets_noticias_agricolas.json"
CATEGORIAS = {"algodao": 6, "bovinos": 10, "cafe": 4, "financeiro": 3,
              "milho": 5, "soja": 10, "sucroenergetico": 4}
TIPOS = {"fisico", "futuro", "reposicao", "indice_fisico", "cambio", "premio"}
CLASSIFICACOES = {"OBSERVADO", "INFORMADO", "ESTIMADO", "INFERIDO", "PROJETADO", "SINTETICO"}
COLUNAS = ("id_widget", "instrumento", "praca", "vencimento", "valor", "unidade",
           "data_referencia", "data_publicacao", "data_coleta", "competencia",
           "classificacao", "fonte_original")


def carregar_catalogo(caminho: Path = CATALOGO) -> dict:
    cat = json.loads(Path(caminho).read_text(encoding="utf-8"))
    ids = [x["id"] for x in cat["indicadores"]]
    if len(ids) != len(set(ids)):
        raise ValueError("ID de widget duplicado")
    if len(ids) != 42:
        raise ValueError(f"Esperados 42 widgets, recebidos {len(ids)}")
    for categoria, esperado in CATEGORIAS.items():
        if sum(x["categoria"] == categoria for x in cat["indicadores"]) != esperado:
            raise ValueError(f"Quantidade inválida em {categoria}")
    for x in cat["indicadores"]:
        if not isinstance(x["id"], int) or x["id"] <= 0 or x["tipo"] not in TIPOS:
            raise ValueError(f"Metadados inválidos em {x}")
    if cat["permissoes"]["coleta_automatizada"] != "NAO_COMPROVADA":
        raise ValueError("Catalogação não autoriza coleta")
    return cat


def url_incorporacao(id_widget: int, catalogo: dict) -> str:
    """Somente URL de apresentação; NUNCA usar para coleta automatizada."""
    if id_widget not in {x["id"] for x in catalogo["indicadores"]}:
        raise ValueError("Widget não cadastrado")
    return "https://www.noticiasagricolas.com.br/widgets/cotacoes?" + urlencode({
        "id": id_widget, "fonte": "Arial, Helvetica, sans-serif", "tamanho": "10pt",
        "largura": "400px", "cortexto": "333333", "corcabecalho": "B2C3C6",
        "corlinha": "DCE7E9", "imagem": "false", "output": "js"})


def validar_permissao(permissao: dict | None, sintetico: bool) -> None:
    if sintetico:
        return
    if not permissao or not all([
        permissao.get("coleta_autorizada") is True,
        permissao.get("armazenamento_autorizado") is True,
        permissao.get("identificador_autorizacao"),
        permissao.get("responsavel_validacao"),
        permissao.get("fonte") == "Noticias Agricolas",
    ]):
        raise PermissionError("Coleta/armazenamento bloqueados: autorização verificável ausente")


def normalizar(linha: dict, catalogo: dict, sintetico: bool) -> dict:
    if set(COLUNAS) - linha.keys():
        raise ValueError(f"Campos faltantes: {sorted(set(COLUNAS) - linha.keys())}")
    row = {k: linha[k] for k in COLUNAS}
    if isinstance(row["id_widget"], bool) or not isinstance(row["id_widget"], int):
        raise ValueError("id_widget deve ser inteiro")
    if row["id_widget"] not in {x["id"] for x in catalogo["indicadores"]}:
        raise ValueError("Widget desconhecido")
    for campo in ("instrumento", "unidade", "fonte_original"):
        if not isinstance(row[campo], str) or not row[campo].strip():
            raise ValueError(f"Campo {campo} vazio")
    for campo in ("praca", "vencimento"):
        if row[campo] is not None and not isinstance(row[campo], str):
            raise ValueError(f"Campo {campo} inválido")
    try:
        valor = Decimal(str(row["valor"]))
        if not valor.is_finite():
            raise ValueError("Valor não finito")
    except (InvalidOperation, TypeError) as e:
        raise ValueError("Valor decimal inválido") from e
    row["valor"] = format(valor, "f")
    try:
        ref = date.fromisoformat(row["data_referencia"])
        pub = datetime.fromisoformat(row["data_publicacao"])
        coleta = datetime.fromisoformat(row["data_coleta"])
    except (TypeError, ValueError) as e:
        raise ValueError("Datas precisam estar no formato ISO 8601") from e
    if pub.tzinfo is None or coleta.tzinfo is None:
        raise ValueError("Publicação e coleta precisam de fuso explícito")
    if not isinstance(row["competencia"], str) or row["competencia"] != ref.strftime("%Y-%m"):
        raise ValueError("Competência precisa corresponder à data de referência (AAAA-MM)")
    if row["classificacao"] not in CLASSIFICACOES:
        raise ValueError("Classificação inválida")
    if sintetico != (row["classificacao"] == "SINTETICO"):
        raise ValueError("Flag sintético precisa coincidir com a classificação")
    if coleta < pub:
        raise ValueError("Coleta anterior à publicação")
    return row


def iniciar_banco(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS cotacoes (
        hash_registro TEXT PRIMARY KEY, chave_serie TEXT NOT NULL,
        id_widget INTEGER NOT NULL, instrumento TEXT NOT NULL, praca TEXT,
        vencimento TEXT, valor TEXT NOT NULL, unidade TEXT NOT NULL,
        data_referencia TEXT NOT NULL, data_publicacao TEXT NOT NULL,
        data_coleta TEXT NOT NULL, competencia TEXT NOT NULL,
        classificacao TEXT NOT NULL, fonte_original TEXT NOT NULL,
        identificador_autorizacao TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cotacoes_ref ON cotacoes(id_widget, data_referencia)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_cotacoes_serie ON cotacoes(chave_serie, data_coleta)")


def importar(caminho: Path, banco: Path | str, *, sintetico: bool = False,
             caminho_permissao: Path | None = None, catalogo: dict | None = None) -> dict:
    catalogo = catalogo or carregar_catalogo()
    permissao = json.loads(Path(caminho_permissao).read_text(encoding="utf-8")) if caminho_permissao else None
    validar_permissao(permissao, sintetico)
    documento = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if not isinstance(documento, list):
        raise ValueError("O arquivo precisa ser uma lista JSON de observações")
    linhas = [normalizar(item, catalogo, sintetico) for item in documento]
    inseridos = 0
    with sqlite3.connect(str(banco)) as con:
        iniciar_banco(con)
        for row in linhas:
            chave = {k: row[k] for k in ("id_widget", "instrumento", "praca", "vencimento", "data_referencia", "fonte_original")}
            chave_serie = hashlib.sha256(json.dumps(chave, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            registro = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            dados = [registro, chave_serie, *(row[k] for k in COLUNAS),
                     None if sintetico else permissao["identificador_autorizacao"]]
            cur = con.execute("INSERT OR IGNORE INTO cotacoes (hash_registro, chave_serie, "
                + ", ".join(COLUNAS) + ", identificador_autorizacao) VALUES (" + ", ".join("?" for _ in dados) + ")", dados)
            inseridos += cur.rowcount
    return {"recebidos": len(linhas), "inseridos": inseridos,
            "duplicados": len(linhas) - inseridos, "modo": "SINTETICO" if sintetico else "AUTORIZADO"}


def main() -> None:
    parser = argparse.ArgumentParser(description="NIVON — catálogo e ingestão controlada de cotações")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("validar-catalogo")
    url = sub.add_parser("url-widget")
    url.add_argument("id", type=int)
    imp = sub.add_parser("importar")
    imp.add_argument("--arquivo", type=Path, required=True)
    imp.add_argument("--banco", type=Path, required=True)
    imp.add_argument("--sintetico", action="store_true")
    imp.add_argument("--permissao", type=Path)
    args = parser.parse_args()
    cat = carregar_catalogo()
    if args.comando == "validar-catalogo":
        print(json.dumps({"status": "VALIDADO", "quantidade": len(cat["indicadores"]),
                          "categorias": CATEGORIAS}, ensure_ascii=False))
    elif args.comando == "url-widget":
        print(url_incorporacao(args.id, cat))
    elif args.comando == "importar":
        print(json.dumps(importar(args.arquivo, args.banco, sintetico=args.sintetico,
               caminho_permissao=args.permissao, catalogo=cat), ensure_ascii=False))


if __name__ == "__main__":
    main()
