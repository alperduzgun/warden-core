
import re

pattern_str = r"requests\.(?:get|post|put|delete|patch)\([^)]*?\)(?!.*timeout)"
pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)

line = '    response = requests.get("https://api.example.com/data")'

match = pattern.search(line)
if match:
    print("MATCH FOUND:", match.group(0))
else:
    print("NO MATCH")
