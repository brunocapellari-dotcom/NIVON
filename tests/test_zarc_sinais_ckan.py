"""CKAN ZARC versão observada é sinal, nunca comprovação de CSV novo."""
import unittest
from nivon.zarc_sinais_ckan import (
    RESOURCE_ID,ErroZarcCKAN,abrir_historico_zarc_meta,
    normalizar_sinal,registrar_sinal,verificar_fonte_ckan,
)
CSV=("https://dados.agricultura.gov.br/dataset/"
     "6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/"
     +RESOURCE_ID+
     "/download/dados-abertos-tabua-de-risco-safra-2026-2027.csv")

def fixture(version="rev-a",date="2026-10-22T12:00:00Z",license_id="cc-by"):
    return {
        "fonte_id":"MAPA_ZARC","licenca_declarada":license_id,
        "revision_id":"pkg-1","atualizado_em":"2026-10-21T10:00:00",
        "coleta":date,
        "recursos":[{"id":RESOURCE_ID,"formato":"CSV",
                     "url_somente_referencia":CSV,
                     "revision_id":version,
                     "atualizado_em":"2026-10-22T11:00:00"}],
    }

class TestZarcCKAN(unittest.TestCase):
    def setUp(self):
        self.db=abrir_historico_zarc_meta()
        self.addCleanup(self.db.close)

    def test_primeira_observacao_nao_afirma_csv_novo(self):
        r=normalizar_sinal(fixture())
        out=registrar_sinal(self.db,r)
        self.assertFalse(out["sinal_revision_changed"])
        self.assertFalse(out["pode_afirmar_novo_csv"])
        self.assertFalse(out["csv_baixado"])
        self.assertEqual(out["observacoes"],1)
        self.assertIsNone(r["versao_csv_sha256"])
        self.assertFalse(r["consegue_provar_arquivo_alterado"])

    def test_mesmo_metadado_coletas_distintas_idempotentes(self):
        r1=normalizar_sinal(fixture())
        r2=normalizar_sinal(fixture(date="2026-10-23T12:00:00Z"))
        registrar_sinal(self.db,r1)
        changed=registrar_sinal(self.db,r2)
        self.assertFalse(changed["sinal_revision_changed"])
        self.assertFalse(registrar_sinal(self.db,r2)["sinal_revision_changed"])
        self.assertEqual(changed["observacoes"],2)

    def test_mudanca_revision_e_sinal_nao_arquivo_provado(self):
        registrar_sinal(self.db,normalizar_sinal(fixture()))
        r=normalizar_sinal(fixture(version="rev-b",date="2026-10-23T12:00:00Z"))
        d=registrar_sinal(self.db,r)
        self.assertTrue(d["sinal_sugere_reavaliacao_csv"])
        self.assertFalse(d["pode_afirmar_novo_csv"])
        self.assertEqual(d["observacoes"],2)

    def test_mesmo_instante_conflitante_e_rollback(self):
        registrar_sinal(self.db,normalizar_sinal(fixture()))
        with self.assertRaises(ErroZarcCKAN):
            registrar_sinal(self.db,normalizar_sinal(fixture(version="new")))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM zarc_sinais_ckan").fetchone()[0],1)

    def test_licenca_nao_reconhecida_bloqueia(self):
        with self.assertRaises(ErroZarcCKAN):
            normalizar_sinal(fixture(license_id="unknown"))

    def test_url_malformada_nao_baixar(self):
        m=fixture()
        m["recursos"][0]["url_somente_referencia"]="https://attacker.example/arquivo.csv"
        with self.assertRaises(ErroZarcCKAN):
            normalizar_sinal(m)

    def test_invalido_recurso_sem_fuso(self):
        m=fixture()
        m["recursos"][0]["id"]="outro"
        with self.assertRaises(ErroZarcCKAN):
            normalizar_sinal(m)
        with self.assertRaises(ErroZarcCKAN):
            normalizar_sinal(fixture(date="2026-10-22T12:00:00"))

    def test_rede_optin(self):
        with self.assertRaises(PermissionError):
            verificar_fonte_ckan()

if __name__=="__main__":
    unittest.main()
