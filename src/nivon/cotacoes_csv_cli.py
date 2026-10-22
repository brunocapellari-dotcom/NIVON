"""CLI OFFLINE de importacao supervisionada CEPEA/IMEA.

Manifesto e arquivo CSV preexistentes; sem aquisicao HTTP nem publicação.
O manifesto não comprova titularidade nem concede direito de reuso.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

from .historico_vintages import ArmazemVintages
from .importacao_cotacoes_autorizadas import (
    normalizar_arquivo_cotacoes, persistir_quarentena, ErroImportacaoCotacoes,
)

_CAMPOS = frozenset({
    "fonte_id", "fonte_url", "edicao_id", "coletado_em", "publicado_em",
    "disponivel_em", "arquivo_csv",
})
_ARQUIVO = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}\\Z")

class ErroCLIImportacao(ValueError):
    pass

def _arquivo_seguro(pasta: Path, nome: str, *, existente: bool) -> Path:
    if (not isinstance(nome, str) or nome in (".", "..")
            or not _ARQUIVO.fullmatch(nome)):
        raise ErroCLIImportacao("nome de arquivo deve ser simples e local")
    alvo = pasta / nome
    if alvo.is_symlink() or (existente and not alvo.is_file()) or (
        not existente and alvo.exists() and not alvo.is_file()
    ):
        raise ErroCLIImportacao("arquivo ausente ou nao regular")
    return alvo

def executar_importacao(*, manifesto: Path, persistir: bool = False,
                       banco: str | None = None) -> dict:
    if persistir is not True and banco is not None:
        raise ErroCLIImportacao("banco so pode ser informado com persistencia")
    if persistir and banco is None:
        raise ErroCLIImportacao("persistencia exige nome de banco")
    m = Path(manifesto)
    if m.is_symlink() or not m.is_file() or not 0 < m.stat().st_size < 20_000:
        raise ErroCLIImportacao("manifesto JSON regular obrigatorio")
    try:
        doc = json.loads(m.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ErroCLIImportacao("manifesto nao e JSON") from exc
    if not isinstance(doc, dict) or not set(doc) <= _CAMPOS or not _CAMPOS <= set(doc):
        raise ErroCLIImportacao("campos do manifesto incompletos ou desconhecidos")
    csv_path = _arquivo_seguro(m.parent, doc["arquivo_csv"], existente=True)
    if csv_path.stat().st_size > 1_000_000:
        raise ErroCLIImportacao("CSV excede limite")
    pacote = normalizar_arquivo_cotacoes(
        bruto=csv_path.read_bytes(), fonte_id=doc["fonte_id"],
        fonte_url=doc["fonte_url"], edicao_id=doc["edicao_id"],
        coletado_em=doc["coletado_em"], publicado_em=doc["publicado_em"],
        disponivel_em=doc["disponivel_em"])
    saida = {k: pacote[k] for k in ("fonte_id","dataset_id","edicao_id",
                                   "sha256","linhas","estado")}
    saida.update({"modo": "VALIDACAO_OFFLINE", "publicavel": False})
    if persistir:
        caminho = _arquivo_seguro(m.parent, banco, existente=False)
        store = ArmazemVintages(caminho)
        try:
            resumo = persistir_quarentena(store, pacote, operador_autorizou_importacao=True)
        finally:
            store.fechar()
        saida.update({"modo": "QUARENTENA_SQLITE", "novas": resumo["novas"],
                      "duplicadas": resumo["duplicadas"]})
    return saida

def main(argv=None) -> int:
    cli = argparse.ArgumentParser(description="NIVON: CSV CEPEA/IMEA OFFLINE em quarentena")
    cli.add_argument("--manifesto", required=True, type=Path)
    cli.add_argument("--persistir-quarentena", action="store_true")
    cli.add_argument("--banco", help="nome simples do arquivo SQLite no diretorio do manifesto")
    args = cli.parse_args(argv)
    try:
        resultado = executar_importacao(manifesto=args.manifesto,
              persistir=args.persistir_quarentena, banco=args.banco)
    except (OSError, ValueError, PermissionError) as exc:
        print(json.dumps({"status":"BLOQUEADO",
                          "classe_erro": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
