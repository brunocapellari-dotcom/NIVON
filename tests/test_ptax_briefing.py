import hashlib
import json
import unittest
from datetime import datetime, timezone

from nivon.ptax_plano import planejar_consultas_ptax
from nivon.ptax_briefing import (
    LICENCA,ErroPTAXBriefing,adquirir_ptax_autorizado,
    normalizar_snapshot_ptax,construir_indicador_ptax
)
from nivon.briefing_composto import montar_briefing

AGORA="2026-10-20T10:00:00-03:00"
COLETA="2026-10-20T09:00:00-03:00"


def plano():
    return planejar_consultas_ptax(moeda="USD",inicio="2026-10-19",fim="2026-10-20")[0]


def dados_boletins(sem_fechamento=False):
    rows=[
        {"cotacaoCompra":5.01,"cotacaoVenda":5.02,
         "dataHoraCotacao":"2026-10-19 10:00:00","tipoBoletim":"Abertura"},
        {"cotacaoCompra":5.03,"cotacaoVenda":5.04,
         "dataHoraCotacao":"2026-10-19 12:00:00","tipoBoletim":"Fechamento Interbancário"},
    ]
    if not sem_fechamento:
        rows.append({"cotacaoCompra":5.05,"cotacaoVenda":5.06,
             "dataHoraCotacao":"2026-10-19 13:00:00","tipoBoletim":"Fechamento"})
    return json.dumps({"value":rows}).encode("utf-8")


def dataset(aprovado=True):
    return {"id":"BCB_PTAX","enabled":aprovado,
            "collection_authorized":aprovado,
            "commercial_redistribution_authorized":aprovado}


def direitos():
    return {"status":"APROVADA",
            "operacoes":["LEITURA","COLETA","ARMAZENAMENTO",
                         "PUBLICACAO_DERIVADA","REDISTRIBUICAO"],
            "evidencia_id":"EVIDENCIA_SINTETICA_20261020",
            "licenca":LICENCA,
            "attribution_reviewed":True,
            "share_alike_reviewed":True}


class Resposta:
    def __init__(self,url,data,mime="application/json"):
        self.status=200
        self.url=url
        self.data=data
        self.headers={"Content-Type":mime}
    def geturl(self):return self.url
    def read(self,n):return self.data[:n]
    def __enter__(self):return self
    def __exit__(self,*args):return None


class Cliente:
    def __init__(self,data,wrong_url=None,mime="application/json"):
        self.data=data;self.url=wrong_url;self.mime=mime;self.calls=0
    def open(self,request,timeout):
        self.calls+=1
        return Resposta(self.url or request.full_url,self.data,self.mime)


