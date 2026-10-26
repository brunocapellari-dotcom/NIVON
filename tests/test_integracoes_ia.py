"""Testes de contrato das integrações, completamente offline e sem credenciais reais."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nivon.integracoes_ia.core import (PoliticaIntegracao, ErroIntegracao,
    catalogo, diagnostico, dominio_publico_autorizado, evidencia,
    hash_texto, limitar_contexto)
from nivon.integracoes_ia.provedores import (consultar_firecrawl,
    listar_paperclip, consultar_hindsight, consultar_pageindex)
from nivon.integracoes_ia.engenharia import (aceite_trabalho, dependencias_python,
    importar_graphify, gerar_skill_rascunho)


POLITICA = PoliticaIntegracao(True, True, ("conab.gov.br", "paperclip.exemplo.com", "memoria.exemplo.com"))


class _Resposta:
    status = 200
    headers = {"Content-Type": "application/json; charset=utf-8"}

    def __init__(self, dado):
        self.buffer = io.BytesIO(json.dumps(dado).encode())

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, n): return self.buffer.read(n)


class _HTTP:
    def __init__(self, resposta):
        self.resposta = resposta
        self.requisicoes = []

    def open(self, req, timeout):
        self.requisicoes.append(req)
        return _Resposta(self.resposta)


class ContratosTest(unittest.TestCase):
    def test_import_nunca_liga_rede(self):
        self.assertTrue(catalogo())
        self.assertTrue(diagnostico())
        self.assertEqual({x["prioridade"] for x in catalogo()}, {"P0", "P1", "P2"})

    def test_externo_bloqueado_por_padrao(self):
        with self.assertRaisesRegex(ErroIntegracao, "REDE_EXTERNA_NAO_AUTORIZADA"):
            consultar_firecrawl("https://conab.gov.br/relatorio", PoliticaIntegracao())

    def test_firecrawl_credencial_e_campo_de_proveniencia(self):
        http = _HTTP({"success": True, "data": {"markdown": "Safra CONAB em estudo"}})
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "segredo-TESTE"}):
            out = consultar_firecrawl("https://conab.gov.br/relatorio", POLITICA, opener=http)
        self.assertEqual(out["evidencia"]["natureza"], "EXTRAIDO_NAO_VALIDADO")
        self.assertFalse(out["evidencia"]["publicavel"])
        self.assertIn("api.firecrawl.dev/v2/scrape", http.requisicoes[0].full_url)
        self.assertNotIn("segredo-TESTE", json.dumps(out))

    def test_firecrawl_sem_chave_e_sem_texto(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ErroIntegracao):
            consultar_firecrawl("https://conab.gov.br/relatorio", POLITICA)
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "x"}), self.assertRaises(ErroIntegracao):
            consultar_firecrawl("https://conab.gov.br/relatorio", POLITICA,
                                opener=_HTTP({"success": True, "data": {}}))

    def test_protege_urls_proibidas(self):
        invalidas = ["http://conab.gov.br/p", "https://localhost/x",
                     "https://127.0.0.1/p", "https://10.2.3.4/x", "https://conab.gov.br.evil.com/a",
                     "https://p:senha@conab.gov.br/a", "https://conab.gov.br:8080/a",
                     "https://conab.gov.br/a#x", "https://metadata.google.internal/computeMetadata/v1"]
        for url in invalidas:
            with self.subTest(url=url), self.assertRaises(ErroIntegracao):
                dominio_publico_autorizado(url, ("conab.gov.br",))
        self.assertEqual(dominio_publico_autorizado("https://conab.gov.br/a", ("conab.gov.br",)),
                         "https://conab.gov.br/a")

    def test_paperclip_somente_leitura(self):
        http = _HTTP([{"id": "x1", "title": "Revisar PR", "status": "todo"}])
        cfg = {"PAPERCLIP_API_KEY": "privado", "NIVON_PAPERCLIP_ORIGEM": "https://paperclip.exemplo.com/",
               "NIVON_PAPERCLIP_COMPANY_ID": "nivon"}
        with patch.dict(os.environ, cfg):
            r = listar_paperclip(POLITICA, opener=http)
        self.assertEqual(r["tarefas_externas"][0]["titulo"], "Revisar PR")
        self.assertEqual(http.requisicoes[0].get_method(), "GET")
        self.assertFalse(r["canonica"])
        self.assertNotIn("privado", json.dumps(r))

    def test_paperclip_bloqueia_origem_nao_aprovada(self):
        with patch.dict(os.environ, {"PAPERCLIP_API_KEY": "x", "NIVON_PAPERCLIP_ORIGEM": "https://evil.test/",
                                   "NIVON_PAPERCLIP_COMPANY_ID": "nivon"}):
            with self.assertRaises(ErroIntegracao): listar_paperclip(POLITICA, opener=_HTTP([]))

    def test_memoria_read_only(self):
        class Cliente:
            def recall(self, **kwargs):
                self.dados = kwargs
                return type("Resultado", (), {"results": [type("Mem", (), {"text": "Dado histórico"})()]})()
        c = Cliente()
        with patch.dict(os.environ, {"NIVON_HINDSIGHT_BANK_ID": "nivon-operacao",
                                   "NIVON_HINDSIGHT_URL": "https://memoria.exemplo.com",
                                   "NIVON_HINDSIGHT_API_KEY": "x"}):
            r = consultar_hindsight("O que mudou?", POLITICA, cliente=c)
        self.assertEqual(c.dados["bank_id"], "nivon-operacao")
        self.assertEqual(r["natureza"], "MEMORIA_NAO_VALIDADA")
        self.assertFalse(r["publicavel"])

    def test_pdf_indexacao_sem_publicacao(self):
        class Cliente:
            def submit_document(self, arquivo, wait): return {"doc_id": "doc100"}
            def chat(self, *args, **kwargs): return "Resposta inicial não validada"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"relatorio.pdf"
            p.write_bytes(b"%PDF-1.4 exemplo")
            with patch.dict(os.environ, {"NIVON_PAGEINDEX_MODELO": "openai/modelo",
                                       "NIVON_PAGEINDEX_CHAT_MODELO": "openai/modelo"}):
                r = consultar_pageindex(p, "Qual a conclusao?", POLITICA, cliente=Cliente())
            self.assertEqual(r["natureza"], "INFERIDO")
            self.assertFalse(r["publicavel"])
            self.assertEqual(len(r["documento_sha256"]), 64)

    def test_aceite_nao_homologa_sozinho(self):
        x = aceite_trabalho(tarefa="NIVON-M1", pr=324, commit="a"*40, testes="SUCESSO",
                           evidencia_url="https://foo.run.app/", deploy=True)
        self.assertFalse(x["homologado"])
        self.assertEqual(x["estado"], "EVIDENCIA_PENDENTE_DE_VALIDACAO")
        y = aceite_trabalho(tarefa="NIVON-M1", pr=324, commit="a"*40, testes="PULADO", deploy=True)
        self.assertEqual(y["estado"], "NAO_APROVADO")

    def test_grafo_analisa_sem_executar_codigo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz/"modulo.py").write_text("import nivon.portal_interno\nfrom .motor import iniciar\n")
            r = dependencias_python(raiz)
            self.assertIn({"arquivo": "modulo.py", "importa": "nivon.portal_interno"}, r["arestas"])
            self.assertIn({"arquivo": "modulo.py", "importa": ".motor"}, r["arestas"])

    def test_exportacao_graphify_quarentena(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"graph.json"
            p.write_text('{"nodes": [], "edges": []}')
            out = importar_graphify(p)
            self.assertFalse(out["apto_como_fonte_canonica"])

    def test_book_to_skill_nao_vira_skill_ativa(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = gerar_skill_rascunho("boletim-agro", "Conteudo fornecido com evidencia. "*4,
                                     "https://conab.gov.br/exemplo", Path(tmp))
            self.assertEqual(p.name, "boletim-agro.rascunho.md")
            self.assertIn("NÃO EXECUTAR", p.read_text())
            with self.assertRaises(FileExistsError):
                gerar_skill_rascunho("boletim-agro", "Conteudo fornecido com evidencia. "*4,
                                     "https://conab.gov.br/exemplo", Path(tmp))

    def test_truncamento_explicito_e_hash(self):
        t = limitar_contexto("A"*900, limite=300)
        self.assertTrue(t["truncado"])
        self.assertEqual(t["sha256_original"], hash_texto("A"*900))
        self.assertTrue(t["nao_usar_como_evidencia_integral"])


if __name__ == "__main__":
    unittest.main()
