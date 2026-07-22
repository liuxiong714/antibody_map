import sys

file = r"e:\linux\trae_project\antibody_map01\frontend\src\layouts\MainLayout.tsx"
with open(file, "r", encoding="utf-8") as f:
    data = f.read()

old = """  { key: '/assessment', icon: <SafetyOutlined />, label: '\u514d\u75ab\u5c4f\u969c\u8bc4\u4f30' },
  { key: '/analysis', icon: <BarChartOutlined />, label: '\u6570\u636e\u5206\u6790' },"""

new = """  { key: '/analysis', icon: <BarChartOutlined />, label: '\u6570\u636e\u5206\u6790' },
  { key: '/assessment', icon: <SafetyOutlined />, label: '\u514d\u75ab\u5c4f\u969c\u8bc4\u4f30' },"""

data = data.replace(old, new)

with open(file, "w", encoding="utf-8") as f:
    f.write(data)

print("Menu order fixed!")
