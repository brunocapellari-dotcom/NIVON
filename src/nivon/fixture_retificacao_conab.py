"""Gerador EXCLUSIVAMENTE de fixture XLSX artificial para testes de retificação.

Jamais usar como arquivo emitido pela CONAB. Modifica uma célula
numérica de progresso na coluna E e retorna novos bytes verificáveis.
"""
from __future__ import annotations

import io
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

NS="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def alterar_xlsx_apenas_teste(original: bytes):
    src=io.BytesIO(original)
    dest=io.BytesIO()
    changed=[]
    with ZipFile(src) as zin, ZipFile(dest,"w") as zout:
        for file in zin.infolist():
            payload=zin.read(file.filename)
            if file.filename.startswith("xl/worksheets/sheet") and file.filename.endswith(".xml"):
                root=ET.fromstring(payload)
                for cell in root.iter(NS+"c"):
                    loc=cell.get("r","")
                    if not re.fullmatch(r"E[1-9][0-9]*",loc) or cell.get("t","n") not in ("n",None):
                        continue
                    val=cell.find(NS+"v")
                    if val is None or val.text is None:
                        continue
                    try:
                        number=float(val.text)
                    except ValueError:
                        continue
                    if 0.02<=number<=0.90:
                        val.text=repr(round(number+0.015,8))
                        changed.append(loc)
                        payload=ET.tostring(root,encoding="utf-8",xml_declaration=True)
                        break
            zout.writestr(file,payload)
    if len(changed)!=1:
        raise ValueError("fixture XLSX não contém uma célula E numérica esperada; não simular revisão")
    return dest.getvalue(),changed[0]
