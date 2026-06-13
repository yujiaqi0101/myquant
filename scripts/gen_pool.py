import openpyxl
wb = openpyxl.load_workbook(r"D:\python_workspace\myquant\docs\股票与ETF清单.xlsx")
ws = wb.active
codes = []
for row in ws.iter_rows(min_row=2, values_only=True):
    if row[0]:
        c = str(row[0]).strip()
        if c.startswith("sh"):
            codes.append("SHSE." + c[2:])
        elif c.startswith("sz"):
            codes.append("SZSE." + c[2:])
print(f"Total: {len(codes)}")

with open(r"D:\python_workspace\myquant\docs\stock_pool_code.txt", "w", encoding="utf-8") as f:
    for i in range(0, len(codes), 5):
        chunk = codes[i:i+5]
        quoted = ['"' + c + '"' for c in chunk]
        f.write("        " + ",".join(quoted) + ",\n")

# Verify
with open(r"D:\python_workspace\myquant\docs\stock_pool_code.txt", "r", encoding="utf-8") as f:
    for i, ln in enumerate(f):
        if i < 3:
            print(ln.rstrip())
print("Done")
