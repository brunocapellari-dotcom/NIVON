"""Ciclo E2E PAM: novo banco -> backup -> restauração -> revisão -> backup.

Integra SQLite real + quarentena + normalizador SIDRA + CLI + auditoria
sem HTTP externo nos testes. Testes não homologam dados de produção.
"""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime,timezone

from nivon.ivo_pam_operacao import abrir_operacao_pam, consultar_pam_operacional
from nivon.ivo_pam_backup import (
    ErroBackupPAM, criar_backup_pam, restaurar_backup_pam)
from nivon.ivo_pam_ciclo import executar_ciclo_pam, main
from nivon.ivo_pam_qualidade import auditar_operacao_pam


def sidra(valor,ano=2021):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":"5107958","D2C":"214","D3C":str(ano),
         "D4C":"2713","V":str(valor),"MN":"Toneladas"}],
        ensure_ascii=False).encode()


class TestIVOPAMCicloUnificadoE2E(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.arquivos=self.root/"inputs"
        self.arquivos.mkdir()
        self.tarefa={"municipio_ibge":"5107958","ano":2021,
                     "variavel":"214","categoria_c81":"2713","arquivo":"pam.json"}
        self.arquivo=self.arquivos/"pam.json"
        self.arquivo.write_bytes(sidra(100))

    def ciclo(self,n,**kw):
        cfg=dict(saida=self.root/f"ciclo{n}",tarefas=[self.tarefa],
                 entrada=self.arquivos,modo="LOCAL")
        cfg.update(kw)
        return executar_ciclo_pam(**cfg)

    def test_duas_coletas_persistem_e_revisao_real_do_mesmo_banco(self):
        a=self.ciclo(1,iniciar_novo=True)
        self.assertEqual(a["backup"]["capturas"],1)
        self.assertEqual(a["backup"]["vintages"],1)
        self.assertTrue((self.root/"ciclo1"/"estado_pam.zip").is_file())
        self.arquivo.write_bytes(sidra(150))
        b=self.ciclo(2,arquivo_anterior=self.root/"ciclo1"/"estado_pam.zip")
        self.assertEqual(b["estado_anterior"]["capturas"],1)
        self.assertEqual(b["backup"]["capturas"],2)
        self.assertEqual(b["backup"]["vintages"],2)
        self.assertEqual(b["coleta"]["mudancas"][0]["alteracao"],"VALOR_ALTERADO")
        d=abrir_operacao_pam(self.root/"ciclo2"/"estado"/"operacional.sqlite")
        try:
            q=consultar_pam_operacional(d,municipio_ibge="5107958",
                ano=2021,variavel="214",produto="2713")
            self.assertEqual([v["valor"] for v in q["historico"]],[100.,150.])
        finally:d.close()
        self.assertFalse(b["treinamento_real_habilitado"])

    def test_recoleta_sem_mudanca_mantem_vintage_e_adiciona_captura(self):
        self.ciclo(1,iniciar_novo=True)
        next=self.ciclo(2,arquivo_anterior=self.root/"ciclo1"/"estado_pam.zip")
        self.assertEqual(next["backup"]["vintages"],1)
        self.assertEqual(next["backup"]["capturas"],2)
        self.assertEqual(next["coleta"]["mudancas"][0]["alteracao"],"SEM_ALTERACAO")

    def test_restaura_terceiro_ciclo_com_todas_as_vintages(self):
        self.ciclo(1,iniciar_novo=True)
        self.arquivo.write_bytes(sidra(150))
        self.ciclo(2,arquivo_anterior=self.root/"ciclo1"/"estado_pam.zip")
        self.arquivo.write_bytes(sidra(150))
        next=self.ciclo(3,arquivo_anterior=self.root/"ciclo2"/"estado_pam.zip")
        self.assertEqual(next["backup"]["vintages"],2)
        self.assertEqual(next["backup"]["capturas"],3)
        self.assertTrue(next["integridade"]["integridade_local_aprovada"])

    def test_restauracao_em_diretorio_existente_nao_apaga_dados(self):
        self.ciclo(1,iniciar_novo=True)
        existing=self.root/"dados"
        existing.mkdir()
        (existing/"marcador.txt").write_text("preservar")
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(
                arquivo_zip=self.root/"ciclo1"/"estado_pam.zip",destino=existing)
        self.assertEqual((existing/"marcador.txt").read_text(),"preservar")

    def test_zip_com_objeto_corrompido_rejeitado_antes_de_publicar(self):
        self.ciclo(1,iniciar_novo=True)
        p=self.root/"ciclo1"/"estado_pam.zip"
        bad=self.root/"corrompido.zip"
        with zipfile.ZipFile(p) as z,zipfile.ZipFile(bad,"w") as out:
            for n in z.namelist():
                dados=z.read(n)
                if n.startswith("objetos_sha256/"):
                    dados=b"ataque de adulteracao"
                out.writestr(n,dados)
        dest=self.root/"nao-publicado"
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=bad,destino=dest)
        self.assertFalse(dest.exists())

    def test_zip_escapando_diretorio_rejeitado(self):
        malicious=self.root/"zip-slip.zip"
        with zipfile.ZipFile(malicious,"w") as z:
            z.writestr("pam.sqlite",b"sqlite!")
            z.writestr("../fora.txt",b"hack")
        with self.assertRaises(ErroBackupPAM):
            restaurar_backup_pam(arquivo_zip=malicious,destino=self.root/"restaurado")
        self.assertFalse((self.root/"fora.txt").exists())

    def test_migracao_legada_rejeitada_ate_converter_e_auditar(self):
        self.ciclo(1,iniciar_novo=True)
        with self.assertRaises(ErroBackupPAM):
            self.ciclo(2,arquivo_anterior=self.root/"ciclo1"/"estado_pam.zip",
                       permitir_legado=True)
        self.assertFalse((self.root/"ciclo2").exists())

    def test_falha_de_tarefa_nao_sobrescreve_backup_anterior(self):
        a=self.ciclo(1,iniciar_novo=True)
        arquivo_zip=self.root/"ciclo1"/"estado_pam.zip"
        sha=a["backup"]["sha256_arquivo"]
        self.arquivo.write_bytes(b"nao-json")
        with self.assertRaises(ErroBackupPAM):
            self.ciclo(2,arquivo_anterior=arquivo)
        import hashlib
        self.assertEqual(hashlib.sha256(arquivo.read_bytes()).hexdigest(),sha)
        self.assertFalse((self.root/"ciclo2"/"estado_pam.zip").exists())

    def test_nao_recomeca_historico_silenciosamente_sem_backup(self):
        with self.assertRaises(ErroBackupPAM):
            self.ciclo(1)
        self.assertFalse((self.root/"ciclo1").exists())

    def test_restauracao_atesta_integridade_antes_de_uso(self):
        self.ciclo(1,iniciar_novo=True)
        restaurar_backup_pam(
            arquivo_zip=self.root/"ciclo1"/"estado_pam.zip",
            destino=self.root/"test-recovery")
        db=abrir_operacao_pam(self.root/"test-recovery"/"operacional.sqlite")
        try:
            aud=auditar_operacao_pam(db=db,raiz=self.root/"test-recovery")
            self.assertTrue(aud["integridade_local_aprovada"])
            self.assertEqual(aud["vintages_verificadas"],1)
        finally:db.close()


if __name__=="__main__":
    unittest.main()
