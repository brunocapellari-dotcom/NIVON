"""Integração entre PTAX, coverage, auditoria e editor do NIVON.

Todos os dados e os catálogos deste teste são FICTÍCIOS. Mesmo que o
cenário marque REAL_AUTORIZADO para exercitar o gate, ele não torna
uma resposta sintética real nem aprova a publicação.
"""
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta

from nivon.captura_ptax_http import capturar_ptax_odata
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_raw_sqlite import guardar_raw_ptax
from nivon.pipeline_api_dados import ingerir_json_local
from nivon.ptax_cobertura_mercados import diagnosticar_cobertura_ptax
from nivon.indicadores_historicos import compor_pacote_historico, ErroPonte
from nivon.registro_snapshots import abrir_registro
from nivon.rotina_diaria import preparar_rotina

CAT = {"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                    "enabled":True,"collection_authorized":True}]}
DIREITOS = frozenset({"COLETA","ARMAZENAMENTO"})
FONTES = {"BCB_PTAX":{"status_direitos":"APROVADA",
                      "operacoes":["LEITURA","PUBLICACAO_DERIVADA"]}}
T = datetime(2026,10,21,18,0,tzinfo=timezone.utc)
PLAN = planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-19",fim="2026-10-21",
)[0]


def buf(*, tipo="Fechamento", v="5.1000", d="2026-10-20"):
    kind = ',"tipoBoletim":"'+tipo+'"' if tipo is not None else ""
    return ('{"value":[{"cotacaoCompra":'+v+
            ',"cotacaoVenda":5.2000,"dataHoraCotacao":"'+
            d+' 13:03:00"'+kind+'}]}').encode()


def pacote_para_briefing(db_mercados, db_raw, *, fontes=FONTES):
    return compor_pacote_historico(
        db_conab=None,db_portos=None,
        db_mercados=db_mercados,db_ptax_raw=db_raw,
        incluir_ptax_usd=True,modo_ptax="AUDITAR_RAW",
        fontes=fontes,gerado_em=T.isoformat(),
    )


def inserir(db, payload, *, real=False, coleta=T):
    tipo="REAL_AUTORIZADO" if real else "SINTETICO"
    ingerir_json_local(
        db,CAT,dataset_id="BCB_PTAX",payload=payload,
        plano=PLAN,coletado_em=coleta.isoformat(),
        tipo=tipo,autorizacoes=DIREITOS if real else frozenset(),
        evidencia_direitos="TESTE_DIREITOS_FICTICIOS" if real else None,
    )
    cap=capturar_ptax_odata(
        PLAN,transporte=lambda _: (200,{"content-type":"application/json"},payload),
        relogio=lambda:coleta,
    )
    if real:
        cap={**cap,"tipo":"REAL_AUTORIZADO",
             "origem_execucao":"HTTP_HTTPS_BCB_REAL_NAO_HOMOLOGADO"}
    guardar_raw_ptax(
        db,CAT,cap,
        autorizacoes=DIREITOS if real else frozenset(),
        evidencia_direitos="TESTE_DIREITOS_FICTICIOS" if real else None,
    )


