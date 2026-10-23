"""E2E GCS simulado: duas capturas PAM -> backup -> GCS CAS -> recuperação.

Google Storage API é simulada localmente, sem credenciais, rede, IAM,
bucket real ou cobrança. SQLite/quarentena/ZIP/restauração são verdadeiros.
"""
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from nivon.ivo_pam_operacao import (
    abrir_operacao_pam, executar_lote_pam)
from nivon.ivo_pam_backup import criar_backup_pam, restaurar_backup_pam
from nivon.ivo_pam_storage_gcs import (
    ClienteGCS, ErroGCSState, _HTTPStatus,
    publicar_backup_gcs, baixar_backup_gcs)


class StorageFalso:
    def __init__(self):
        self.obj={}
        self.generation=100
        self.mudar_no_cas=False
        self.corromper_readback=False
        self.pedidos=[]
    def __call__(self,method,url,headers,body):
        self.pedidos.append((method,url))
        assert headers["Authorization"]=="Bearer TOKEN_SO_TESTE"
        p=urllib.parse.urlsplit(url)
        assert p.scheme=="https" and p.hostname=="storage.googleapis.com"
        qs=urllib.parse.parse_qs(p.query)
        if p.path.startswith("/upload/storage/v1/b/"):
            assert method=="POST"
            name=qs["name"][0]
            assert qs.get("uploadType")==["media"]
            pre=int(qs["ifGenerationMatch"][0])
            existing=self.obj.get(name)
            if self.mudar_no_cas and name.endswith("/controle/ultimo.json"):
                self.generation+=1
                self.obj[name]=(b"{}",""+str(self.generation))
                self.mudar_no_cas=False
                raise _HTTPStatus(412)
            if (pre==0 and existing is not None) or (
                 pre!=0 and (existing is None or int(existing[1])!=pre)):
                raise _HTTPStatus(412)
            self.generation+=1
            self.obj[name]=(body,str(self.generation))
            return json.dumps({"name":name,"generation":str(self.generation)}).encode()
        start="/storage/v1/b/test-bucket/o/"
        assert p.path.startswith(start) and method=="GET"
        name=urllib.parse.unquote(p.path[len(start):])
        if name not in self.obj:
            raise _HTTPStatus(404)
        raw,gen=self.obj[name]
        if qs.get("alt")==["media"]:
            if "generation" in qs and qs["generation"]!=[gen]:
                raise _HTTPStatus(404)
            if self.corromper_readback and name.endswith(".zip"):
                return raw+b"alterado"
            return raw
        return json.dumps({"name":name,"generation":gen,"size":str(len(raw))}).encode()


def fixture(valor):
    return json.dumps([
      {"D1C":"Município (Código)","D2C":"Variável (Código)",
       "D3C":"Ano (Código)",
       "D4C":"Produto das lavouras temporárias (Código)",
       "V":"Valor","MN":"Unidade de Medida"},
      {"D1C":"5107958","D2C":"214","D3C":"2021",
       "D4C":"2713","V":str(valor),"MN":"Toneladas"}],
      ensure_ascii=False).encode()


