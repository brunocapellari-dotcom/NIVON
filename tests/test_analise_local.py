import copy
import json
import tempfile
import unittest
from pathlib import Path

from nivon.analise_local import executar


class TestAnaliseLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pasta = Path(self.tmp.name)
        mapa_path = pasta / "cadastro-sintetico.csv"
        mapa_path.write_text(
            "uf;cidade;situacao;atividade;area;classe\n"
            "GO;Rio Verde;ATIVO;FABRICANTE;ALIMENTACAO ANIMAL;RAÇÃO\n"
            "SC;Chapeco;INATIVO;FABRICANTE;ALIMENTACAO ANIMAL;RAÇÃO\n", encoding="utf-8"
        )
        antt_path = pasta / "fluxos-sinteticos.csv"
        antt_path.write_text(
            "mes;uf_inicio;origem;uf_fim;destino;ncm;toneladas;propria\n"
            "2026-01;MT;Sorriso;GO;Rio Verde;10059010;100,00;S\n"
            "2026-02;MT;Sorriso;GO;Rio Verde;10059010;200,00;N\n"
            "2026-03;MT;Sorriso;GO;Rio Verde;10059010;300,00;N\n"
            "2026-04;MT;Sorriso;GO;Rio Verde;;50,00;S\n", encoding="utf-8"
        )
        self.cfg = {
            "mes_corte": "2026-04",
            "mapa": {
                "caminho": str(mapa_path), "fonte_id": "MAPA_FIXTURE",
                "status": "APROVADA", "operacoes": ["LEITURA_LOCAL"],
                "competencia": "2026", "referencia": "2026-04-01",
                "publicacao": "2026-04-02",
                "colunas": {"uf": "uf", "municipio": "cidade",
                            "situacao": "situacao", "atividade": "atividade", "area": "area", "classificacao": "classe"},
                "dominios": {
                    "situacoes_ativas": ["ATIVO"], "situacoes_inativas": ["INATIVO"],
                    "atividades_fabricante": ["FABRICANTE"], "atividades_nao_fabricante": ["IMPORTADOR"],
                    "areas_alimentacao_animal": ["ALIMENTACAO ANIMAL"],
                    "areas_nao_alimentacao_animal": ["OUTROS"],
                },
            },
            "antt": {
                "caminho": str(antt_path), "fonte_id": "ANTT_FIXTURE",
                "status": "APROVADA", "operacoes": ["LEITURA_LOCAL"],
                "competencia": "2026-04", "referencia": "2026-04-30",
                "publicacao": "2026-05-02",
                "colunas": {"periodo": "mes", "origem_uf": "uf_inicio",
                            "origem_municipio": "origem", "destino_uf": "uf_fim",
                            "destino_municipio": "destino", "ncm": "ncm",
                            "toneladas": "toneladas", "carga_propria": "propria"},
            },
            "terminais": [
                {"uf": "GO", "municipio": "Rio Verde", "tipo": "FERROVIARIO",
                 "produtos": ["MILHO"], "fonte_id": "TERMINAL_FIXTURE"}
            ],
        }

    def test_fluxo_integrado_preserva_ambiguidade_e_ncm_ausente(self):
        r = executar(self.cfg)
        self.assertEqual(r["total_t_identificado"], 600)
        self.assertEqual(r["destinos"][0]["classe"], "AMBIGUO")
        self.assertEqual(r["destinos"][0]["meses_com_fluxo"], 3)
        self.assertTrue(r["destinos"][0]["recorrente"])
        self.assertEqual(r["auditoria_importacao"]["toneladas_sem_ncm"], 50)
        self.assertEqual(r["auditoria_importacao"]["status"], "NAO_HOMOLOGADO_COM_DADOS_REAIS")

    def test_fonte_pendente_bloqueia_antes_de_abrir(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["antt"]["status"] = "PENDENTE"
        with self.assertRaises(PermissionError):
            executar(cfg)

    def test_mapeamento_incorreto_nao_inventa_coluna(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["antt"]["colunas"]["toneladas"] = "SEM_ESSA_COLUNA"
        with self.assertRaises(ValueError):
            executar(cfg)

    def test_utiliza_apenas_agregado_municipal_sem_identificadores(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["mapa"]
        path = Path(self.tmp.name) / "agregado.json"
        path.write_text(json.dumps({
            "fonte": "MAPA SIPEAGRO ALIMENTAÇÃO ANIMAL",
            "licenca_catalogo": "Creative Commons Attribution",
            "sha256_arquivo": "a" * 64,
            "data_coleta_utc": "2026-10-17T03:00:00Z",
            "municipios_distintos_com_fabricante_ativo_racao": 1,
            "municipios_candidatos": [
                {"uf": "GO", "municipio": "RIO VERDE", "registros_distintos": 2}
            ],
        }), encoding="utf-8")
        cfg["mapa_agregado"] = str(path)
        r = executar(cfg)
        self.assertEqual(r["destinos"][0]["classe"], "AMBIGUO")
        self.assertEqual(r["auditoria_importacao"]["modo_cadastro"],
                         "AGREGADO_MUNICIPAL_SEM_IDENTIFICADORES")
        self.assertEqual(r["auditoria_importacao"]["municipios_racao_candidatos"], 1)
        self.assertIsNone(r["auditoria_importacao"]["total_linhas_cadastrais_ou_nulo"])

    def test_duas_entradas_mapa_simultaneas_rejeitadas(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["mapa_agregado"] = "falso.json"
        with self.assertRaises(ValueError):
            executar(cfg)

    def test_alteracao_layout_delimitador_explicito(self):
        cfg = copy.deepcopy(self.cfg)
        path = Path(cfg["mapa"]["caminho"])
        path.write_text(path.read_text(encoding="utf-8").replace(";", ","), encoding="utf-8")
        cfg["mapa"]["delimitador"] = ","
        r = executar(cfg)
        self.assertEqual(r["auditoria_importacao"]["registros_fabricante_ativo_alimentacao_animal"], 1)


if __name__ == "__main__":
    unittest.main()
