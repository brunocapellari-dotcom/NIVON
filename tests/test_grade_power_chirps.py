"""Ensaios offline da persistência em grade NASA e pêntadas CHIRPS v3."""
import json
import unittest

from nivon.nasa_power_diario import planejar_power
from nivon.grade_meteorologica_store import (
    ErroGrade, abrir_grade, ingerir_power_local, grade_asof,
)
from nivon.chirps_v3_conservacao import (
    ErroCHIRPS, dias_pentada, reconciliar_chirps_pentada,
)

def plano():
    return planejar_power(latitude=-12.54,longitude=-55.72,
                          inicio="2025-01-01",fim="2025-01-03",
                          parametros=("PRECTOTCORR","T2M_MIN","T2M_MAX"))

def raw(chuva=10):
    return json.dumps({"properties":{"parameter":{
        "PRECTOTCORR":{"20250101":chuva,"20250102":0,"20250103":-999},
        "T2M_MIN":{"20250101":20,"20250102":21,"20250103":19},
        "T2M_MAX":{"20250101":30,"20250102":31,"20250103":32}
    }}},sort_keys=True).encode()

def salvar(db,conteudo=None,pub="2025-01-04T09:00:00Z",coleta="2025-01-04T12:00:00Z",**extra):
    return ingerir_power_local(db,bytes_json=raw() if conteudo is None else conteudo,
                               plano=plano(),coletado_em=coleta,publicado_em=pub,**extra)

def serie(db,ident,**overrides):
    defaults=dict(consulta_sha256=ident,parametro="PRECTOTCORR",
                  inicio="2025-01-01",fim="2025-01-03",
                  corte_publicacao="2025-01-20T00:00:00Z",
                  corte_coleta="2025-01-20T00:00:00Z")
    return grade_asof(db,**(defaults|overrides))

class TestGradePowerTemporal(unittest.TestCase):
    def setUp(self):
        self.db=abrir_grade()
        self.addCleanup(self.db.close)

    def test_idempotencia_e_ausencia_sem_zero(self):
        a=salvar(self.db)
        b=salvar(self.db)
        self.assertTrue(a["nova_edicao"])
        self.assertFalse(b["nova_edicao"])
        self.assertFalse(b["nova_captura"])
        rows=serie(self.db,a["consulta_sha256"])
        self.assertEqual(len(rows),3)
        self.assertEqual([r["valor"] for r in rows],[10.,0.,None])
        self.assertFalse(a["apto_para_treino_temporal"])

    def test_revisoes_temporais_sem_vazamento(self):
        a=salvar(self.db)
        salvar(self.db,conteudo=raw(chuva=13),pub="2025-01-06T09:00:00Z",
              coleta="2025-01-06T10:00:00Z")
        before=serie(self.db,a["consulta_sha256"],
               corte_publicacao="2025-01-05T00:00:00Z",
               corte_coleta="2025-01-05T00:00:00Z")
        after=serie(self.db,a["consulta_sha256"])
        self.assertEqual(before[0]["valor"],10.)
        self.assertEqual(after[0]["valor"],13.)
        hidden=serie(self.db,a["consulta_sha256"],
               corte_publicacao="2025-01-20T00:00:00Z",
               corte_coleta="2025-01-05T00:00:00Z")
        self.assertEqual(hidden[0]["valor"],10.)

    def test_fonte_sem_publicacao_nao_e_retroprevisao(self):
        a=salvar(self.db,pub=None)
        self.assertFalse(a["publicacao_conhecida"])
        self.assertEqual(serie(self.db,a["consulta_sha256"]),[])

    def test_rejeita_real_sem_direitos_por_operacao(self):
        with self.assertRaises(PermissionError):
            salvar(self.db,classe="REAL_AUTORIZADO")
        ok=salvar(self.db,classe="REAL_AUTORIZADO",
            permissoes=frozenset({"COLETA","ARMAZENAMENTO"}),
            licenca_evidencia="Permissao_documentada_2026")
        self.assertEqual(ok["classe"],"REAL_AUTORIZADO")
        self.assertFalse(ok["coleta_ativa"])

    def test_coleta_repetida_gera_vintage_sem_nova_edicao(self):
        a=salvar(self.db)
        b=salvar(self.db,coleta="2025-01-07T09:00:00Z")
        self.assertEqual(a["conteudo_sha256"],b["conteudo_sha256"])
        self.assertFalse(b["nova_edicao"])
        self.assertTrue(b["nova_captura"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grade_valor").fetchone()[0],9)

    def test_publicacao_apos_coleta_bloqueada(self):
        with self.assertRaises(ErroGrade):
            salvar(self.db,pub="2025-01-08T00:00:00Z")

def itens(ano,mes,pentada,produto="sat",estado="FINAL",chuva=2.0):
    return [{"data":d,"chuva_mm":chuva,"produto":produto,
             "versao":"3.0","estado":estado}
            for d in dias_pentada(ano,mes,pentada)]

def fechar(ano,mes,pentada,rows,**extra):
    return reconciliar_chirps_pentada(
         ano=ano,mes=mes,pentada=pentada,
         chuva_total_pentada_mm=len(rows)*2.,
         chuva_diaria=rows,diario_tipo="sat",estado="FINAL",
         versao="3.0",fonte_temporal="CHIRPS3_sat_rastreador_2026",**extra)

class TestConservacaoCHIRPS(unittest.TestCase):
    def test_pentada_sexta_fevereiro_bissexto(self):
        self.assertEqual(dias_pentada(2024,2,6),
                         ["2024-02-26","2024-02-27","2024-02-28","2024-02-29"])
        x=itens(2024,2,6)
        r=fechar(2024,2,6,x)
        self.assertEqual(r["erro_conservacao_mm"],0)
        self.assertEqual(r["dias"],4)

    def test_pentada_sexta_mes_de_31(self):
        self.assertEqual(len(dias_pentada(2026,10,6)),6)
        x=itens(2026,10,6)
        self.assertEqual(fechar(2026,10,6,x)["dias"],6)

    def test_pentada_total_diferente_bloqueia(self):
        x=itens(2026,10,1)
        x[0]["chuva_mm"]=9.
        with self.assertRaises(ErroCHIRPS):
            fechar(2026,10,1,x)

    def test_produto_rnl_e_sat_nao_misturados(self):
        x=itens(2026,10,1)
        x[0]["produto"]="rnl"
        with self.assertRaises(ErroCHIRPS):
            fechar(2026,10,1,x)

    def test_nao_misturar_preliminar_final(self):
        x=itens(2026,10,1)
        x[0]["estado"]="PRELIMINAR"
        with self.assertRaises(ErroCHIRPS):
            fechar(2026,10,1,x)

    def test_dias_faltantes_duplicados_chuva_negativa(self):
        x=itens(2026,10,1)
        with self.assertRaises(ErroCHIRPS):fechar(2026,10,1,x[:-1])
        y=itens(2026,10,1);y[1]["data"]=y[0]["data"]
        with self.assertRaises(ErroCHIRPS):fechar(2026,10,1,y)
        y=itens(2026,10,1);y[1]["chuva_mm"]=-999
        with self.assertRaises(ErroCHIRPS):fechar(2026,10,1,y)

if __name__=="__main__":
    unittest.main()
