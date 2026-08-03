import re

f = 'frontend/src/pages/MapOverview.tsx'
c = open(f, 'r', encoding='utf-8').read()

# 1. geoJson state -> mapReady state
c = c.replace(
    'const [geoJson, setGeoJson] = useState<object | null>(null);',
    'const [mapReady, setMapReady] = useState(false);'
)

# 2. Register map sync then set ready
old2 = """  // Load GeoJSON
  useEffect(() => {
    fetch('https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json')
      .then((r) => r.json())
      .then((data) => setGeoJson(data))
      .catch(() => message.error('地图数据加载失败'));
  }, []);"""
new2 = """  // Load GeoJSON - register map before trigger render
  useEffect(() => {
    fetch('https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json')
      .then((r) => r.json())
      .then((data) => {
        echarts.registerMap('china', data);
        setMapReady(true);
      })
      .catch(() => message.error('地图数据加载失败'));
  }, []);"""
c = c.replace(old2, new2)

# 3. Remove registerMap useEffect
old3_re = re.compile(r'  // Register map when GeoJSON loaded\n  useEffect\(\(\) => \{[^}]+\}, \[geoJson\]\);\n')
c = old3_re.sub('', c)

# 4. Remove guard in getOption
c = c.replace('    if (!geoJson) return {};\n    const', '    const')

# 5. Change conditional render
c = c.replace('{geoJson ? (', '{mapReady ? (')

open(f, 'w', encoding='utf-8').write(c)
print('Done')
