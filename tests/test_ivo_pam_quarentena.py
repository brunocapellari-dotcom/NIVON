"""Acervo PAM: content addressing, replay idempotente e falha segura."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from nivon.sidra_pam import planejar_pam_1612
from nivon.ivo_pam_coletor_pontual import coletar_candidato_pam
from nivon.ivo_pam_quarentena import (
    ErroQuarentenaPAM,arquivar_candidato_pam,conferir_recibo_pam
)

UTC=timezone.utc
CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
    "enabled":True,"collection_authorized":True,"training_authorized":False}]}
RIGHTS={"operacoes":frozenset(("COLETA","ARMAZENAMENTO")),
        "evidencia_ref":"LICENCA_FICTICIA_SOMENTE_TESTE"}


def candidato(ano=2021,mes=10,dia=21,valor="170"):
    p=planejar_pam_1612(
        municipio_ibge="5107958",ano=ano,
        codigo_produto_c81="2713",codigo_variavel="214")
    dados=[
      {"D1C":"Município (Código)","D2C":"Variável (Código)",
       "D3C":"Ano (Código)",
       "D4C":"Produto das lavouras temporárias (Código)",
       "V":"Valor","MN":"Unidade de Medida"},
      {"D1C":"5107958","D2C":"214","D3C":str(ano),
       "D4C":"2713","V":valor,"MN":"Toneladas"}
    ]
    raw=json.dumps(dados,ensure_ascii=False).encode()
    instante=datetime(2026,mes,dia,12,tzinfo=UTC)
    return coletar_candidato_pam(catalogo=CAT,direitos=RIGHTS,
        tipo="SIDRA_JSON",plano=p,coletado_em=instante,
        transporte=lambda url,limit,timeout:(raw,"application/json"))


class TestIVOQuarentenaPAM(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"cofre"

    def stage(self,data=None,**kw):
        return arquivar_candidato_pam(
            raiz=self.root,candidato=candidato() if data is None else data,**kw)

    def test_bytes_originais_persistidos_e_conferidos(self):
        source=candidato()
        x=self.stage(source)
        self.assertTrue(x["novo_objeto"])
        self.assertTrue(x["novo_recibo"])
        self.assertEqual((self.root/x["objeto_relativo"]).read_bytes(),
                         source["conteudo_original"])
        verified=conferir_recibo_pam(raiz=self.root,recibo_sha256=x["recibo_sha256"])
        self.assertEqual(verified["sha256"],source["sha256"])
        self.assertFalse(verified["origem_publicacao_autenticada"])
        self.assertFalse(verified["modelo_treinavel"])
        self.assertFalse(x["ledger_canonico_atualizado"])

    def test_mesma_captura_idempotente(self):
        a=self.stage()
        b=self.stage()
        self.assertEqual(a["sha256"],b["sha256"])
        self.assertEqual(a["recibo_sha256"],b["recibo_sha256"])
        self.assertFalse(b["novo_objeto"])
        self.assertFalse(b["novo_recibo"])

    def test_segunda_captura_mesmos_bytes_cria_outro_recibo(self):
        first=self.stage()
        second=self.stage(candidato(dia=22))
        self.assertEqual(first["sha256"],second["sha256"])
        self.assertNotEqual(first["recibo_sha256"],second["recibo_sha256"])
        self.assertFalse(second["novo_objeto"])
        self.assertTrue(second["novo_recibo"])
        self.assertTrue(conferir_recibo_pam(
            raiz=self.root,recibo_sha256=second["recibo_sha256"]))

    def test_adulteracao_de_bytes_detectada(self):
        r=self.stage()
        target=self.root/r["objeto_relativo"]
        target.write_bytes(b"conteudo trocado")
        with self.assertRaises(ErroQuarentenaPAM):
            conferir_recibo_pam(raiz=self.root,recibo_sha256=r["recibo_sha256"])
        with self.assertRaises(ErroQuarentenaPAM):
            self.stage()

    def test_adulteracao_de_recibo_detectada(self):
        r=self.stage()
        target=self.root/r["recibo_relativo"]
        target.write_text('{"liberado_para_treino":true}')
        with self.assertRaises(ErroQuarentenaPAM):
            conferir_recibo_pam(raiz=self.root,recibo_sha256=r["recibo_sha256"])

    def test_meta_sem_recebimento_nunca_autoriza_treino(self):
        r=self.stage()
        payload=json.loads((self.root/r["recibo_relativo"]).read_bytes())
        self.assertFalse(payload["fonte_autenticada_externamente"])
        self.assertFalse(payload["direitos_validados_externamente"])
        self.assertFalse(payload["liberado_para_treino"])
        self.assertFalse(payload["inscrito_no_ledger_canonico"])

    def test_candidato_com_hash_adulterado_rejeitado(self):
        a=candidato()
        a["sha256"]="a"*64
        with self.assertRaises(ErroQuarentenaPAM):
            self.stage(a)

    def test_candidato_com_flag_homologacao_falsa_nao_entra(self):
        for flag in ("treinamento_autorizado","publicacao_oficial_verificada",
                     "autenticidade_documental_verificada",
                     "gravado_em_snapshot_ledger"):
            a=candidato()
            a[flag]=True
            with self.subTest(flag=flag),self.assertRaises(ErroQuarentenaPAM):
                self.stage(a)

    def test_quota_local_rejeita_candidato_que_excede_limite(self):
        a=candidato()
        with self.assertRaises(ErroQuarentenaPAM):
            self.stage(a,limite_total_bytes=1024)
        self.assertFalse((self.root/"objetos_sha256"/(a["sha256"]+".bin")).exists())

    def test_quota_nao_reconta_objeto_ja_arquivado(self):
        a=candidato()
        r=self.stage(a)
        b=self.stage(a,limite_total_bytes=1024)
        self.assertEqual(r["sha256"],b["sha256"])
        self.assertFalse(b["novo_objeto"])

    def test_nao_aceita_raiz_simbolica(self):
        outra=Path(self.tmp.name)/"externo"
        outra.mkdir()
        self.root.symlink_to(outra,target_is_directory=True)
        with self.assertRaises(ErroQuarentenaPAM):
            self.stage()

    def test_nao_aceita_link_para_objeto(self):
        self.root.mkdir()
        objects=self.root/"objetos_sha256"
        objects.mkdir()
        a=candidato()
        externo=Path(self.tmp.name)/"externo.bin"
        externo.write_bytes(a["conteudo_original"])
        (objects/(a["sha256"]+".bin")).symlink_to(externo)
        with self.assertRaises(ErroQuarentenaPAM):
            self.stage(a)

    def test_recibo_desconhecido_ou_nome_de_path_invalidos(self):
        self.stage()
        for bad in ("../etc/passwd","z"*64,"a"*63):
            with self.subTest(bad=bad),self.assertRaises(ErroQuarentenaPAM):
                conferir_recibo_pam(raiz=self.root,recibo_sha256=bad)

    def test_transporte_injetado_continua_dado_sintetico(self):
        x=self.stage()
        self.assertFalse(x["captura_remota_comprovada"])
        self.assertFalse(x["publicacao_oficial_comprovada"])
        self.assertFalse(x["treinamento_real_autorizado"])


if __name__=="__main__":
    unittest.main()
