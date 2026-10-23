"""Teste de contrato com bucket GCS simulado — nenhuma rede/cobrança.

Verifica que o adapter usará upload condicional if_generation_match=0 e
read-back da mesma geração. NÃO prova permissão, custo, IAM ou WORM reais.
"""
import unittest
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from nivon.fretes_recibos_ancora import criar_recibo_local_frete
from nivon.fretes_recibos_gcs import (
    ErroReciboGCS, gravar_recibo_gcs_condicional,
    conferir_recibo_gcs_generation,
)

KEY=b"fixture-gcs-receipt-verification-key-20261023"
NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)


class BucketFalso:
    name="bucket-fixture-privado"

    def __init__(self):
        self.live={}
        self.generations={}
        self.uploads=[]
        self.reads=[]
        self.forcar_divergencia=False

    def blob(self,nome,generation=None):
        return BlobFalso(self,nome,generation)


class BlobFalso:
    def __init__(self, bucket, nome, generation):
        self.bucket=bucket
        self.name=nome
        self.generation=generation

    def upload_from_string(self, data, *, content_type, if_generation_match, timeout):
        self.bucket.uploads.append({
            "name":self.name,"content_type":content_type,
            "if_generation_match":if_generation_match,"timeout":timeout,
        })
        if if_generation_match!=0 or self.name in self.bucket.live:
            raise RuntimeError("GCS PreconditionFailed 412")
        gen=len(self.bucket.generations)+1
        self.generation=gen
        self.bucket.generations[(self.name,gen)]=data
        self.bucket.live[self.name]=gen

    def download_as_bytes(self, *, if_generation_match, timeout):
        self.bucket.reads.append({
            "name":self.name,"generation":self.generation,
            "if_generation_match":if_generation_match,"timeout":timeout,
        })
        if self.generation!=if_generation_match:
            raise RuntimeError("generation read mismatch")
        v=self.bucket.generations[(self.name,if_generation_match)]
        return v+b"ADULTERADO" if self.bucket.forcar_divergencia else v


def recibo():
    return criar_recibo_local_frete(
        tipo_ledger="PREVISOES",emissor_id="assinador-fixture",
        cabeca_sha256="a"*64,sequencia=17,
        assinado_em=NOW,chave_recibo=KEY,
    )


def escrever(bucket, r=None, **overrides):
    return gravar_recibo_gcs_condicional(
        bucket,r if r is not None else recibo(),
        chave_recibo=KEY,emissor_esperado="assinador-fixture",
        as_of=NOW+timedelta(minutes=1),
        autorizar_escrita=True,**overrides,
    )


class TestAdaptadorCloudStorage(unittest.TestCase):
    def test_desligado_por_padrao_sem_chamar_bucket(self):
        b=BucketFalso()
        x=gravar_recibo_gcs_condicional(
            b,recibo(),chave_recibo=KEY,
            emissor_esperado="assinador-fixture",as_of=NOW
        )
        self.assertEqual(x["status"],"GCS_DESABILITADO_POR_PADRAO")
        self.assertFalse(b.uploads)
        self.assertFalse(b.reads)

    def test_upload_condicional_readback_e_generacao(self):
        b=BucketFalso()
        r=escrever(b)
        self.assertEqual(r["status"],"GCS_UPLOAD_CONDICIONAL_READBACK_VERIFICADO")
        self.assertEqual(r["generation"],1)
        self.assertEqual(b.uploads[0]["if_generation_match"],0)
        self.assertEqual(b.reads[0]["if_generation_match"],1)
        self.assertEqual(b.uploads[0]["content_type"],"application/json")
        self.assertFalse(r["retencao_worm_comprovada"])
        self.assertFalse(r["timestamp_independente_comprovado"])
        self.assertFalse(r["publicavel"])
        v=conferir_recibo_gcs_generation(
            b,nome_objeto=r["nome_objeto"],generation=r["generation"],
            sha256_esperado=r["sha256_bytes"],
        )
        self.assertEqual(v["status"],"OBJETO_GCS_GENERATION_E_SHA_VALIDOS")
        self.assertFalse(v["assinatura_mac_conferida"])

    def test_mesmo_recibo_reenviado_nao_sobrescreve(self):
        b=BucketFalso()
        r=recibo()
        a=escrever(b,r)
        with self.assertRaisesRegex(ErroReciboGCS,"falha de escrita"):
            escrever(b,r)
        self.assertEqual(b.live[a["nome_objeto"]],1)
        self.assertEqual(len(b.generations),1)

    def test_recibo_com_hmac_alterado_nao_tenta_upload(self):
        b=BucketFalso()
        r=recibo()
        r["sequencia"]=18
        with self.assertRaisesRegex(ValueError,"MAC inválido"):
            escrever(b,r)
        self.assertEqual(len(b.uploads),0)

    def test_readback_alterado_falha_fechado(self):
        b=BucketFalso()
        b.forcar_divergencia=True
        with self.assertRaisesRegex(ErroReciboGCS,"read-back remoto"):
            escrever(b)
        self.assertEqual(len(b.uploads),1)

    def test_confere_sha_lido_apos_commit(self):
        b=BucketFalso()
        a=escrever(b)
        with self.assertRaisesRegex(ErroReciboGCS,"divergente"):
            conferir_recibo_gcs_generation(
                b,nome_objeto=a["nome_objeto"],generation=a["generation"],
                sha256_esperado="0"*64,
            )

    def test_geracao_inesperada_nao_pode_ser_lida_como_original(self):
        b=BucketFalso()
        a=escrever(b)
        with self.assertRaisesRegex(ErroReciboGCS,"recuperado"):
            conferir_recibo_gcs_generation(
                b,nome_objeto=a["nome_objeto"],generation=999,
                sha256_esperado=a["sha256_bytes"],
            )

    def test_sem_bucket_autorizado_nao_tenta_carga(self):
        with self.assertRaisesRegex(ErroReciboGCS,"bucket"):
            escrever(None)

    def test_nome_objeto_nao_aceita_path_traversal(self):
        b=BucketFalso()
        r=recibo()
        r["tipo_ledger"]="../secrets"
        with self.assertRaises(ErroReciboGCS):
            escrever(b,r)
        self.assertFalse(b.uploads)

    def test_tipo_de_arquivo_cloud_apenas_hash_sem_raw(self):
        b=BucketFalso()
        r=escrever(b)
        encoded=b.generations[(r["nome_objeto"],r["generation"])]
        self.assertNotIn(b"raw_bytes",encoded)
        self.assertNotIn(b"transportadora_id",encoded)
        self.assertNotIn(b"chave_previsao",encoded)


if __name__=="__main__":
    unittest.main()
