#!/usr/bin/env python3
"""Auditoria estrutural sem dependências externas para identidade visual NIVON."""
from pathlib import Path
import xml.etree.ElementTree as ET
import json
import re

ROOT = Path(__file__).resolve().parent
FILES = ['symbol.svg', 'logo-horizontal.svg', 'logo-reverse.svg',
         'logo-monochrome.svg', 'app-icon.svg', 'favicon.svg', 'identity-preview.svg']
LOGOS = FILES[:-1]
REQUIRED = ['green_deep', 'green_agro', 'gold_harvest', 'sand', 'earth', 'white']
FORBIDDEN = ('®', '™', 'http://', 'https://', 'javascript:', '<script', '<foreignObject')
NS = '{http://www.w3.org/2000/svg}'

def luminance(color):
    v = [int(color[k:k+2], 16)/255 for k in (1, 3, 5)]
    v = [x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in v]
    return sum(a*b for a,b in zip(v, [.2126, .7152, .0722]))

def contrast(a, b):
    x, y = sorted([luminance(a), luminance(b)], reverse=True)
    return (x+.05)/(y+.05)

def audit():
    errors = []
    spec = json.loads((ROOT/'brand-tokens.json').read_text(encoding='utf-8'))
    palette = spec['palette']
    for key in REQUIRED:
        if key not in palette or not re.fullmatch('#[0-9A-Fa-f]{6}', palette[key]['hex']):
            errors.append(f'Paleta inválida: {key}')
    for name in FILES:
        txt = (ROOT/name).read_text(encoding='utf-8')
        try:
            svg = ET.fromstring(txt)
        except ET.ParseError as exc:
            errors.append(f'{name}: XML inválido: {exc}')
            continue
        if svg.tag != NS+'svg' or not svg.attrib.get('viewBox'):
            errors.append(f'{name}: raiz/viewBox inválidos')
        if svg.find(NS+'title') is None:
            errors.append(f'{name}: sem título acessível')
        if not svg.findall('.//'+NS+'path'):
            errors.append(f'{name}: sem geometria vetorial')
        sanitized = txt.replace('xmlns="http://www.w3.org/2000/svg"', '')
        if any(f in sanitized for f in FORBIDDEN):
            errors.append(f'{name}: contém referência externa ou símbolo proibido')
        if name in LOGOS and svg.findall('.//'+NS+'text'):
            errors.append(f'{name}: marca contém texto não vetorizado')
    if spec['artwork']['wordmark'] != 'logo-horizontal.svg':
        errors.append('Contrato de marca divergente')
    pairs = [('green_deep','white',7),('green_deep','sand',7),
             ('green_agro','white',4.5),('green_agro','sand',4.5),
             ('gold_harvest','green_deep',4.5)]
    for a,b,min_ratio in pairs:
        ratio = contrast(palette[a]['hex'], palette[b]['hex'])
        if ratio < min_ratio:
            errors.append(f'Contraste insuficiente: {a}/{b}={ratio:.2f}')
        print(f'Contraste {a}/{b}: {ratio:.2f}:1')
    if errors:
        for e in errors: print('FALHA:', e)
        return 1
    print(f'PASSOU: {len(FILES)} arquivos SVG, paleta, caminhos e pares essenciais de contraste.')
    return 0

if __name__ == '__main__':
    raise SystemExit(audit())
