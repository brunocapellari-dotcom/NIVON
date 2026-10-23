#!/usr/bin/env python3
"""Smoke E2E: executor PAM -> quarentena local -> auditoria -> revisao.

100% offline, valores inventados, sem credenciais, rede, servicos pagos,
modelo preditivo, banco canonico ou dados oficiais.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from nivon.ivo_pam_operacao_lote import PedidoPAM, executar_lote_pam_offline
from nivon.ivo_pam_gate_promocao import preparar_fila_revisao_pam
from nivon.ivo_pam_cli_local import executar_importacao_local_pam
from nivon.sidra_pam import planejar_pam_1612


def main():
    pedidos = [
        PedidoPAM("5107958", 2021, "2713", "214"),
        PedidoPAM("3503109", 2020, "2714", "214"),
    ]
    responses = {}
    for i, p in enumerate(pedidos, 1):
        url = planejar_pam_1612(
            municipio_ibge=p.municipio_ibge, ano=p.ano,
            codigo_produto_c81=p.categoria_c81, codigo_variavel=p.variavel,
        )["url"]
        raw = json.dumps([
            {"D1C": "Município (Código)", "D2C": "Variável (Código)",
             "D3C": "Ano (Código)",
             "D4C": "Produto das lavouras temporárias (Código)",
             "V": "Valor", "MN": "Unidade de Medida"},
            {"D1C": p.municipio_ibge, "D2C": p.variavel,
             "D3C": str(p.ano), "D4C": p.categoria_c81,
             "V": str(i * 111), "MN": "Toneladas"},
        ], ensure_ascii=False).encode("utf-8")
        responses[url] = (raw, "application/json")
    called = []
    def fake_transport(url, limit, timeout):
        called.append(url)
        return responses[url]

    with tempfile.TemporaryDirectory() as root:
        opts = {
            "pedidos": pedidos,
            "catalogo": {"datasets": [{"id": "IBGE_PAM", "source_id": "IBGE",
                          "enabled": True, "collection_authorized": True,
                          "training_authorized": False}]},
            "direitos": {"operacoes": frozenset({"COLETA", "ARMAZENAMENTO"}),
                         "evidencia_ref": "LICENCA_FICTICIA_APENAS_CI"},
            "raiz": Path(root) / "quarentena",
            "coletado_em": datetime(2026, 10, 21, 15, tzinfo=timezone.utc),
            "transporte": fake_transport,
        }
        primeira = executar_lote_pam_offline(**opts)
        segunda = executar_lote_pam_offline(**opts)
        fila = preparar_fila_revisao_pam(primeira)
        assert primeira == segunda, "replay offline nao idempotente"
        assert primeira["auditorias"] == len(pedidos) == fila["quantidade_pendente"]
        assert primeira["falhas"] == 0 and len(called) == len(pedidos) * 2
        assert len(list((Path(root) / "quarentena" / "recibos").iterdir())) == 2
        assert primeira["promocoes_realizadas"] == 0
        assert not fila["registro_canonico_autorizado"]
        assert not fila["provas_externas_verificadas"]
        assert all(x["estado"] == "REVISAO_INDEPENDENTE_NAO_EXECUTADA"
                   for x in fila["itens_pendentes"])
        # Exercitar tambem a entrada a partir de arquivos locais com SHA
        # fornecido. Nunca presume origem/licenca real desses bytes.
        entrada = Path(root) / "arquivos_entrada"
        entrada.mkdir()
        itens = []
        for p in pedidos:
            uri = planejar_pam_1612(
                municipio_ibge=p.municipio_ibge, ano=p.ano,
                codigo_produto_c81=p.categoria_c81, codigo_variavel=p.variavel,
            )["url"]
            raw, _mime = responses[uri]
            nome = "arquivo_" + p.municipio_ibge + "_" + str(p.ano) + ".json"
            (entrada / nome).write_bytes(raw)
            itens.append({
                "municipio_ibge": p.municipio_ibge, "ano": p.ano,
                "categoria_c81": p.categoria_c81, "variavel": p.variavel,
                "arquivo": nome,
                "arquivo_sha256": hashlib.sha256(raw).hexdigest(),
            })
        manifestacao_local = {
            "schema": "nivon_ivo_pam_importacao_local_v1",
            "somente_quarentena": True, "publicacao_proibida": True,
            "capturado_em_declarado": "2026-10-21T15:00:00+00:00",
            "referencia_direitos_declarada": "DOCUMENTO_FICTICIO_DO_TESTE",
            "itens": itens,
        }
        saida = Path(root) / "saida_local"
        importacao1 = executar_importacao_local_pam(
            config=manifestacao_local, origem=entrada, destino=saida)
        importacao2 = executar_importacao_local_pam(
            config=manifestacao_local, origem=entrada, destino=saida)
        assert importacao1 == importacao2
        assert importacao1["auditados"] == len(pedidos)
        assert importacao1["falhas"] == 0
        assert not importacao1["rede_executada"]
        assert len(list(saida.glob("manifesto_*.json"))) == 1
        assert len(list(saida.glob("fila_*.json"))) == 1
        print(json.dumps({
            "demo": "PAM_OFFLINE_SEM_REDE",
            "status": "E2E_SUCESSO_REVISAO_PENDENTE",
            "registros_simulados": primeira["auditorias"],
            "falhas": primeira["falhas"],
            "idempotencia_verificada": primeira == segunda,
            "recibos": fila["quantidade_pendente"],
            "manifesto_sha256": primeira["manifesto_sha256"],
            "fila_sha256": fila["fila_sha256"],
            "promocoes": primeira["promocoes_realizadas"],
            "importacao_local_auditada": importacao1["auditados"],
            "relatorios_locais": len(list(saida.glob("*.json"))),
            "coleta_real": False,
            "homologado": False,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
