import requests
import re
from urllib.parse import urljoin

html = requests.get('https://data.anbima.com.br/debentures/ALAR14').text
js_files = re.findall(r'src="(/titulos-privados/static/js/[^"]+\.js)"', html)
print("JS Files:", js_files)

for js in js_files:
    url = urljoin('https://data.anbima.com.br/', js)
    js_content = requests.get(url).text
    endpoints = re.findall(r'"(/[^"]*debenture[^"]*)"|''(/[^\']*debenture[^\']*)''', js_content)
    if endpoints:
        print(url, ":")
        for ep in endpoints:
            print("  ", ep[0] or ep[1])
