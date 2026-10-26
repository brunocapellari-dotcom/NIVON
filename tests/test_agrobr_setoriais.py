"""Testes offline de agrobr_setoriais e catalogo_github.

Fornecedor agrobr fictício; números sintéticos, não são dados IBGE/ANP reais.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.agrobr_setoriais import (
    CONTRATOS, ErroFontesSetoriais, _parametros, _referencia, coletar_setorial_agrobr,
)
from nivon.catalogo_github import ErroCatalogo, consultar_catalogo

AGORA = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)


class Quadro:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return [dict(r) for r in self.rows]


class Meta:
    def __init__(self, **over):
        self.d = {"agrobr_version": "2.0.0", "validation_passed": True,
                  "selected_source": "ibge_pam", "license": "livre",
                  "contract_version": "1"} | over

    def to_dict(self):
        return dict(self.d)


def fornecedor(rows, **meta):
    async def f(dataset, args, params):
        f.chamada = (dataset, args, params)
        return Quadro(rows), Meta(**meta)
    return f


PAM = [{"ano": 2024, "localidade_cod": "51", "produto": "soja",
        "area_plantada": 100.0, "area_colhida": 99.5, "producao": 350.0,
        "unidade_producao": "t", "rendimento": None, "valor_producao": float("nan")}]


class Coleta(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)

    def coletar(self, rows=PAM, dataset="producao_anual", meta=None, **kw):
        kw = {"produto": "soja", "ano": 2024, "uf": "MT"} | kw
        f = fornecedor(rows, **(meta or {}))
        out = coletar_setorial_agrobr(
            dataset=dataset, banco=self.root / "db.sqlite", raw_dir=self.root / "raw",
            executar=True, fornecedor=f, instante=AGORA, **kw)
        return out, f

    def test_exige_execucao_explicita(self):
        with self.assertRaises(PermissionError):
            coletar_setorial_agrobr(dataset="producao_anual", banco="x", raw_dir="y")

    def test_pam_normaliza_medidas_e_ignora_ausentes(self):
        out, f = self.coletar()
        self.assertEqual(f.chamada, ("producao_anual", ("soja",),
                                     {"ano": 2024, "nivel": "uf", "uf": "MT"}))
        self.assertEqual(out["observacoes_normalizadas"], 3)  # rendimento None e NaN fora
        self.assertFalse(out["snapshot_eh_raw_primario"])
        with sqlite3.connect(self.root / "db.sqlite") as db:
            linhas = db.execute("SELECT identidade, referencia, unidade, valor, natureza "
                                "FROM observacoes ORDER BY identidade").fetchall()
        unidades = {i.rsplit("|", 1)[1]: (u, v) for i, _, u, v, _ in linhas}
        self.assertEqual(unidades["area_plantada"], ("ha", "100.0"))
        self.assertEqual(unidades["producao"], ("t", "350.0"))
        self.assertTrue(all(r == "2024-12-31" and n == "INFORMADO" for _, r, _, _, n in linhas))

    def test_rejeita_fonte_licenca_versao_ou_validacao(self):
        for meta in ({"selected_source": "conab"}, {"license": "restrita"},
                     {"agrobr_version": "1.9"}, {"validation_passed": False}):
            with self.subTest(meta=meta), self.assertRaises(PermissionError):
                self.coletar(meta=meta)

    def test_chave_repetida_ou_incompleta(self):
        with self.assertRaises(ErroFontesSetoriais):
            self.coletar(rows=PAM + PAM)
        with self.assertRaises(ErroFontesSetoriais):
            self.coletar(rows=[{k: v for k, v in PAM[0].items() if k != "localidade_cod"}])

    def test_unidade_ausente_bloqueia(self):
        sem_unidade = [{k: v for k, v in PAM[0].items() if k != "unidade_producao"}]
        with self.assertRaises(ErroFontesSetoriais):
            self.coletar(rows=sem_unidade)

    def test_negativo_so_na_margem_do_diesel(self):
        base = {"data": "2026-10-19", "uf": "MT", "municipio": "CUIABA", "produto": "DIESEL S10",
                "nivel": "uf", "agregacao": "semanal", "preco_venda": 6.1, "margem": -0.05}
        kw = dict(dataset="precos_diesel", meta={"selected_source": "anp_diesel"},
                  produto="DIESEL S10", ano=None, uf="MT", inicio="2026-10-01", fim="2026-10-20")
        out, _ = self.coletar(rows=[base], **kw)
        self.assertEqual(out["observacoes_normalizadas"], 2)
        with self.assertRaises(ErroFontesSetoriais):
            self.coletar(rows=[base | {"preco_venda": -1}], **kw)


class Parametros(unittest.TestCase):
    def test_contratos(self):
        self.assertEqual(_parametros("leite_industrial", trimestre="202602"),
                         ((), {"trimestre": "202602", "uf": None}))
        invalidos = [
            dict(dataset="producao_anual", produto="cafe", ano=2024),
            dict(dataset="leite_industrial", produto="leite", trimestre="202602"),
            dict(dataset="producao_anual", produto="soja", ano=2024, uf="mt"),
            dict(dataset="abate_trimestral", produto="bovino", trimestre="2026Q1"),
            dict(dataset="pib_agro", produto="agropecuaria", trimestre="202602", uf="MT"),
            dict(dataset="precos_diesel", produto="DIESEL", uf="MT",
                 inicio="2026-01-01", fim="2026-10-20"),
            dict(dataset="inexistente"),
        ]
        for kw in invalidos:
            with self.subTest(kw=kw), self.assertRaises(ErroFontesSetoriais):
                _parametros(**kw)

    def test_referencias_temporais(self):
        self.assertEqual(_referencia({"trimestre": "202602"}),
                         ("2026-06-30", "FIM_TRIMESTRE_CONVENCIONAL"))
        self.assertEqual(_referencia({"ano": 2024}), ("2024-12-31", "FIM_ANO_CONVENCIONAL"))
        self.assertEqual(_referencia({"data": "2026-10-19T00:00:00"}), ("2026-10-19", "DATA"))
        for linha in ({}, {"trimestre": "202605"}, {"ano": 1980}):
            with self.subTest(linha=linha), self.assertRaises(ErroFontesSetoriais):
                _referencia(linha)

    def test_datasets_tem_fontes_e_chaves(self):
        for nome, regra in CONTRATOS.items():
            self.assertTrue(regra["fontes"] and regra["chave"] and regra["medidas"], nome)


class Catalogo(unittest.TestCase):
    def test_catalogo_versionado_valido(self):
        r = consultar_catalogo()
        self.assertGreater(len(r["repositorios"]), 0)
        self.assertGreater(len(r["datasets_agrobr_2_0"]), 0)
        self.assertIn("não equivale", r["nota"])

    def test_filtros(self):
        r = consultar_catalogo(secao="repositorios", status="INTEGRADO")
        self.assertEqual(set(r), {"repositorios", "referencia", "situacao", "nota"})
        self.assertTrue(all(x["decisao"] == "INTEGRADO" for x in r["repositorios"]))
        with self.assertRaises(ErroCatalogo):
            consultar_catalogo(secao="outra")

    def test_rejeita_schema_duplicados_e_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            base = {"schema": "nivon.integracoes.github.v1", "referencia": "x",
                    "repositorios": [{"id": "a"}, {"id": "a"}], "datasets_agrobr_2_0": []}
            p.write_text(json.dumps(base))
            with self.assertRaises(ErroCatalogo):
                consultar_catalogo(arquivo=p)
            p.write_text(json.dumps(base | {"schema": "v0"}))
            with self.assertRaises(ErroCatalogo):
                consultar_catalogo(arquivo=p)
            link = Path(tmp) / "l.json"
            link.symlink_to(p)
            with self.assertRaises(ErroCatalogo):
                consultar_catalogo(arquivo=link)


if __name__ == "__main__":
    unittest.main()
