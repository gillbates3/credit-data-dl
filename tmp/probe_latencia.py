"""Prova onde vai o tempo de uma chamada: TTFT (input) vs geração (output)."""
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pdfplumber  # noqa: E402
from google.genai import types  # noqa: E402
from scripts_v2 import servico_ia_qualitativa as qual  # noqa: E402

CLIENT = qual.CLIENT
pasta = Path("data/01_landing/manual_uploads/arteris/Regis Bittencourt")
conteudo = (pasta / "Relatorio Anual 2025.pdf").read_bytes()

with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
    pages = pdf.pages[:8]
    parts = []
    for i, p in enumerate(pages):
        t = (p.extract_text() or "").strip()
        if len(t) >= qual.MIN_TEXT_CHARS_PER_PAGE:
            parts.append(f"\n\n--- PÁGINA {i + 1} ---\n{t}")
    texto, _ = qual.sanitize_extracted_text("".join(parts).strip())

prompt = f"CNPJ: x\nArquivo: chunk 1-8\n\n{qual.PROMPT_QUALITATIVO}\n\nTexto extraído do PDF:\n{texto}"
cfg = types.GenerateContentConfig(temperature=0.0)
print(f"Prompt: {len(prompt):,} chars (~{len(prompt)//4:,} tokens de entrada)")

def medir(model_id):
    t0 = time.perf_counter()
    ttft = None
    chars_saida = 0
    for ch in CLIENT.models.generate_content_stream(model=model_id, contents=prompt, config=cfg):
        txt = getattr(ch, "text", None)
        if txt:
            if ttft is None:
                ttft = time.perf_counter() - t0
            chars_saida += len(txt)
    return ttft, chars_saida, time.perf_counter() - t0


ttft = chars_saida = total = None
model_usado = None
for mid in ("gemini-2.5-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"):
    try:
        ttft, chars_saida, total = medir(mid)
        model_usado = mid
        break
    except Exception as e:
        print(f"  [{mid}] falhou ({str(e)[:70]}). Tentando de novo/fallback...")
        time.sleep(8)

if model_usado is None:
    raise SystemExit("Todas as tentativas falharam (503).")

print(f"Modelo medido: {model_usado}")
print(f"TTFT (tempo até o 1o token de saída): {ttft:.2f}s")
print(f"Tempo TOTAL da chamada:               {total:.2f}s")
print(f"Tempo gerando output (após 1o token): {total - (ttft or 0):.2f}s  <-- AQUI vai o tempo")
print(f"Output gerado: {chars_saida:,} chars (~{chars_saida//4:,} tokens) | velocidade ~{(chars_saida//4)/max(total-(ttft or 0),0.01):.0f} tok/s")
