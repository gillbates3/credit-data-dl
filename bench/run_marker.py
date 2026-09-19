"""Runner Marker: PDF -> Markdown, com faixa de páginas opcional.

Requer o binário nativo `llama-server` (llama.cpp) no PATH, ou a variável
LLAMA_CPP_BINARY apontando para ele — o backend do surya 0.22 usa esse binário
para inferência de layout/OCR. Sem ele, o Marker falha com:
    surya ... SpawnError: llama-server binary not found

Instalação do binário:
    macOS:  brew install llama.cpp
    Linux:  release pré-compilado em https://github.com/ggml-org/llama.cpp/releases
            (asset ubuntu-x64) no PATH, OU compile, OU export LLAMA_CPP_BINARY=/path/llama-server

Uso:
    python run_marker.py <pdf> <saida.md> [ini-fim]   # ini-fim 0-indexado, ex "2-7"
"""
import sys
import time

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

pdf, out = sys.argv[1], sys.argv[2]
config = {}
if len(sys.argv) > 3:
    config["page_range"] = sys.argv[3]

t0 = time.time()
converter = PdfConverter(artifact_dict=create_model_dict(), config=config)
text, _, _ = text_from_rendered(converter(pdf))
dt = time.time() - t0

with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(f"[marker] {pdf} -> {out} em {dt:.1f}s | {len(text)} chars | pipes={text.count('|')}")
