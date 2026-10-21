"""Testes de integridade de dois artefatos OFFLINE; dados sintéticos."""
from hashlib import sha256
import json
import unittest

from nivon.evidencia_bruta_mercados import (
    ErroEvidenciaMercado, preparar_precos_com_artefatos,
)


def row(preco="1000", **alt):
    dado = {
        "mercado": "CME", "produto": "SOJA", "contrato": "2026-11",
        "tipo": "AJUSTE", "unidade": "USC/BU", "instrumento_id": "ZS",
        "data_referencia": "2026-10-13", "competencia": "2026-10",
        "referencia_em": "2026-10-13T16:00:00-04:00",
        "publicacao_em": "2026-10-13T16:30:00-04:00",
        "coleta_em": "2026-10-13T17:00:00-04:00",
        "fonte_id": "FONTE-TESTE", "fonte_url": "https://example.org/test",
        "edicao_sha256": "a" * 64, "preco": preco,
    }
    dado.update(alt)
    return dado


RAW = b"conteudo cru ficticio do provedor (sem parser real)\n"


def lote(rows=None, arquivo_original=RAW):
    linhas = rows if rows is not None else [row()]
    snap = b"".join(
        (json.dumps(r, sort_keys=True, ensure_ascii=True,
                    separators=(",", ":")) + "\n").encode()
        for r in linhas
    )
    manifest = {
        "schema": "NIVON_MARKET_RAW_NORM_V1",
        "fonte_id": "FONTE-TESTE",
        "fonte_url": "https://example.org/test",
        "raw_sha256": sha256(arquivo_original).hexdigest(),
        "normalizado_sha256": sha256(snap).hexdigest(),
        "capturado_em": "2026-10-14T10:00:00Z",
        "parser_id": "PARSER-TESTE", "parser_versao": "0.0-test",
        "direitos_status": "NAO_HOMOLOGADO",
    }
    return arquivo_original, snap, manifest


def executar(raw=None, snap=None, manifest=None):
    a, b, m = lote()
    return preparar_precos_com_artefatos(
        raw if raw is not None else a,
        snap if snap is not None else b,
        manifesto=manifest if manifest is not None else m,
        as_of="2026-10-20T12:00:00Z",
    )


class TestEvidenciaBrutaMercado(unittest.TestCase):
    def test_integridade_bytes_e_limites_do_que_foi_provado(self):
        res = executar()
        ev = res["evidencia_arquivos"]
        self.assertTrue(ev["bytes_original_conferidos"])
        self.assertTrue(ev["bytes_normalizados_conferidos"])
        self.assertFalse(ev["fidelidade_parser_independente_verificada"])
        self.assertFalse(ev["origem_remota_autenticada"])
        self.assertFalse(ev["direitos_publicacao_verificados"])
        self.assertFalse(res["publicavel"])
        self.assertEqual(res["serie"][0]["valor_decimal"], "1000")

    def test_raw_adulterado_bloqueia(self):
        with self.assertRaisesRegex(ErroEvidenciaMercado, "original diverge"):
            executar(raw=RAW+b"adulteracao")

    def test_jsonl_adulterado_bloqueia(self):
        _, snap, _ = lote()
        with self.assertRaisesRegex(ErroEvidenciaMercado, "normalizado diverge"):
            executar(snap=snap.replace(b"1000", b"5000"))

    def test_parser_pode_mentir_mesmo_com_hashs_validos(self):
        raw, snap, manifest = lote([row(preco="5000")])
        result = preparar_precos_com_artefatos(
            raw, snap, manifesto=manifest, as_of="2026-10-20T12:00:00Z")
        self.assertEqual(result["serie"][0]["valor_decimal"], "5000")
        # O contrato não permite declarar correção da extração com este par.
        self.assertFalse(result["evidencia_arquivos"]["fidelidade_parser_independente_verificada"])

    def test_manifesto_de_outro_provedor_bloqueia(self):
        a, b, m = lote()
        m["fonte_id"] = "FONTE-OUTRA"
        with self.assertRaisesRegex(ErroEvidenciaMercado, "diverge do manifesto"):
            executar(raw=a, snap=b, manifest=m)

    def test_injecao_chave_duplicada_nao_entra_em_preco(self):
        duplicate = (b'{"mercado":"CME","mercado":"ICE"}\n')
        raw, _, m = lote()
        m["normalizado_sha256"] = sha256(duplicate).hexdigest()
        with self.assertRaises(ErroEvidenciaMercado):
            executar(raw=raw, snap=duplicate, manifest=m)

    def test_nan_jsonl_rejeitado(self):
        payload = b'{"valor":NaN}\n'
        raw, _, m = lote()
        m["normalizado_sha256"] = sha256(payload).hexdigest()
        with self.assertRaises(ErroEvidenciaMercado):
            executar(raw=raw, snap=payload, manifest=m)

    def test_manifesto_coletado_depois_asof(self):
        a, b, m = lote()
        m["capturado_em"] = "2026-10-21T10:00:00Z"
        with self.assertRaisesRegex(ErroEvidenciaMercado, "após as_of"):
            executar(raw=a, snap=b, manifest=m)

    def test_registro_coletado_depois_snapshot(self):
        a, b, m = lote([
            row(coleta_em="2026-10-14T15:00:00Z")
        ])
        with self.assertRaisesRegex(ErroEvidenciaMercado, "depois da captura"):
            executar(raw=a, snap=b, manifest=m)

    def test_preco_float_normalizado_recusado(self):
        a, b, m = lote([row(preco=1000.25)])
        from nivon.qualidade_mercados import ErroQualidadeMercado
        with self.assertRaisesRegex(ErroQualidadeMercado, "float"):
            executar(raw=a, snap=b, manifest=m)

    def test_nao_homologa_licenca_pelo_manifesto(self):
        a, b, m = lote()
        m["direitos_status"] = "HOMOLOGADO"
        with self.assertRaisesRegex(ErroEvidenciaMercado, "direitos"):
            executar(raw=a, snap=b, manifest=m)

    def test_lote_multiobservacao(self):
        r1 = row()
        r2 = row(preco="1005", data_referencia="2026-10-14",
                 referencia_em="2026-10-14T08:00:00-04:00",
                 publicacao_em="2026-10-14T08:10:00-04:00",
                 coleta_em="2026-10-14T08:20:00-04:00")
        a, b, m = lote([r1, r2])
        r = executar(raw=a, snap=b, manifest=m)
        self.assertEqual(r["periodos"], 2)
        self.assertEqual(r["evidencia_arquivos"]["registros_jsonl"], 2)


if __name__ == "__main__":
    unittest.main()
