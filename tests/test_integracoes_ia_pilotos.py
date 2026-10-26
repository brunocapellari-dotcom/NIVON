"""Sem rede: garante política, privacidade e execução operacional auditável."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon.integracoes_ia.core import ErroIntegracao, PoliticaIntegracao, hash_texto
from nivon.integracoes_ia.pilotos import executar, main

APROVADA = PoliticaIntegracao(True, True, ("conab.gov.br", "memo.example.org", "paper.example.org"))


class TestPilotosNivon(unittest.TestCase):
    def test_diagnostico_e_grafo_sao_reais_sem_rede(self):
        d = executar("diagnostico")
        self.assertEqual(d["execucao"], "EXECUCAO_LOCAL_REAL")
        self.assertGreaterEqual(d["resultado_sanitizado"]["capacidades_catalogadas"], 9)
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)
            (path / "mod.py").write_text("import nivon.portal_interno\n")
            g = executar("grafo", raiz=t)
        self.assertEqual(g["resultado_sanitizado"]["arquivos_inspecionados"], 1)
        self.assertEqual(g["resultado_sanitizado"]["arestas"], 1)
        self.assertFalse(g["validado_em_producao"])

    def test_bloqueia_todos_externos_por_padrao(self):
        for capacidade in ("firecrawl", "pageindex", "paperclip", "hindsight"):
            with self.subTest(capacidade=capacidade), self.assertRaisesRegex(ErroIntegracao, "REDE_EXTERNA_NAO_AUTORIZADA"):
                executar(capacidade)

    def test_firecrawl_real_mockado_publica_apenas_hash(self):
        fake = {"texto": "Nao registrar conteudo sensivel",
                "evidencia": {"publicavel": False, "validado": False, "sha256": hash_texto("Nao registrar conteudo sensivel"),
                              "natureza": "EXTRAIDO_NAO_VALIDADO"}}
        with patch("nivon.integracoes_ia.pilotos.provedores.consultar_firecrawl", return_value=fake) as func:
            resp = executar("firecrawl", origem="https://conab.gov.br/rel", politica=APROVADA)
        func.assert_called_once()
        self.assertEqual(resp["execucao"], "PILOTO_EXTERNO_REAL")
        self.assertFalse(resp["publicavel"])
        self.assertNotIn("Nao registrar", json.dumps(resp))
        self.assertEqual(resp["resultado_sanitizado"]["sha256_texto"], fake["evidencia"]["sha256"])

    def test_paperclip_sem_vazar_tarefas_e_titulos(self):
        dados = {"tarefas_externas": [{"id": "privado", "titulo": "secreto"}], "canonica": False}
        with patch("nivon.integracoes_ia.pilotos.provedores.listar_paperclip", return_value=dados):
            out = executar("paperclip", politica=APROVADA)
        self.assertEqual(out["resultado_sanitizado"]["tarefas_lidas"], 1)
        self.assertNotIn("secreto", json.dumps(out))
        self.assertNotIn("privado", json.dumps(out))

    def test_hindsight_sem_vazar_memorias(self):
        with patch("nivon.integracoes_ia.pilotos.provedores.consultar_hindsight",
                   return_value={"memorias": [{"texto": "secreto"}], "publicavel": False, "natureza": "MEMORIA_NAO_VALIDADA"}):
            out = executar("hindsight", pergunta="O que mudou?", politica=APROVADA)
        self.assertEqual(out["resultado_sanitizado"]["memorias_encontradas"], 1)
        self.assertNotIn("secreto", json.dumps(out))

    def test_pageindex_rejeita_documento_externo(self):
        with tempfile.TemporaryDirectory() as t:
            doc = Path(t) / "relatorio.pdf"
            doc.write_bytes(b"%PDF-1.4")
            with self.assertRaisesRegex(ErroIntegracao, "DOCUMENTO_FORA_DO_DIRETORIO_APROVADO"):
                executar("pageindex", arquivo=str(doc), pergunta="Resumo?", politica=APROVADA)

    def test_pageindex_permite_somente_docs_e_sem_texto_resposta(self):
        with tempfile.TemporaryDirectory(dir="docs") as t:
            doc = Path(t) / "relatorio.pdf"
            doc.write_bytes(b"%PDF-1.4 teste")
            fake = {"documento_sha256": "b" * 64, "resposta": "conclusao confidencial",
                    "natureza": "INFERIDO", "publicavel": False}
            with patch("nivon.integracoes_ia.pilotos.provedores.consultar_pageindex", return_value=fake):
                out = executar("pageindex", arquivo=str(doc), pergunta="Qual a conclusao?", politica=APROVADA)
        self.assertNotIn("conclusao confidencial", json.dumps(out))
        self.assertEqual(out["resultado_sanitizado"]["sha256_documento"], "b" * 64)

    def test_rejeita_resultado_inseguro(self):
        fake = {"texto": "qualquer", "evidencia": {"publicavel": True, "validado": False, "sha256": "a"*64}}
        with patch("nivon.integracoes_ia.pilotos.provedores.consultar_firecrawl", return_value=fake):
            with self.assertRaisesRegex(ErroIntegracao, "FIRECRAWL_PROVENIENCIA_INSEGURA"):
                executar("firecrawl", origem="https://conab.gov.br/", politica=APROVADA)

    def test_cli_grava_evidencia_uma_unica_vez(self):
        with tempfile.TemporaryDirectory() as t:
            saida = Path(t) / "evidencia.json"
            self.assertEqual(main(["--capacidade", "diagnostico", "--saida", str(saida)]), 0)
            payload = json.loads(saida.read_text())
            self.assertFalse(payload["deploy_realizado"])
            self.assertEqual(main(["--capacidade", "diagnostico", "--saida", str(saida)]), 2)


if __name__ == "__main__":
    unittest.main()