class TestIVOSyncGCS(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.mock=StorageFalso()
        self.cloud=ClienteGCS(bucket="test-bucket",token="TOKEN_SO_TESTE",
                              transporte=self.mock)
        self.tarefa=[{"municipio_ibge":"5107958","ano":2021,
                      "variavel":"214","categoria_c81":"2713",
                      "arquivo":"pam.json"}]
        self.inp=self.root/"entrada"
        self.inp.mkdir()

    def estado(self,valor,numero,backup_anterior=None):
        root=self.root/f"estado{numero}"
        root.mkdir()
        if backup_anterior is not None:
            restaurar_backup_pam(arquivo=backup_anterior,destino=root/"recuperado")
            data=root/"recuperado"
        else:
            data=root/"novo"
            data.mkdir()
        self.inp.joinpath("pam.json").write_bytes(fixture(valor))
        db=abrir_operacao_pam(data/"pam.sqlite")
        try:
            r=executar_lote_pam(db=db,raiz=data/"cofre",tarefas=self.tarefa,
                modo="LOCAL",entrada=self.inp)
            self.assertEqual(r["aprovados"],1)
            arq=root/"backup.zip"
            criar_backup_pam(db=db,raiz=data/"cofre",saida=arq)
        finally:
            db.close()
        return arq

    def test_bootstrap_e_incremento_preservam_vintages_e_capturas(self):
        antigo=self.estado("100",1)
        first=publicar_backup_gcs(cliente=self.cloud,arquivo=antigo,
                                  permitir_bootstrap=True)
        self.assertTrue(first["cloud_verified"])
        self.assertEqual(first["capturas"],1)
        rec=self.root/"recuperado.zip"
        got=baixar_backup_gcs(cliente=self.cloud,saida=rec)
        self.assertEqual(got["sha256"],first["sha256"])
        novo=self.estado("150",2,backup_anterior=rec)
        second=publicar_backup_gcs(cliente=self.cloud,arquivo=novo)
        self.assertEqual(second["capturas"],2)
        self.assertEqual(second["vintages"],2)
        self.assertNotEqual(second["sha256"],first["sha256"])
        target=self.root/"recuperado2.zip"
        done=baixar_backup_gcs(cliente=self.cloud,saida=target)
        self.assertEqual(done["capturas"],2)
        self.assertEqual(done["vintages"],2)
        self.assertTrue(target.is_file())

    def test_nao_cria_ponteiro_ou_bucket_sem_bootstrap(self):
        backup=self.estado("100",1)
        with self.assertRaises(ErroGCSState):
            publicar_backup_gcs(cliente=self.cloud,arquivo=backup)
        self.assertFalse(self.mock.obj)

    def test_repetir_backup_antigo_nao_apaga_avanco(self):
        backup=self.estado("100",1)
        publicar_backup_gcs(cliente=self.cloud,arquivo=backup,permitir_bootstrap=True)
        with self.assertRaises(ErroGCSState):
            publicar_backup_gcs(cliente=self.cloud,arquivo=backup)
        self.assertEqual(self.cloud.ponteiro()[0]["capturas"],1)

    def test_outro_processo_muda_ponteiro_e_cas_falha(self):
        antigo=self.estado("100",1)
        publicar_backup_gcs(cliente=self.cloud,arquivo=antigo,permitir_bootstrap=True)
        novo=self.estado("150",2,backup_anterior=antigo)
        self.mock.mudar_no_cas=True
        with self.assertRaises(ErroGCSState):
            publicar_backup_gcs(cliente=self.cloud,arquivo=novo)
        # A simulação faz outro processo alterar a geração e deixar
        # ponteiro inválido; o cliente deve rejeitá-lo em vez de fingir
        # que o próprio upload foi publicado.
        with self.assertRaises(ErroGCSState):
            self.cloud.ponteiro()

    def test_readback_corrompido_nao_avanca_latest(self):
        b=self.estado("100",1)
        self.mock.corromper_readback=True
        with self.assertRaises(ErroGCSState):
            publicar_backup_gcs(cliente=self.cloud,arquivo=b,permitir_bootstrap=True)
        self.assertIsNone(self.cloud.ponteiro()[0])

    def test_backup_remoto_alterado_bloqueia_recuperacao(self):
        b=self.estado("100",1)
        info=publicar_backup_gcs(cliente=self.cloud,arquivo=b,permitir_bootstrap=True)
        self.mock.corromper_readback=True
        out=self.root/"nao_criar.zip"
        with self.assertRaises(ErroGCSState):
            baixar_backup_gcs(cliente=self.cloud,saida=out)
        self.assertFalse(out.exists())

    def test_resto_antigo_inalterado_se_arquivo_destino_existe(self):
        b=self.estado("100",1)
        publicar_backup_gcs(cliente=self.cloud,arquivo=b,permitir_bootstrap=True)
        out=self.root/"nao_sobrescrever.zip"
        out.write_bytes(b"backup preexistente")
        with self.assertRaises(ErroGCSState):
            baixar_backup_gcs(cliente=self.cloud,saida=out)
        self.assertEqual(out.read_bytes(),b"backup preexistente")

    def test_bucket_token_nome_objeto_invalidos(self):
        for kw in ({"bucket":"..","token":"TOKEN_SO_TESTE"},
                   {"bucket":"https://evil.test","token":"TOKEN_SO_TESTE"},
                   {"bucket":"test-bucket","token":""}):
            with self.subTest(kw=kw),self.assertRaises(ErroGCSState):
                ClienteGCS(**kw)
        with self.assertRaises(ErroGCSState):
            self.cloud.download("../../outro-objeto")

    def test_nao_existe_estado_pra_restaurar(self):
        with self.assertRaises(ErroGCSState):
            baixar_backup_gcs(cliente=self.cloud,saida=self.root/"vazio.zip")


if __name__=="__main__":
    unittest.main()
