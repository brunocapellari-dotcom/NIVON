"""Importador LOCAL de arquivos PAM previamente recebidos: sem rede e sem promoção.

O usuário fornece apenas os arquivos para QUARENTENA e os SHA esperados.
Não existe concessão de licença neste módulo. Não insere no ledger nem
trata uma declaração de direitos como autorização oficial comprovada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from .ivo_pam_operacao_lote import (
    ErroLotePAM, PedidoPAM, _validar_pedidos, executar_lote_pam_offline,
)
from .ivo_pam_gate_promocao import preparar_fila_revisao_pam

_HASH = re.compile(r"[a-f0-9]{64}\Z")


class ErroImportacaoLocalPAM(ValueError):
    pass


def _ler_arquivo(base: Path, nome: str, digest: str, max_bytes: int) -> bytes:
    if (type(nome) is not str or not nome or len(nome) > 300
            or "\\" in nome or "\x00" in nome):
        raise ErroImportacaoLocalPAM("caminho de arquivo invalido")
    rel = PurePosixPath(nome)
    if rel.is_absolute() or not rel.parts or any(p in (".", "..") for p in rel.parts):
        raise ErroImportacaoLocalPAM("somente caminhos relativos sob o diretorio base")
    if type(digest) is not str or _HASH.fullmatch(digest) is None:
        raise ErroImportacaoLocalPAM("SHA-256 explicito obrigatorio")
    target = base
    for parte in rel.parts:
        target = target / parte
        if target.is_symlink():
            raise ErroImportacaoLocalPAM("links simbolicos proibidos em caminhos de origem")
    if not target.is_file() or target.stat().st_size > max_bytes:
        raise ErroImportacaoLocalPAM("arquivo ausente ou excede quota por arquivo")
    raw = target.read_bytes()
    if not raw or len(raw) > max_bytes or hashlib.sha256(raw).hexdigest() != digest:
        raise ErroImportacaoLocalPAM("bytes nao correspondem ao SHA fornecido")
    return raw


def _escrever_uma_vez(path: Path, raw: bytes) -> None:
    if path.is_symlink():
        raise ErroImportacaoLocalPAM("destino e symlink")
    try:
        fd = os.open(path, os.O_EXCL | os.O_CREAT | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if not path.is_file() or path.is_symlink() or path.read_bytes() != raw:
            raise ErroImportacaoLocalPAM("arquivo existente foi modificado ou colidiu")
        return
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def executar_importacao_local_pam(*, config: dict, origem: str | Path,
                                 destino: str | Path) -> dict:
    """Recebe arquivos locais, escreve só quarentena e relatórios bloqueados.

    TODOS os caminhos, hashes, datas e recortes são validados antes da
    primeira criação de diretório no destino.
    """
    if not isinstance(config, dict) or config.get("schema") != "nivon_ivo_pam_importacao_local_v1":
        raise ErroImportacaoLocalPAM("schema de manifestacao local invalido")
    if (config.get("somente_quarentena") is not True
            or config.get("publicacao_proibida") is not True):
        raise ErroImportacaoLocalPAM("operacoes precisam estar explicitamente bloqueadas")
    ref = config.get("referencia_direitos_declarada")
    if (type(ref) is not str or not re.fullmatch(r"[A-Za-z0-9._:/-]{6,160}", ref)):
        raise ErroImportacaoLocalPAM("referencia de direitos invalida")
    timestamp = config.get("capturado_em_declarado")
    try:
        momento = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ErroImportacaoLocalPAM("captura declarada invalida") from exc
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ErroImportacaoLocalPAM("timestamp com timezone obrigatorio")
    entradas = config.get("itens")
    if not isinstance(entradas, list) or not 1 <= len(entradas) <= 25:
        raise ErroImportacaoLocalPAM("lote local deve ter 1-25 itens")
    origin = Path(origem).expanduser()
    output = Path(destino).expanduser()
    if not origin.is_dir() or origin.is_symlink() or output.is_symlink():
        raise ErroImportacaoLocalPAM("diretorio base ausente ou simbolico")
    if output.exists() and not output.is_dir():
        raise ErroImportacaoLocalPAM("destino nao e diretorio")
    pedidos = []
    arquivos: dict[str, tuple[bytes, str]] = {}
    for x in entradas:
        if not isinstance(x, dict):
            raise ErroImportacaoLocalPAM("item do manifesto nao e objeto")
        if set(x) - {
            "municipio_ibge", "ano", "categoria_c81", "variavel",
            "arquivo", "arquivo_sha256", "pdf_arquivo", "pdf_sha256", "pdf_url",
            "publicacao_declarada", "versao_anterior_sha256",
        }:
            raise ErroImportacaoLocalPAM("campo nao suportado no manifesto")
        req = PedidoPAM(
            municipio_ibge=x.get("municipio_ibge"), ano=x.get("ano"),
            categoria_c81=x.get("categoria_c81"), variavel=x.get("variavel"),
            pdf_url=x.get("pdf_url"),
            publicacao_declarada=x.get("publicacao_declarada"),
            versao_anterior_sha256=x.get("versao_anterior_sha256"),
        )
        pedidos.append(req)
    try:
        plans = _validar_pedidos(pedidos)
    except (ErroLotePAM, ValueError) as exc:
        raise ErroImportacaoLocalPAM("lote invalido na validacao preflight") from exc
    for entry, (req, plan) in zip(entradas, plans):
        raw = _ler_arquivo(origin, entry.get("arquivo"), entry.get("arquivo_sha256"),
                           2_000_000)
        if plan["url"] in arquivos:
            raise ErroImportacaoLocalPAM("URL repetida no lote")
        arquivos[plan["url"]] = (raw, "application/json")
        if req.pdf_url is not None:
            pdf = _ler_arquivo(origin, entry.get("pdf_arquivo"), entry.get("pdf_sha256"),
                               8_000_000)
            if req.pdf_url in arquivos:
                raise ErroImportacaoLocalPAM("documento PDF reutilizado como outra consulta")
            arquivos[req.pdf_url] = (pdf, "application/pdf")
        elif any(k in entry for k in ("pdf_arquivo", "pdf_sha256")):
            raise ErroImportacaoLocalPAM("PDF sem URL declarada")
    def arquivo_local(url: str, _limit: int, _timeout: int) -> tuple[bytes, str]:
        return arquivos[url]
    # O catalogo aqui tem escopo somente LOCAL e é passado ao contrato
    # legado de coleta. Nao altera o catalogo real do NIVON.
    temporario = {"datasets": [{"id": "IBGE_PAM", "source_id": "IBGE",
                 "enabled": True, "collection_authorized": True,
                 "training_authorized": False}]}
    direitos = {"operacoes": frozenset({"COLETA", "ARMAZENAMENTO"}),
                "evidencia_ref": ref}
    manifest = executar_lote_pam_offline(
        pedidos=pedidos, catalogo=temporario, direitos=direitos,
        raiz=output / "quarentena", coletado_em=momento, transporte=arquivo_local,
        continuar_apos_falha=False,
    )
    fila = preparar_fila_revisao_pam(manifest)
    # Os arquivos de saida sao somente metadados e SHA, nunca raw SIDRA.
    # Nomes content-addressed garantem repeticao sem sobrescrever provas.
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.is_symlink():
        raise ErroImportacaoLocalPAM("diretorio destino substituido por link")
    dados = [
        ("manifesto_" + manifest["manifesto_sha256"] + ".json", manifest),
        ("fila_" + fila["fila_sha256"] + ".json", fila),
    ]
    for nome, val in dados:
        content = (json.dumps(val, sort_keys=True, ensure_ascii=False,
                              allow_nan=False, indent=2) + "\n").encode("utf-8")
        _escrever_uma_vez(output / nome, content)
    return {
        "estado": ("QUARENTENA_LOCAL_COM_FALHAS" if manifest["falhas"]\n                   else "QUARENTENA_LOCAL_AUDITADA_SEM_HOMOLOGACAO"),
        "lote_sha256": manifest["manifesto_sha256"],
        "fila_sha256": fila["fila_sha256"],
        "recebidos": manifest["solicitados"], "auditados": manifest["auditorias"],
        "falhas": manifest["falhas"], "promocoes": 0,
        "resultado_gravado": True, "dados_reais_homologados": False,
        "direitos_declarados_nao_comprovados": True,
        "rede_executada": False, "publicado": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arquivar PAM local com SHA e revisao pendente; sem rede"
    )
    parser.add_argument("--manifesto", required=True, type=Path)
    parser.add_argument("--destino", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.manifesto.is_symlink() or args.manifesto.stat().st_size > 100_000:
        raise ErroImportacaoLocalPAM("manifesto invalido ou excessivo")
    config = json.loads(args.manifesto.read_text(encoding="utf-8"))
    result = executar_importacao_local_pam(
        config=config, origem=args.manifesto.parent, destino=args.destino,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
