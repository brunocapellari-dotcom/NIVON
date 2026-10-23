"""CLI local do lote de abate SIDRA (sem rede; dry-run por padrao).

Exemplo:
 PYTHONPATH=src python -m nivon.pecuaria_sidra_operacao \
   --manifest /dados/manifests/lote.json --base-dir /dados/capturas \
   --corte 2026-10-23T00:00:00-04:00 --confirmar-direitos

Somente com --gravar --banco <sqlite> grava em transacao atomica.
Nao embute senha, URL dinamica, crawler, agendamento ou rede.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .motores import DadoInvalido
from .pecuaria_sidra_lote import executar_lote_sidra_offline, resumir_lote_sidra

_KEYS = {"especie", "tabela_sidra", "url_valores", "url_metadados",
         "arquivo_valores", "arquivo_metadados", "publicacao_declarada",
         "coleta_declarada", "dimensoes", "totais", "variaveis"}


def _arquivo_seguro(base, relativo, tamanho_maximo):
    if (not isinstance(relativo, str) or not relativo or len(relativo) > 240
        or "\x00" in relativo):
        raise DadoInvalido("nome de arquivo invalido")
    rp = Path(relativo)
    if rp.is_absolute() or any(part in ("..", ".") for part in rp.parts) or rp.suffix != ".json":
        raise DadoInvalido("arquivo deve ser JSON relativo sem path traversal")
    arquivo = base / rp
    if arquivo.is_symlink() or any(p.is_symlink()
        for p in [arquivo, *arquivo.parents] if p != base and base in p.parents):
        raise DadoInvalido("symlink nao permitido nos arquivos de entrada")
    try:
        resolvido = arquivo.resolve(strict=True)
        resolvido.relative_to(base)
    except (OSError, ValueError) as exc:
        raise DadoInvalido("arquivo fora da base ou inexistente") from exc
    if not arquivo.is_file() or arquivo.stat().st_size > tamanho_maximo:
        raise DadoInvalido("arquivo invalido ou excessivo")
    with arquivo.open("rb") as f:
        raw = f.read(tamanho_maximo + 1)
    if not raw or len(raw) > tamanho_maximo:
        raise DadoInvalido("arquivo vazio ou acima do limite")
    return raw


def carregar_manifesto_sidra(*, manifest, base_dir):
    """Carregar um lote de arquivos locais, sem escrever nem acessar rede."""
    base = Path(base_dir)
    if base.is_symlink() or not base.is_dir():
        raise DadoInvalido("base-dir deve ser diretorio local nao symlink")
    base = base.resolve(strict=True)
    mp = Path(manifest)
    if mp.is_symlink() or not mp.is_file() or mp.stat().st_size > 200_000:
        raise DadoInvalido("manifesto inexistente/inseguro/excessivo")
    with mp.open("rb") as f:
        bruto = f.read(200_001)
    if len(bruto) > 200_000:
        raise DadoInvalido("manifesto excessivo")
    try:
        doc = json.loads(bruto.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise DadoInvalido("manifesto JSON invalido") from exc
    if (not isinstance(doc, dict) or set(doc) != {"schema_version", "capturas"}
        or doc["schema_version"] != "1.0"
        or not isinstance(doc["capturas"], list)
        or not 1 <= len(doc["capturas"]) <= 24):
        raise DadoInvalido("manifesto fora do schema 1.0")
    capturas = []
    for entry in doc["capturas"]:
        if not isinstance(entry, dict) or set(entry) != _KEYS:
            raise DadoInvalido("entrada de manifesto com campos incompletos/extras")
        cap = {k: v for k, v in entry.items()
               if k not in {"arquivo_valores", "arquivo_metadados"}}
        cap["bruto_valores"] = _arquivo_seguro(base, entry["arquivo_valores"], 4_000_000)
        cap["bruto_metadados"] = _arquivo_seguro(base, entry["arquivo_metadados"], 1_000_000)
        capturas.append(cap)
    return capturas


def main(argv=None):
    parser = argparse.ArgumentParser(description="NIVON SIDRA: lote offline auditavel")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--corte", required=True, help="timestamp com fuso")
    parser.add_argument("--confirmar-direitos", action="store_true",
                        help="afirma autorizacao de leitura e armazenamento; nao constitui licenca")
    parser.add_argument("--gravar", action="store_true",
                        help="salva capturas em SQLite local; sem deploy nem agenda")
    parser.add_argument("--banco", help="caminho SQLite local exigido em --gravar")
    args = parser.parse_args(argv)
    try:
        if not args.confirmar_direitos:
            raise PermissionError("confirmacao de direitos necessaria")
        if args.gravar and not args.banco:
            raise DadoInvalido("--gravar exige --banco")
        if args.banco and not args.gravar:
            raise DadoInvalido("--banco sem --gravar nao altera arquivos")
        capturas = carregar_manifesto_sidra(
            manifest=args.manifest, base_dir=args.base_dir)
        resultado = executar_lote_sidra_offline(
            capturas=capturas, corte_asof=args.corte,
            status_fonte="APROVADA",
            operacoes_autorizadas={"LEITURA", "ARMAZENAMENTO"},
            banco=args.banco, persistir=args.gravar)
        print(json.dumps(resumir_lote_sidra(resultado),
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DadoInvalido, PermissionError, ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOQUEADO_SEM_PROMOCAO",
                          "motivo": type(exc).__name__,
                          "detalhe": str(exc)[:240]}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
