"""Converte traduções em TSV ("número<TAB>texto") para scarlet/locales/<idioma>.json e valida os marcadores {…}.

Uso: python tools/build_locales.py [pasta_dos_tsv]   (padrão: tools/translations)
Frases criadas depois da numeração usam a forma "=texto original<TAB>tradução".
Frases criadas depois da numeração usam a forma "=texto original<TAB>tradução".
A numeração é a da lista original de 478 frases (a posição 104 foi removida depois); por isso
a lista atual recebe um buraco na posição 104 antes de mapear.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PH = re.compile(r"\{[^{}]*\}")


def main(src_dir):
    keys = json.load(open(os.path.join(ROOT, "scarlet", "locales", "_keys.json"), encoding="utf-8"))
    keys.insert(104, None)
    problems = 0
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".tsv"):
            continue
        lang = name[:-4]
        table = {}
        for ln, line in enumerate(open(os.path.join(src_dir, name), encoding="utf-8").read().splitlines(), 1):
            if not line.strip():
                continue
            idx, _, text = line.partition("\t")
            if idx.startswith("="):            # frase nova: "=texto original<TAB>tradução"
                i = idx
                key = idx[1:].replace("\\n", "\n")
            else:
                i = int(idx)
                key = keys[i] if i < len(keys) else None
            if key is None:
                print(f"{lang}:{ln}: índice {i} inválido")
                problems += 1
                continue
            text = text.replace("\\n", "\n").replace("\\t", "\t")
            if sorted(PH.findall(key)) != sorted(PH.findall(text)):
                print(f"{lang}:{ln}: marcadores diferentes em {i}: {PH.findall(key)} != {PH.findall(text)}")
                problems += 1
                continue
            table[key] = text
        out = os.path.join(ROOT, "scarlet", "locales", lang + ".json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"{lang}: {len(table)} frases")
    return problems


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tools", "translations")) else 0)