class TestPonteEditorialPTAX(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def test_cobertura_multiplas_datas_sem_publicacao(self):
        inserir(self.db,buf(d="2026-10-19"))
        inserir(self.db,buf(v="5.1200",d="2026-10-20"))
        r=diagnosticar_cobertura_ptax(
            self.db,corte=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(r["status"],"COBERTURA_FECHAMENTO_RAW_SEM_PUBLICACAO")
        self.assertEqual(r["fechamentos_comprovados_no_raw"],2)
        self.assertEqual(r["dias_referencia"],["2026-10-19","2026-10-20"])
        self.assertFalse(r["pode_informar_motor_preditivo"])
        self.assertFalse(r["calendario_oficial_validado"])
        self.assertIsNone(r["sessoes_sem_cobertura"])

    def test_ambiguidade_fechamento_impede_classificacao(self):
        inserir(self.db,buf(tipo=None))
        r=diagnosticar_cobertura_ptax(
            self.db,corte=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(r["status"],"SEM_FECHAMENTO_EXPLICITO_NO_CORTE")
        self.assertEqual(r["boletins_sem_tipo"],1)
        self.assertEqual(r["serie"],[])

    def test_vintages_conflitantes_no_mesmo_dia_bloqueiam(self):
        inserir(self.db,buf(v="5.1000"))
        inserir(self.db,buf(v="5.1200"))
        r=diagnosticar_cobertura_ptax(
            self.db,corte=T.isoformat(),incluir_sinteticos=True,
        )
        self.assertEqual(r["status"],"FECHAMENTOS_CONFLITANTES")
        self.assertFalse(r["publicavel"])

    def test_corte_ignora_coleta_futura(self):
        inserir(self.db,buf(),coleta=T)
        cutoff=(T-timedelta(seconds=1)).isoformat()
        r=diagnosticar_cobertura_ptax(
            self.db,corte=cutoff,incluir_sinteticos=True,
        )
        self.assertEqual(r["capturas_consultadas"],0)

    def test_default_nunca_considera_fixture_sintetica(self):
        inserir(self.db,buf())
        r=diagnosticar_cobertura_ptax(self.db,corte=T.isoformat())
        self.assertEqual(r["capturas_consultadas"],0)

    def test_pacote_auditado_contem_status_mas_nao_indicador(self):
        # Testa literalmente o caminho 'REAL' com autorização FICTÍCIA
        # só para validar o gate de publicação. Nenhum dado BCB foi lido.
        inserir(self.db,buf(),real=True)
        p=pacote_para_briefing(self.db,self.db)
        self.assertEqual(p["resultados"][0]["status"],
                         "AUDITORIA_PTAX_RAW_SEM_LIBERACAO_EDITORIAL")
        self.assertEqual(p["resultados"][0]["paridade"]["status"],
                         "PARIDADE_NUMERICA_MESMA_EDICAO_OFFLINE")
        self.assertEqual(p["resultados"][0]["cobertura"]
                         ["fechamentos_comprovados_no_raw"],1)
        self.assertEqual(p["pacote"]["indicadores"],[])
        self.assertFalse(p["resultados"][0]["publicavel"])
        r=preparar_rotina(
            pacote=p["pacote"],gerado_em=T.isoformat(),
            obrigatorias=frozenset({"CAMBIO"}),
            auditor=lambda _:True,
        )
        self.assertEqual(r["status"],"BLOQUEADO_INDICADORES_ESSENCIAIS")
        self.assertFalse(r["agendado"])

    def test_pacote_com_vintage_sintetica_nao_promove(self):
        inserir(self.db,buf())
        p=pacote_para_briefing(self.db,self.db)
        self.assertEqual(p["resultados"][0]["paridade"]["status"],
                         "COMPARACAO_INCOMPLETA")
        self.assertEqual(p["pacote"]["indicadores"],[])

    def test_direitos_faltantes_auditoria_nao_divulga(self):
        inserir(self.db,buf(),real=True)
        p=pacote_para_briefing(self.db,self.db,fontes={})
        self.assertEqual(p["resultados"][0]["paridade"]["status"],
                         "BLOQUEADO_DIREITOS")
        self.assertEqual(p["pacote"]["indicadores"],[])

    def test_versao_ptax_desconhecida_rejeita(self):
        with self.assertRaisesRegex(ErroPonte,"modo PTAX"):
            compor_pacote_historico(
                db_conab=None,db_portos=None,
                db_mercados=self.db,incluir_ptax_usd=True,
                fontes=FONTES,gerado_em=T.isoformat(),
                modo_ptax="LIBERADO_AUTOMATICO",
            )

    def test_pacote_legado_persiste_sem_alteracao_de_default(self):
        inserir(self.db,buf(),real=True)
        p=compor_pacote_historico(
            db_conab=None,db_portos=None,
            db_mercados=self.db,incluir_ptax_usd=True,
            fontes=FONTES,gerado_em=T.isoformat(),
        )
        self.assertEqual(p["resultados"][0]["status"],
                         "INDICADOR_VERIFICADO_TEMPO")
        self.assertEqual(len(p["pacote"]["indicadores"]),1)


if __name__=="__main__":
    unittest.main()
