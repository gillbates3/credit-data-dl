import asyncio
import importlib.util
from pathlib import Path
import sys

# Caminho do script
script_path = Path(__file__).parent / "scripts" / "01_download_anbima.py"

# Carrega o módulo dinamicamente
spec = importlib.util.spec_from_file_location("scraper", script_path)
scraper = importlib.util.module_from_spec(spec)
sys.modules["scraper"] = scraper
spec.loader.exec_module(scraper)

# Sobrescreve a lista de tickers para o teste
scraper.TICKERS = ["IRJS15"] # Testa com um papel conhecido
scraper.MAX_CONCURRENT_TICKERS = 3

if __name__ == "__main__":
    asyncio.run(scraper.main())
