"""Pacote portavel de quarentena SIDRA para staging posterior (inclusive GCS).

Nao faz upload, publica series, ativa Cloud ou modifica SQLite. Uma
exportacao requer declaracao expressa de direito de retencao/transferencia.
Mantem todas as versoes conhecidas no corte, em vez de apenas o ultimo valor.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile

from .cadeias_adicionais import TABELAS_SIDRA, _instante
from .motores import DadoInvalido
from .pecuaria_sidra_quarentena import _conectar, recuperar_values_quarentena
from .pecuaria_sidra_backfill import _validar_periodos


def exportar_quarentena_sidra(*, banco, destino, periodos, corte_asof,
                              direitos_confirmados=False):
    """Exporta bytes existentes e manifesto com hashes em diretorio NOVO.

    Preflight em SQLite RO + corte + hashes ANTES de criar diretorio.
    Escrita num diretorio temporario e rename atomicamente no mesmo volume.
    O retorno de sucesso nao certifica proveniencia HTTP ou licença.
    """
    if type(direitos_confirmados) is not bool or not direitos_confirmados:
        raise PermissionError("exportacao requer direito explicito de transferencia")
    periodos = _validar_periodos(periodos)
    corte = _instante(corte_asof, "corte_asof")
    if not isinstance(destino, (str, Path)):
        raise DadoInvalido("destino de exportacao invalido")
    pasta = Path(destino).expanduser()
    if any(x.is_symlink() for x in (pasta, *pasta.parents)):
        raise DadoInvalido("exportacao recusa symlinks")
    if pasta.exists() or not pasta.parent.is_dir():
        raise DadoInvalido("destino deve ser NOVO e ter diretorio pai existente")
    with closing(_conectar(banco, criar=False)) as cx:
        placeholders = ",".join("?" for _ in periodos)
        rows = cx.execute(
            """SELECT id FROM valores_pecuaria_quarentena
               WHERE periodo IN (""" + placeholders + """)
               ORDER BY id ASC LIMIT 301""", tuple(periodos)).fetchall()
    if len(rows) > 300:
        raise DadoInvalido("exportacao acima de 300 capturas: paginacao obrigatoria")
    arquivos = []
    for (id_captura,) in rows:
        pacote = recuperar_values_quarentena(banco=banco, id_captura=id_captura)
        primeiro = _instante(pacote["primeira_coleta_em"], "primeira_coleta_em")
        if primeiro > corte:
            continue
        especie, tabela = pacote["especie"], pacote["tabela_sidra"]
        if TABELAS_SIDRA.get(especie) != tabela:
            raise DadoInvalido("especie/tabela fora do registro canonico")
        raw = pacote["bruto"]
        hash_ = sha256(raw).hexdigest()
        if pacote["sha256_bruto"] != hash_:
            raise DadoInvalido("hash divergente na exportacao")
        nome = f"{id_captura:07d}-{tabela}-{pacote['periodo']}-{pacote['territorio']}-{hash_[:12]}.json"
        arquivos.append((
            nome, raw, {
                "id_captura_local": id_captura,
                "arquivo": nome,
                "especie": especie, "tabela_sidra": tabela,
                "periodo": pacote["periodo"], "territorio": pacote["territorio"],
                "url_declarada": pacote["url_declarada"],
                "primeira_coleta_em": pacote["primeira_coleta_em"],
                "sha256_bruto": hash_, "tamanho_bytes": len(raw),
                "status": "QUARENTENA_VALUES_SEM_METADATA_V3",
                "metadados_v3_verificados": False,
                "publicacao_historica_ibge_confirmada": False,
            }
        ))
    if not arquivos:
        raise DadoInvalido("nenhuma captura estava disponivel ate o corte")
    manifesto = {
        "formato": "NIVON_SIDRA_QUARENTENA_EXPORT_V1",
        "criado_em": datetime.now(timezone.utc).isoformat(),
        "corte_asof": corte.isoformat(),
        "periodos": periodos,
        "n_capturas": len(arquivos),
        "capturas": [item[2] for item in arquivos],
        "origem_externa_autenticada": False,
        "direitos_licenca_auditados": False,
        "metadados_v3_verificados": False,
        "dados_homologados": False,
        "publicacao_permitida": False,
        "instrucao": "Carga futura apenas em staging/quarentena apos auditoria",
    }
    raw_manifesto = (json.dumps(manifesto, ensure_ascii=False,
                                sort_keys=True, indent=2) + "\n").encode("utf-8")
    tmp = Path(tempfile.mkdtemp(prefix=".nivon-sidra-export-", dir=pasta.parent))
    try:
        for nome, raw, _ in arquivos:
            (tmp / nome).write_bytes(raw)
        (tmp / "manifesto.json").write_bytes(raw_manifesto)
        if pasta.exists():
            raise DadoInvalido("destino criado por outro processo; nao sobrescrever")
        os.rename(tmp, pasta)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {
        "status": "EXPORTACAO_LOCAL_DE_QUARENTENA_NAO_HOMOLOGADA",
        "destino": str(pasta),
        "n_capturas": len(arquivos),
        "sha256_manifesto": sha256(raw_manifesto).hexdigest(),
        "arquivos_verificados": len(arquivos),
        "transferencia_cloud_executada": False,
        "publicacao_permitida": False,
    }
