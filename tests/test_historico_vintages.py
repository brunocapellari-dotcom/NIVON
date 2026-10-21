import hashlib
import unittest
from nivon.qualidade_cientifica import ErroCientifico
from nivon.historico_vintages import ArmazemVintages,normalizar_edicao


def item(edicao,valor,publicado,coletado="2026-10-20T08:00:00-04:00",
         disponivel=None):
    return dict(source_id="CONAB",dataset_id="CONAB_GRAOS_SERIES",
        serie_id="MT/SOJA/PRODUCAO_T",competencia="2025/26",
        referencia="2026-01-01",edicao_id=edicao,unidade="t",valor=valor,
        classe_evidencia="ESTIMADO",publicado_em=publicado,
        disponivel_em=disponivel if disponivel is not None else publicado,
        coletado_em=coletado,fonte_url="https://www.gov.br/conab/",
        raw_sha256=hashlib.sha256(edicao.encode()).hexdigest(),
        disponibilidade_verificada=True,
        prova_disponibilidade_sha256=hashlib.sha256(("evidence-"+edicao).encode()).hexdigest())


class TestVintages(unittest.TestCase):
    def setUp(self):self.s=ArmazemVintages(":memory:")
    def tearDown(self):self.s.fechar()
    def q(self,when):
        return self.s.consultar_asof(dataset_id="CONAB_GRAOS_SERIES",
          serie_id="MT/SOJA/PRODUCAO_T",competencia="2025/26",instante_decisao=when)

    def test_vintages_nao_vazam_revisao_futura(self):
        a=item("2026-01", "1000.0","2026-01-12T09:00:00-04:00")
        b=item("2026-04", "1200.0","2026-04-12T09:00:00-04:00")
        self.assertEqual(self.s.gravar(b),"EDICAO_PERSISTIDA_LOCALMENTE")
        self.assertEqual(self.s.gravar(a),"EDICAO_PERSISTIDA_LOCALMENTE")
        self.assertIsNone(self.q("2026-01-11T12:00:00-04:00"))
        self.assertEqual(self.q("2026-02-01T12:00:00-04:00")["valor_decimal"],1000)
        self.assertEqual(self.q("2026-06-01T12:00:00-04:00")["valor_decimal"],1200)
        self.assertEqual(self.s.contar(),2)

    def test_edicao_idempotente_e_conflito_detectado(self):
        a=item("2026-01","1000","2026-01-12T09:00:00-04:00")
        self.s.gravar(a)
        self.assertEqual(self.s.gravar({**a,"coletado_em":"2026-10-20T09:00:00-04:00"}),"DUPLICATA_IDEMPOTENTE")
        with self.assertRaises(ErroCientifico):
            self.s.gravar({**a,"valor":"1001"})

    def test_falta_data_publicacao_exclui_backtest(self):
        a=item("2026-01","1000","2026-01-12T09:00:00-04:00")
        a["publicado_em"]=a["disponivel_em"]=None
        a["disponibilidade_verificada"]=False
        a["prova_disponibilidade_sha256"]=None
        self.s.gravar(a)
        self.assertIsNone(self.q("2026-10-20T08:00:00-04:00"))

    def test_temporalidade_erro(self):
        a=item("2026-01","1000","2026-10-21T09:00:00-04:00")
        with self.assertRaises(ErroCientifico):
            normalizar_edicao(a)
        b=item("2026-01","1000","2026-01-12T09:00:00-04:00",
               disponivel="2026-01-01T09:00:00-04:00")
        with self.assertRaises(ErroCientifico):
            normalizar_edicao(b)

    def test_sem_prova_nao_aceita_historico_asof(self):
        a=item("2026-01","1000","2026-01-12T09:00:00-04:00")
        a["disponibilidade_verificada"]=False
        a["prova_disponibilidade_sha256"]=None
        self.s.gravar(a)
        self.assertIsNone(self.q("2026-10-20T12:00:00-04:00"))
        b=item("2026-02","1100","2026-02-12T09:00:00-04:00")
        b["prova_disponibilidade_sha256"]=None
        with self.assertRaises(ErroCientifico):
            self.s.gravar(b)

    def test_numeros_ruins_bloqueados(self):
        a=item("2026-01","NaN","2026-01-12T09:00:00-04:00")
        with self.assertRaises(ErroCientifico):
            self.s.gravar(a)
        a["valor"]="1000.025"
        self.s.gravar(a)
        self.assertEqual(self.q("2026-10-19T12:00:00-04:00")["valor"],"1000.025")

    def test_nao_inferir_licenca_ou_go_live(self):
        self.assertEqual(self.s.contar(),0)
        # Persistência local é apenas índice para edição; RAW/licença/backup fora.
        self.assertIsNone(self.q("2026-10-20T12:00:00-04:00"))


if __name__=="__main__":
    unittest.main()
