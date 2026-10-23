"""Verificacao integrada de metadados SIDRA, nunca homologacao."""
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_metadados import (
    analisar_contrato_metadados_sidra, confrontar_mapa_variaveis,
)
from nivon.pecuaria_sidra_lote import executar_lote_sidra_offline
from test_pecuaria_sidra_lote_integrado import pacote

MOCK_METADATA = {
    "id": 1092,
    "variaveis": [
        {"id": 9999, "nome": "Animais abatidos", "unidade": "Cabeças"},
        {"id": 8888, "nome": "Peso total das carcaças", "unidade": "Quilogramas"},
        {"id": 1000284, "nome": "Animais abatidos - percentual do total geral",
         "unidade": "%"},
    ],
    "classificacoes": [
        {"id": 120, "nome": "Tipo de inspeção", "categorias": [
            {"id": 0, "nome": "Total"},
            {"id": 1, "nome": "Federal"},
        ]},
        {"id": 121, "nome": "Referência temporal", "categorias": [
            {"id": 0, "nome": "Total"}
        ]},
    ],
}


def inspecionar(metadata=None):
    x = MOCK_METADATA if metadata is None else metadata
    return analisar_contrato_metadados_sidra(
        bruto_metadados=json.dumps(x, ensure_ascii=False).encode(),
        especie="BOVINO", tabela_sidra="1092")


class TestMetadadosSidra(unittest.TestCase):
    def test_duas_variaveis_completas_e_percentual_descartado(self):
        d = inspecionar()
        self.assertEqual(d["variaveis_candidatas"],
                         {"9999": "ABATE_CABECAS",
                          "8888": "PESO_CARCACAS_KG"})
        self.assertTrue(d["variaveis_completas"])
        self.assertFalse(d["metadados_homologados"])
        self.assertFalse(d["publicacao_permitida"])
        self.assertEqual(d["classificacoes_candidatas"]["120"]["total_candidato"], "0")
        self.assertEqual(confrontar_mapa_variaveis(
            diagnostico=d, mapa={"9999": "ABATE_CABECAS",
                                 "8888": "PESO_CARCACAS_KG"}),
            "CONSISTENTE_COM_METADADOS_NAO_HOMOLOGADOS")

    def test_mapa_divergente_falha(self):
        with self.assertRaisesRegex(DadoInvalido, "diferem"):
            confrontar_mapa_variaveis(
                diagnostico=inspecionar(),
                mapa={"284": "ABATE_CABECAS", "285": "PESO_CARCACAS_KG"})

    def test_metadados_parciais_nunca_sao_promovidos(self):
        doc = {"id": 1092, "variaveis": [{"id": 9999}]}
        d = inspecionar(doc)
        self.assertFalse(d["variaveis_completas"])
        self.assertIn("VARIAVEIS_NAO_IDENTIFICADAS_NOS_METADADOS",
                      d["impedimentos"])
        self.assertEqual(confrontar_mapa_variaveis(
            diagnostico=d, mapa={"9999": "ABATE_CABECAS"}),
            "NAO_VERIFICAVEL_SEM_VARIAVEIS_COMPLETAS")

    def test_categoria_total_ambigua_falha(self):
        x = deepcopy(MOCK_METADATA)
        x["classificacoes"][0]["categorias"].append(
            {"id": 99, "nome": "Total geral"})
        with self.assertRaisesRegex(DadoInvalido, "multiplos totais"):
            inspecionar(x)

    def test_mesmo_indicador_duplicado_falha(self):
        x = deepcopy(MOCK_METADATA)
        x["variaveis"].append({"id": 1234, "nome": "Animais abatidos",
                               "unidade": "Cabeças"})
        with self.assertRaisesRegex(DadoInvalido, "mais de uma"):
            inspecionar(x)

    def test_falhas_de_id_unidade_e_nome(self):
        for mutation in (
            {"id": 1093},
            {"id": "1094"},
            {"id": None},
        ):
            x = deepcopy(MOCK_METADATA)
            x.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(DadoInvalido):
                inspecionar(x)
        x = deepcopy(MOCK_METADATA)
        x["variaveis"][0]["unidade"] = "%"
        self.assertFalse(inspecionar(x)["variaveis_completas"])

    def test_integracao_metadados_consistentes_tres_especies(self):
        caps = [pacote(k) for k in ("BOVINO", "SUINO", "FRANGO")]
        for cap in caps:
            meta = deepcopy(MOCK_METADATA)
            meta["id"] = int(cap["tabela_sidra"])
            cap["bruto_metadados"] = json.dumps(meta, ensure_ascii=False).encode()
        out = executar_lote_sidra_offline(
            capturas=caps, corte_asof="2026-10-23T00:00:00-04:00",
            status_fonte="APROVADA",
            operacoes_autorizadas={"LEITURA", "ARMAZENAMENTO"})
        self.assertEqual(out["qualidade"]["n_contratos_variaveis_coerentes"], 3)
        self.assertEqual(out["qualidade"]["n_contratos_variaveis_nao_verificaveis"], 0)
        self.assertFalse(out["publicacao_permitida"])

    def test_divergencia_metadados_antes_da_persistencia(self):
        cap = pacote("BOVINO")
        meta = deepcopy(MOCK_METADATA)
        meta["variaveis"][0]["id"] = 284
        cap["bruto_metadados"] = json.dumps(meta, ensure_ascii=False).encode()
        with TemporaryDirectory() as tmp:
            destino = Path(tmp) / "capturas.sqlite"
            with self.assertRaisesRegex(DadoInvalido, "diferem"):
                executar_lote_sidra_offline(
                    capturas=[cap], corte_asof="2026-10-23T00:00:00-04:00",
                    status_fonte="APROVADA",
                    operacoes_autorizadas={"LEITURA", "ARMAZENAMENTO"},
                    banco=destino, persistir=True)
            self.assertFalse(destino.exists())


if __name__ == "__main__":
    unittest.main()
