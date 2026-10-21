#!/usr/bin/env python3
"""Exporta SVGs canônicos de marca para PNGs sem incorporar fontes ou dados fictícios."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parent
SIZES = {'symbol.svg':512, 'logo-horizontal.svg':1700,
         'logo-reverse.svg':1700, 'logo-monochrome.svg':1700,
         'app-icon.svg':1024, 'favicon.svg':192, 'identity-preview.svg':1400}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        import cairosvg
    except ImportError as exc:
        raise SystemExit('Instale cairosvg para exportar os SVGs: pip install cairosvg') from exc
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, width in SIZES.items():
        dest = out/(Path(name).stem+'.png')
        cairosvg.svg2png(url=str(ROOT/name), write_to=str(dest), output_width=width)
        print(dest)
    for width in (16, 32, 48):
        dest = out/f'favicon-{width}.png'
        cairosvg.svg2png(url=str(ROOT/'favicon.svg'), write_to=str(dest), output_width=width)
        print(dest)

if __name__ == '__main__':
    main()
