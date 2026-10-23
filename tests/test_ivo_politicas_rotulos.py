import json
import unittest
from copy import deepcopy
from pathlib import Path

from nivon.ivo_politicas_rotulos import (
    ErroPoliticas,carregar_politicas,auditar_politicas_rotulos,
)

ROOT=Path(__file__).resolve().parents[1]


def catalogo():
    return json.loads((ROOT/"config"/"fontes_nivon_master.v1.json").read_text())


class TestIVOPoliticasRotulos(unittest.TestCase):
    def setUp(self):
        self.catalogo=catalogo()
        self.politicas=carregar_politicas()

    def test_catalogo_real_casa_todas_as_politicas(self):
        x=auditar_politicas_rotulos(self.catalogo,self.politicas)
        self.assertEqual(x["fontes_catalogadas"],11)
        self.assertEqual(x["fontes_prontas_para_treino_real"],0)
        self.assertEqual(x["fontes_aguardando_homologacao"],11)
        self.assertTrue(all(not d["treinamento_real_habilitado"] for d in x["detalhes"]))
        self.assertIn("DIREITO_DE_TREINAMENTO",
             next(d for d in x["detalhes"] if d["dataset_id"]=="CONAB_GRAOS_SERIES")["pendencias"])

    def test_nunca_transforma_coleta_em_treino(self):
        catalog=deepcopy(self.catalogo)
        d=next(d for d in catalog["datasets"] if d["id"]=="CONAB_GRAOS_SERIES")
        d["enabled"]=True
        d["collection_authorized"]=True
        out=auditar_politicas_rotulos(catalog,self.politicas)
        subset=next(x for x in out["detalhes"] if x["dataset_id"]=="CONAB_GRAOS_SERIES")
        self.assertFalse(subset["treinamento_real_habilitado"])
        self.assertIn("DIREITO_DE_TREINAMENTO",subset["pendencias"])
        self.assertNotIn("DIREITO_DE_COLETA",subset["pendencias"])

    def test_marcacao_manual_tudo_true_nao_pula_auditoria_label(self):
        catalog=deepcopy(self.catalogo)
        d=next(d for d in catalog["datasets"] if d["id"]=="INMET_ESTACOES")
        d.update(enabled=True,collection_authorized=True,training_authorized=True)
        out=auditar_politicas_rotulos(catalog,self.politicas)
        subset=next(x for x in out["detalhes"] if x["dataset_id"]=="INMET_ESTACOES")
        self.assertIn("AUDITORIA_INDEPENDENTE_E_HOMOLOGACAO",subset["pendencias"])
        self.assertFalse(subset["treinamento_real_habilitado"])

    def test_politica_sem_restricao_negativa_rejeitada(self):
        p=deepcopy(self.politicas)
        p["automatic_approval"]=True
        with self.assertRaises(ErroPoliticas):
            auditar_politicas_rotulos(self.catalogo,p)

    def test_dataset_id_trocado_bloqueado(self):
        p=deepcopy(self.politicas)
        p["source_policies"][0]["id"]="FONTE_INEXISTENTE"
        with self.assertRaises(ErroPoliticas):
            auditar_politicas_rotulos(self.catalogo,p)

    def test_status_nao_homologado_desconhecido_rejeitado(self):
        p=deepcopy(self.politicas)
        p["source_policies"][0]["status"]="APROVADO"
        with self.assertRaises(ErroPoliticas):
            auditar_politicas_rotulos(self.catalogo,p)

    def test_politicas_repetidas_rejeitadas(self):
        p=deepcopy(self.politicas)
        p["source_policies"].append(deepcopy(p["source_policies"][0]))
        with self.assertRaises(ErroPoliticas):
            auditar_politicas_rotulos(self.catalogo,p)

    def test_trocar_fonte_do_dataset_rejeitado(self):
        p=deepcopy(self.politicas)
        p["source_policies"][0]["source_id"]="INMET"
        with self.assertRaises(ErroPoliticas):
            auditar_politicas_rotulos(self.catalogo,p)


if __name__=="__main__":
    unittest.main()
