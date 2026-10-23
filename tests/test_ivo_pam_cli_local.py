"""E2E de arquivos locais: manifesto SHA -> leitura segura -> quarentena -> fila.

Nenhuma rede e nenhuma alegacao de validade dos arquivos de teste.
"""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from nivon.ivo_pam_cli_local import (
    ErroImportacaoLocalPAM, executar_importacao_local_pam, main,
)


def raw(municipio="5107958", ano=2021, categoria="2713", valor="170"):
    return json.dumps([
        {"D1C": "Município (Código)", "D2C": "Variável (Código)",
         "D3C": "Ano (Código)",
         "D4C": "Produto das lavouras temporárias (Código)",
         "V": "Valor", "MN": "Unidade de Medida"},
        {"D1C": municipio, "D2C": "214", "D3C": str(ano),
         "D4C": categoria, "V": valor, "MN": "Toneladas"},
    ], ensure_ascii=False).encode()


class TestImportacaoLocalPAM(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / "dados"
        self.origin.mkdir()
        self.output = base / "saida"
        payload = raw()
        (self.origin / "pam_soja.json").write_bytes(payload)
        self.cfg = {
            "schema": "nivon_ivo_pam_importacao_local_v1",
            "somente_quarentena": True, "publicacao_proibida": True,
            "capturado_em_declarado": "2026-10-21T15:00:00+00:00",
            "referencia_direitos_declarada": "TERMO_DE_TESTE_FICTICIO",
            "itens": [{
                "municipio_ibge": "5107958", "ano": 2021,
                "categoria_c81": "2713", "variavel": "214",
                "arquivo": "pam_soja.json",
                "arquivo_sha256": hashlib.sha256(payload).hexdigest(),
            }],
        }

    def stage(self):
        return executar_importacao_local_pam(
            config=self.cfg, origem=self.origin, destino=self.output,
        )

    def test_arquivo_local_fica_no_cofre_e_nao_no_canonico(self):
        result = self.stage()
        self.assertEqual(result["recebidos"], 1)
        self.assertEqual(result["auditados"], 1)
        self.assertEqual(result["promocoes"], 0)
        self.assertFalse(result["rede_executada"])
        self.assertFalse(result["dados_reais_homologados"])
        self.assertTrue(result["direitos_declarados_nao_comprovados"])
        manifests = list(self.output.glob("manifesto_*.json"))
        filas = list(self.output.glob("fila_*.json"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(len(filas), 1)
        fila = json.loads(filas[0].read_text())
        self.assertEqual(fila["quantidade_pendente"], 1)
        self.assertFalse(fila["registro_canonico_autorizado"])
        self.assertEqual(len(list((self.output / "quarentena" /
                                   "objetos_sha256").iterdir())), 1)
        self.assertFalse((self.output / "registro_snapshots.sqlite").exists())

    def test_replay_mesmos_arquivos_nao_sobrescreve(self):
        first = self.stage()
        second = self.stage()
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.output.glob("manifesto_*.json"))), 1)
        self.assertEqual(len(list(self.output.glob("fila_*.json"))), 1)

    def test_multiplos_arquivos_geram_fila_revisao(self):
        body = raw("3503109", 2020, "2714", "38")
        (self.origin / "pam_sorgo.json").write_bytes(body)
        self.cfg["itens"].append({
            "municipio_ibge": "3503109", "ano": 2020,
            "categoria_c81": "2714", "variavel": "214",
            "arquivo": "pam_sorgo.json",
            "arquivo_sha256": hashlib.sha256(body).hexdigest(),
        })
        result = self.stage()
        self.assertEqual(result["auditados"], 2)
        path = next(self.output.glob("fila_*.json"))
        self.assertEqual(json.loads(path.read_text())["quantidade_pendente"], 2)

    def test_sha_errado_rejeita_antes_de_criar_quarentena(self):
        self.cfg["itens"][0]["arquivo_sha256"] = "0" * 64
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_caminho_fora_da_origem_rejeitado(self):
        for caminho in ("../secreto.txt", "/etc/passwd", "diretorio\\arquivo.json"):
            with self.subTest(path=caminho):
                self.cfg["itens"][0]["arquivo"] = caminho
                with self.assertRaises(ErroImportacaoLocalPAM):
                    self.stage()
                self.assertFalse(self.output.exists())

    def test_symlink_de_origem_rejeitado(self):
        link = self.origin / "link.json"
        link.symlink_to(self.origin / "pam_soja.json")
        self.cfg["itens"][0]["arquivo"] = "link.json"
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_dados_nao_homologados_nunca_ativam_publicacao(self):
        self.cfg["publicacao_proibida"] = False
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_direito_ausente_e_arquivo_extra_bloqueados(self):
        self.cfg["referencia_direitos_declarada"] = ""
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()
        self.assertFalse(self.output.exists())
        self.cfg["referencia_direitos_declarada"] = "TERMO_TESTE_V1"
        self.cfg["itens"][0]["secret_extra"] = "NÃO"
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()

    def test_importador_pdf_opcional_preserva_estado_pendente(self):
        pdf = b"%PDF-1.4\n" + b"A" * 100
        (self.origin / "anexo.pdf").write_bytes(pdf)
        self.cfg["itens"][0].update({
            "pdf_url": "https://biblioteca.ibge.gov.br/pam/nota.pdf",
            "pdf_arquivo": "anexo.pdf",
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "publicacao_declarada": "2026-09-17",
        })
        result = self.stage()
        self.assertEqual(result["auditados"], 1)
        self.assertEqual(len(list((self.output / "quarentena" /
                                   "objetos_sha256").iterdir())), 2)

    def test_arquivo_de_saida_adulterado_nao_e_sobrescrito(self):
        self.stage()
        path = next(self.output.glob("manifesto_*.json"))
        path.write_text("alterado", encoding="utf-8")
        with self.assertRaises(ErroImportacaoLocalPAM):
            self.stage()

    def test_cli_main_realiza_fluxo_local_sem_rede(self):
        manifest = self.origin / "manifesto.json"
        manifest.write_text(json.dumps(self.cfg, ensure_ascii=False))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([
                "--manifesto", str(manifest), "--destino", str(self.output)
            ]), 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["resultado_gravado"])
        self.assertFalse(result["rede_executada"])
        self.assertEqual(result["promocoes"], 0)


if __name__ == "__main__":
    unittest.main()