class TestPTAXBriefing(unittest.TestCase):
    def processar(self,bytes_json=None,aprovado=True):
        client=Cliente(bytes_json if bytes_json is not None else dados_boletins())
        snap=adquirir_ptax_autorizado(plano(),dataset=dataset(aprovado),
                           direitos=direitos(),coletado_em=COLETA,abridor=client)
        result=normalizar_snapshot_ptax(snap,plano())
        return result,client

    def test_pipeline_bcb_fechar_e_entrar_no_briefing(self):
        x,client=self.processar()
        self.assertEqual(client.calls,1)
        r=construir_indicador_ptax(x,gerado_em=AGORA,dataset=dataset(),direitos=direitos())
        self.assertEqual(r["indicador"]["secao"],"CAMBIO")
        self.assertIn("5.0600",r["indicador"]["valor"])
        self.assertEqual(r["evidencia"]["cotacao_compra"],"5.05")
        self.assertIn("ODbL",r["indicador"]["fonte"])
        msg=montar_briefing(noticias=[],fontes=r["fonte_briefing"],data=AGORA,
                           indicadores=[r["indicador"]])
        self.assertEqual(msg["indicadores_incluidos"],1)
        self.assertIn("PTAX fechamento",msg["texto"])
        self.assertNotIn("5.0400",msg["texto"])
        self.assertEqual(msg["status"],"PREPARADO_SEM_ENVIO")

    def test_sem_licenca_ou_dataset_nao_consulta_rede(self):
        client=Cliente(dados_boletins())
        with self.assertRaises(PermissionError):
            adquirir_ptax_autorizado(plano(),dataset=dataset(False),
                                    direitos=direitos(),coletado_em=COLETA,abridor=client)
        self.assertEqual(client.calls,0)
        dr=direitos();dr["licenca"]="UNKNOWN"
        with self.assertRaises(PermissionError):
            adquirir_ptax_autorizado(plano(),dataset=dataset(),
                                    direitos=dr,coletado_em=COLETA,abridor=client)
        self.assertEqual(client.calls,0)

    def test_plano_adulterado_rejeitado_antes_da_rede(self):
        q=plano();q["url"]="https://olinda.bcb.gov.br/odata/qualquer"
        client=Cliente(dados_boletins())
        with self.assertRaises(ErroPTAXBriefing):
            adquirir_ptax_autorizado(q,dataset=dataset(),direitos=direitos(),
                                    coletado_em=COLETA,abridor=client)
        self.assertEqual(client.calls,0)

    def test_intradiario_nao_passa_por_fechamento(self):
        x,_=self.processar(dados_boletins(sem_fechamento=True))
        with self.assertRaisesRegex(ErroPTAXBriefing,"Fechamento"):
            construir_indicador_ptax(x,gerado_em=AGORA,
                                    dataset=dataset(),direitos=direitos())

    def test_sem_homologacao_redistribuicao_nao_publica(self):
        x,_=self.processar()
        with self.assertRaises(PermissionError):
            construir_indicador_ptax(x,gerado_em=AGORA,
                                    dataset=dataset(False),direitos=direitos())
        dr=direitos();dr["share_alike_reviewed"]=False
        with self.assertRaises(PermissionError):
            construir_indicador_ptax(x,gerado_em=AGORA,
                                    dataset=dataset(),direitos=dr)

    def test_snapshot_alterado_rejeita(self):
        client=Cliente(dados_boletins())
        snap=adquirir_ptax_autorizado(plano(),dataset=dataset(),direitos=direitos(),
                           coletado_em=COLETA,abridor=client)
        snap["conteudo"]=b'{"value":[]}'
        with self.assertRaisesRegex(ErroPTAXBriefing,"hash"):
            normalizar_snapshot_ptax(snap,plano())

    def test_boletim_de_data_futura_nao_aceita(self):
        lines=[{"cotacaoCompra":5.05,"cotacaoVenda":5.06,
                "dataHoraCotacao":"2026-10-21 13:00:00","tipoBoletim":"Fechamento"}]
        client=Cliente(json.dumps({"value":lines}).encode())
        snap=adquirir_ptax_autorizado(plano(),dataset=dataset(),direitos=direitos(),
                           coletado_em=COLETA,abridor=client)
        with self.assertRaises(ErroPTAXBriefing):
            normalizar_snapshot_ptax(snap,plano())

    def test_defasagem_pelo_dia_de_brasilia_nao_pelo_utc(self):
        x,_=self.processar()
        r=construir_indicador_ptax(
            x,gerado_em="2026-10-20T23:30:00-03:00",
            dataset=dataset(),direitos=direitos(),atraso_maximo_dias=1)
        self.assertIn("5.0600",r["indicador"]["valor"])

    def test_boletim_muito_antigo_nao_e_preco_do_dia(self):
        x,_=self.processar()
        with self.assertRaisesRegex(ErroPTAXBriefing,"antigo"):
            construir_indicador_ptax(x,gerado_em="2026-11-01T09:00:00-03:00",
                                    dataset=dataset(),direitos=direitos())

    def test_url_provedor_diferente_rejeitada(self):
        client=Cliente(dados_boletins(),wrong_url="https://outro.example.org/data.json")
        with self.assertRaises(Exception):
            adquirir_ptax_autorizado(plano(),dataset=dataset(),direitos=direitos(),
                                    coletado_em=COLETA,abridor=client)

    def test_json_com_chave_duplicada_rejeitado(self):
        x=b'{"value": [], "value": [{"cotacaoCompra":1}]}'
        client=Cliente(x)
        snap=adquirir_ptax_autorizado(plano(),dataset=dataset(),direitos=direitos(),
                           coletado_em=COLETA,abridor=client)
        with self.assertRaisesRegex(ErroPTAXBriefing,"duplicada"):
            normalizar_snapshot_ptax(snap,plano())


if __name__=="__main__":
    unittest.main()
