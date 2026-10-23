"""PTAX: coletor de quarentena, arquivo Cloud e recuperação integrada.

HTTP e GCS dos testes são dublês em memória. Nenhum dado BCB
real é coletado e nenhuma operação Google Cloud é executada.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nivon.coletor_ptax_quarentena import (
    executar_coleta_ptax_quarentena, ErroColetaQuarentenaPTAX,
)
from nivon.ptax_quarentena_coleta import listar_amostras_ptax
from nivon.ptax_google_cloud import (
    preparar_objetos_gcs_ptax, enviar_objetos_gcs_ptax, ErroExportacaoPTAX,
)
from nivon.ptax_reconciliacao_gcs import reconciliar_gcs_ptax
from nivon.ptax_sincronizacao_gcs import sincronizar_pacote_ptax_gcs
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.registro_snapshots import abrir_registro

T=datetime(2026,10,22,16,0,tzinfo=timezone.utc)
P1=planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-20",fim="2026-10-20",
)[0]
P2=planejar_consultas_ptax(
    moeda="USD",inicio="2026-10-21",fim="2026-10-21",
)[0]
RAW=(b'{"value":[{"cotacaoCompra":5.10000,'
     b'"cotacaoVenda":5.20000,'
     b'"dataHoraCotacao":"2026-10-20 13:03:00",'
     b'"tipoBoletim":"Fechamento"}]}')
EMPTY=b'{"value":[]}'
CAT={"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                   "enabled":True,"collection_authorized":True}]}
DENIED={"datasets":[{"id":"BCB_PTAX","source_id":"BCB",
                      "enabled":False,"collection_authorized":False}]}
DIREITOS=frozenset({"COLETA","ARMAZENAMENTO"})


def http(url):
    data=RAW if url==P1["url"] else EMPTY
    return (200,{"Content-Type":"application/json",
                 "Content-Length":str(len(data))},data)


class Blob:
    def __init__(self,service,key):
        self.service=service
        self.key=key
    def upload_from_string(self,raw,*,content_type,if_generation_match,timeout):
        if self.key in self.service.files:
            raise RuntimeError("ja existe")
        if if_generation_match!=0:
            raise RuntimeError("overwrite")
        self.service.files[self.key]=raw
    def exists(self):
        return self.key in self.service.files
    def download_as_bytes(self,*,timeout):
        if self.service.erro:
            raise RuntimeError("rede indisponivel")
        return self.service.files[self.key]


class Bucket:
    def __init__(self,service):
        self.service=service
    def blob(self,key):
        return Blob(self.service,key)


class GCS:
    def __init__(self):
        self.files={}
        self.erro=False
    def bucket(self,name):
        return Bucket(self)


class TestColetaQuarentenaETL(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def run_fake(self,planos=None,fetch=http,**kw):
        return executar_coleta_ptax_quarentena(
            self.db,planos=[P1,P2] if planos is None else planos,
            catalogo=CAT,transporte=fetch,relogio=lambda:T,**kw,
        )

    def test_ingestao_duas_janelas_uma_vazia_uma_cotada(self):
        r=self.run_fake()
        self.assertEqual(r["status"],"CAPTURAS_PTAX_QUARENTENA_SEM_PROMOCAO")
        self.assertEqual(r["consultas"],2)
        self.assertEqual(r["boletins"],1)
        self.assertEqual(r["respostas_vazias"],1)
        self.assertEqual(r["tipo"],"SINTETICO")
        self.assertFalse(r["publicavel"])
        self.assertEqual(len(listar_amostras_ptax(self.db)),2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_coleta_e_armazenamento_sao_idempotentes(self):
        r1=self.run_fake()
        r2=self.run_fake()
        self.assertEqual(
            [x["evento_sha256"] for x in r1["linhas"]],
            [x["evento_sha256"] for x in r2["linhas"]])
        self.assertTrue(all(not x["nova_captura"] for x in r2["linhas"]))
        self.assertEqual(len(listar_amostras_ptax(self.db)),2)

    def test_primeiro_valido_segundo_erro_reverte_lote(self):
        def segundo_falha(url):
            if url==P2["url"]:
                return 503,{"content-type":"application/json"},b'{"value":[]}'
            return http(url)
        with self.assertRaises(ErroColetaQuarentenaPTAX):
            self.run_fake(fetch=segundo_falha)
        self.assertEqual(len(listar_amostras_ptax(self.db)),0)

    def test_prevalidacao_ambas_impede_adulteracao_json(self):
        def segundo_com_chaves_duplicadas(url):
            if url==P2["url"]:
                return 200,{"content-type":"application/json"},(
                    b'{"value":[],"value":[]}')
            return http(url)
        with self.assertRaises(ValueError):
            self.run_fake(fetch=segundo_com_chaves_duplicadas)
        self.assertEqual(len(listar_amostras_ptax(self.db)),0)

    def test_bloqueio_default_de_rede_e_cat_desligado(self):
        with self.assertRaises(PermissionError):
            executar_coleta_ptax_quarentena(
                self.db,planos=[P1],catalogo=CAT,
            )
        with self.assertRaises(PermissionError):
            executar_coleta_ptax_quarentena(
                self.db,planos=[P1],catalogo=DENIED,
                permitir_rede=True,autorizacoes=DIREITOS,
                evidencia_direitos="REVISAO_INTERNA_2026",
            )
        self.assertEqual(len(listar_amostras_ptax(self.db)),0)

    def test_transporte_mock_nao_pode_alegar_direitos(self):
        with self.assertRaises(ErroColetaQuarentenaPTAX):
            self.run_fake(autorizacoes=DIREITOS)
        with self.assertRaises(ErroColetaQuarentenaPTAX):
            self.run_fake(permitir_rede=True)

    def test_caminho_real_com_patch_de_rede_nunca_e_homologacao(self):
        # A chamada HTTPS é SUBSTITUÍDA por patch de teste.
        with patch("nivon.coletor_ptax_quarentena._requisitar_https", http):
            r=executar_coleta_ptax_quarentena(
                self.db,planos=[P1],catalogo=CAT,
                permitir_rede=True,autorizacoes=DIREITOS,
                evidencia_direitos="TESTE_SEM_COLETA_REAL",
                relogio=lambda:T,
            )
        self.assertEqual(r["tipo"],"CAPTURA_HTTPS_NAO_HOMOLOGADA")
        self.assertFalse(r["fonte_http_certificada_independentemente"])
        self.assertFalse(r["aprovado_para_ledger_operacional"])
        self.assertFalse(r["publicavel"])

    def test_limites_e_url_invalida_antes_do_http(self):
        for planos in ([],[P1]*9,[P1,P1],[{**P1,"url":"https://invalid"}]):
            with self.subTest(planos=planos),self.assertRaises(ErroColetaQuarentenaPTAX):
                self.run_fake(planos=planos)

    def test_cli_recusa_source_registry_desligado_antes_de_criar_banco(self):
        from scripts.coletar_ptax_quarentena import main
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            catalogo=folder/"source-registry.json"
            catalogo.write_text(json.dumps(DENIED),encoding="utf-8")
            dbfile=folder/"quarentena.sqlite"
            with self.assertRaises(PermissionError):
                main(["--catalogo",str(catalogo),
                      "--banco",str(dbfile),
                      "--moeda","USD","--inicio","2026-10-20",
                      "--fim","2026-10-20","--permitir-rede",
                      "--evidencia-direitos","DIREITO_PENDENTE"])
            self.assertFalse(dbfile.exists())

    def test_pacote_google_cloud_reconciliado_com_mock(self):
        self.run_fake(planos=[P1])
        evento=listar_amostras_ptax(self.db)[0]["evento_sha256"]
        pacote=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=evento,bucket="nivon-ptax-arquivos",
        )
        gcs=GCS()
        with self.assertRaises(PermissionError):
            reconciliar_gcs_ptax(pacote,cliente=gcs)
        ausente=reconciliar_gcs_ptax(
            pacote,cliente=gcs,permitir_leitura=True,
            referencia_custo="ORCAMENTO_FICTICIO_CI",
        )
        self.assertEqual(ausente["objetos_ausentes"],2)
        enviar_objetos_gcs_ptax(
            pacote,cliente=gcs,permitir_upload=True,
            referencia_direitos="LICENCA_FICTICIA_CI",
            referencia_custo="ORCAMENTO_FICTICIO_CI",
        )
        completo=reconciliar_gcs_ptax(
            pacote,cliente=gcs,permitir_leitura=True,
            referencia_custo="ORCAMENTO_FICTICIO_CI",
        )
        self.assertEqual(completo["objetos_conferidos"],2)
        self.assertTrue(completo["integridade_bytes_gcs_local_confirmada"])
        self.assertFalse(completo["origem_bcb_independente_confirmada"])

    def test_gcs_divergente_e_erro_de_rede_nao_sao_sucesso(self):
        self.run_fake(planos=[P1])
        eid=listar_amostras_ptax(self.db)[0]["evento_sha256"]
        pkg=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=eid,bucket="nivon-ptax-arquivos",
        )
        cloud=GCS()
        enviar_objetos_gcs_ptax(
            pkg,cliente=cloud,permitir_upload=True,
            referencia_direitos="LICENCA_FICTICIA_CI",
            referencia_custo="ORCAMENTO_FICTICIO_CI",
        )
        cloud.files[pkg["objetos"][0]["chave"]]=b"arquivo alterado"
        r=reconciliar_gcs_ptax(
            pkg,cliente=cloud,permitir_leitura=True,
            referencia_custo="ORCAMENTO_FICTICIO_CI",
        )
        self.assertEqual(r["objetos_divergentes"],1)
        self.assertFalse(r["integridade_bytes_gcs_local_confirmada"])
        cloud.erro=True
        with self.assertRaises(ErroExportacaoPTAX):
            reconciliar_gcs_ptax(
                pkg,cliente=cloud,permitir_leitura=True,
                referencia_custo="ORCAMENTO_FICTICIO_CI",
            )

    def test_sincronizacao_gcs_idempotente_com_retomada_parcial(self):
        self.run_fake(planos=[P1])
        eid=listar_amostras_ptax(self.db)[0]["evento_sha256"]
        pkg=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=eid,bucket="nivon-ptax-arquivos",
        )
        cloud=GCS()
        # Simula upload interrompido após o primeiro objeto.
        cloud.files[pkg["objetos"][0]["chave"]]=pkg["objetos"][0]["bytes"]
        opts=dict(
            permitir_upload=True,
            referencia_direitos="LICENCA_FICTICIA_CI",
            referencia_custo="ORCAMENTO_FICTICIO_CI",
            cliente=cloud,
        )
        retorno=sincronizar_pacote_ptax_gcs(pkg,**opts)
        self.assertEqual(retorno["objetos_ja_presentes"],1)
        self.assertEqual(retorno["objetos_novos"],1)
        self.assertTrue(retorno["integridade_bytes_revalidada"])
        self.assertFalse(retorno["publicavel"])
        segunda=sincronizar_pacote_ptax_gcs(pkg,**opts)
        self.assertEqual(segunda["objetos_novos"],0)
        self.assertEqual(segunda["total_conferidos"],2)

    def test_sincronizacao_rejeita_divergencia_sem_sobrescrever(self):
        self.run_fake(planos=[P1])
        eid=listar_amostras_ptax(self.db)[0]["evento_sha256"]
        pkg=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=eid,bucket="nivon-ptax-arquivos",
        )
        cloud=GCS()
        key=pkg["objetos"][0]["chave"]
        cloud.files[key]=b"adulterado"
        with self.assertRaisesRegex(ErroExportacaoPTAX,"divergente"):
            sincronizar_pacote_ptax_gcs(
                pkg,permitir_upload=True,
                referencia_direitos="LICENCA_FICTICIA_CI",
                referencia_custo="ORCAMENTO_FICTICIO_CI",
                cliente=cloud,
            )
        self.assertEqual(cloud.files[key],b"adulterado")
        self.assertEqual(len(cloud.files),1)

    def test_sincronizacao_exige_aprovacoes_sem_acessar_nuvem(self):
        self.run_fake(planos=[P1])
        eid=listar_amostras_ptax(self.db)[0]["evento_sha256"]
        pkg=preparar_objetos_gcs_ptax(
            self.db,evento_sha256=eid,bucket="nivon-ptax-arquivos",
        )
        cloud=GCS()
        with self.assertRaises(PermissionError):
            sincronizar_pacote_ptax_gcs(pkg,cliente=cloud)
        with self.assertRaises(PermissionError):
            sincronizar_pacote_ptax_gcs(
                pkg,cliente=cloud,permitir_upload=True,
                referencia_direitos="LICENCA_FICTICIA_CI",
            )
        self.assertEqual(len(cloud.files),0)


if __name__=="__main__":
    unittest.main()
