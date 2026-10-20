import json,unittest
from datetime import date
from nivon.pipeline_historico_nasa import HistoricoNASA,planejar_retrocarga
from nivon.catalogo_fontes import carregar_catalogo
from nivon.vinculo_historico_nasa import vincular_nasa_ao_ledger
from nivon.registro_snapshots import abrir_registro,visao_asof
from nivon.qualidade_cientifica import ErroCientifico


class TestLedgerNasa(unittest.TestCase):
    def setUp(self):
        self.raw=HistoricoNASA()
        self.db=abrir_registro()
        self.cat=carregar_catalogo()
        lot=planejar_retrocarga(latitudes_longitudes=[(-12.4,-55.6)],
            inicio=date(2025,1,1),fim=date(2025,1,2),
            parametros=("PRECTOTCORR",))["lotes"][0]
        blob=json.dumps({"type":"Feature",
            "geometry":{"coordinates":[-55.6,-12.4]},
            "properties":{"parameter":{"PRECTOTCORR":{
                "20250101":2.5,"20250102":6.0}}}}).encode()
        self.sha=self.raw.importar_raw(lote=lot,resposta_json=blob,
                         coletado_em="2026-10-20T12:00:00Z")["raw_sha256"]
    def tearDown(self):
        self.raw.fechar();self.db.close()
    def bind(self,**kw):
        return vincular_nasa_ao_ledger(raw=self.raw,ledger=self.db,
                    catalogo=self.cat,sha=self.sha,**kw)

    def test_canonico_idempotente_nao_retroage_vintage(self):
        a=self.bind()
        self.assertTrue(a["nova_versao"])
        self.assertEqual(a["tipo"],"SINTETICO")
        self.assertFalse(a["backtest_historico_asof_permitido"])
        b=self.bind()
        self.assertFalse(b["nova_versao"])
        self.assertFalse(b["nova_coleta"])
        self.assertIsNone(visao_asof(self.db,dataset_id="NASA_POWER_AGRO_DAILY",
            corte_coleta="2026-10-20T13:00:00Z",corte_publicacao="2026-10-20"))

    def test_sintetico_nao_adquire_direito_com_flag(self):
        with self.assertRaises(ErroCientifico):
            self.bind(autorizacoes=frozenset({"COLETA","ARMAZENAMENTO"}),
                      evidencia_direitos="REF-FAKE-01")

    def test_raw_adulterado_nao_entra_no_ledger(self):
        self.raw.conn.execute("UPDATE raw_nasa SET raw_bytes=? WHERE raw_sha256=?",
                              (b"corrupted",self.sha))
        with self.assertRaises(ErroCientifico):self.bind()
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)


if __name__=="__main__":unittest.main()
