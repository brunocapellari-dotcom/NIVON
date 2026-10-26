"""Contrato da prévia NIVON: nenhum dado privado ou inferência como produção."""
from html.parser import HTMLParser
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1] / "apps" / "nivon-terminal"


class Estrutura(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=set()
        self.links=[]
        self.errors=[]
    def handle_starttag(self,tag,attrs):
        props=dict(attrs)
        if "id" in props:
            if props["id"] in self.ids:self.errors.append("id repetido")
            self.ids.add(props["id"])
        if tag=="script":
            self.links.append(props.get("src"))
        if tag=="link" and props.get("rel")=="stylesheet":
            self.links.append(props.get("href"))


class TestTerminalPublico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"index.html").read_text(encoding="utf-8")
        cls.js=(ROOT/"app.js").read_text(encoding="utf-8")
        cls.css=(ROOT/"styles.css").read_text(encoding="utf-8")
        cls.config=json.loads((ROOT/"vercel.json").read_text(encoding="utf-8"))

    def test_terminal_minimo_e_responsivo(self):
        checker=Estrutura()
        checker.feed(self.html)
        self.assertFalse(checker.errors)
        for target in ("conteudo","logistica","fontes","criterios","refresh","source-grid"):
            self.assertIn(target,checker.ids)
        self.assertEqual(sorted(checker.links),["/app.js","/styles.css"])
        self.assertIn("width=device-width",self.html)
        self.assertIn("prefers-reduced-motion",self.css)
        self.assertIn("@media(max-width:720px)",self.css)

    def test_indicadores_historicos_apenas(self):
        for value in ("36.694","555,08","98,17","500,8","530,8","541,9","555,1"):
            self.assertIn(value,self.html)
        self.assertIn("2022–ago. 2026",self.html)
        self.assertIn("ANTT/SIADE",self.html)
        self.assertIn("Amostra Top 16",self.html)
        self.assertIn("não devem ser somados",self.html)

    def test_alerta_de_qualidade_e_limites(self):
        for phrase in ("PRÉVIA TÉCNICA","sem dados pessoais","não significa dado novo",
                       "inferência","não é a homologação integral"):
            self.assertIn(phrase.casefold(),self.html.casefold())
        for value in ("COTAÇÕES_NEGOCIADAS","AIS_HOMOLOGADO","GO_LIVE_COMPLETO"):
            self.assertNotIn(value,self.html)

    def test_fonte_dinamica_sem_token_e_sem_xss(self):
        self.assertIn("api.github.com",self.js)
        self.assertIn('credentials: "omit"',self.js)
        self.assertIn('cache: "no-store"',self.js)
        self.assertIn("textContent",self.js)
        self.assertIn("replaceChildren",self.js)
        self.assertNotIn("innerHTML",self.js)
        self.assertNotIn("Authorization:",self.js)
        self.assertNotIn("localStorage",self.js)
        self.assertIn("data novo",self.js) if "data novo" in self.js else self.assertIn("frescor",self.js)
        self.assertIn("CEPEA",self.js)
        self.assertIn("IMEA",self.js)
        self.assertIn("CONAB",self.js)
        self.assertIn("PTAX",self.js)
        self.assertIn("ANTT",self.js)

    def test_hospedagem_com_isolamento_de_segredos(self):
        headers={h["key"]:h["value"] for group in self.config["headers"]
                 for h in group["headers"]}
        self.assertIn("default-src 'none'",headers["Content-Security-Policy"])
        self.assertIn("connect-src https://api.github.com",headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])
        self.assertIn("noindex",headers["X-Robots-Tag"])
        self.assertIn("Disallow: /",(ROOT/"robots.txt").read_text())
        self.assertFalse((ROOT/"package.json").exists())
        self.assertFalse((ROOT/".env").exists())

if __name__=="__main__":
    unittest.main()
