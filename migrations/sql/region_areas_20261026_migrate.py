"""Calculate region areas using the game calibration; UAT only, with backups."""
import json, math, hashlib, csv
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely import make_valid
from shapely.validation import explain_validity

def polygon_parts(g):
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        return [p for part in g.geoms for p in polygon_parts(part)]
    return []

root=Path(__file__).resolve().parents[2]
source=root/'static/maps/entenda_regiony.geojson'
raw=source.read_bytes()
features=json.loads(raw)['features']
engine=create_engine(dotenv_values(root/'.env.uat')['DATABASE_URL'])
assert engine.url.database=='entenda_uat_db'
query=text("SELECT region_id,region_nazwa,region_powierzchnia FROM regiony ORDER BY region_id")
with engine.connect() as conn:
    exists=conn.execute(text("SHOW COLUMNS FROM regiony LIKE 'region_powierzchnia'")).first()
    if not exists:
        conn.execute(text('ALTER TABLE regiony ADD COLUMN region_powierzchnia BIGINT NULL'))
        conn.commit()
with engine.begin() as conn:
    calibration=dict(conn.execute(text('SELECT * FROM game_map_calibration WHERE id=1 FOR UPDATE')).mappings().one())
    scale=calibration['km_per_unit']
    reference=math.hypot(calibration['reference_a_x']-calibration['reference_b_x'],calibration['reference_a_y']-calibration['reference_b_y'])*scale
    assert math.isclose(reference,calibration['reference_km'],rel_tol=1e-10)
    regions=[dict(r) for r in conn.execute(text(str(query)+' FOR UPDATE')).mappings()]
    assert regions
    ids={r['region_id'] for r in regions}
    geometries=defaultdict(list)
    repairs=[]
    for feature in features:
        region_id=feature['properties']['region_id']
        if region_id in ids:
            geom=shape(feature['geometry'])
            if not geom.is_valid:
                reason=explain_validity(geom)
                old_area=geom.area
                geom=make_valid(geom)
                repairs.append(dict(region_id=region_id,reason=reason,old_map_area=old_area,repaired_map_area=geom.area))
                assert math.isclose(old_area,geom.area,rel_tol=1e-10)
            assert geom.is_valid
            geometries[region_id].extend(polygon_parts(geom))
    missing=[r for r in regions if r['region_id'] not in geometries]
    regions=[r for r in regions if r['region_id'] in geometries]
    rows=[]
    for region in regions:
        cid=region['region_id']
        geom=unary_union(geometries[cid])
        assert geom.is_valid and geom.area>0
        value=int(Decimal(str(geom.area*scale**2)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        rows.append(dict(region,map_area=geom.area,new_area_km2=value))
    out=root/'migrations/sql'/('region_areas_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False)
    report={'database':engine.url.database,'source':str(source),'source_sha256':hashlib.sha256(raw).hexdigest(),'calibration':calibration,'geometry_repairs':repairs,'missing_geometry':missing,'method':'Planar union of region polygons, holes excluded; area * km_per_unit^2; rounded to nearest whole km²','regions':rows}
    (out/'backup_and_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (out/'results.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['region_id','region_nazwa','old_area_km2','new_area_km2'])
        writer.writerows((r['region_id'],r['region_nazwa'],r['region_powierzchnia'],r['new_area_km2']) for r in rows)
    rollback=['-- Database: entenda_uat_db; restore only if the computed value is still present.','START TRANSACTION;']
    for r in rows:
        old='NULL' if r['region_powierzchnia'] is None else str(r['region_powierzchnia'])
        rollback.append(f"UPDATE regiony SET region_powierzchnia={old} WHERE region_id={r['region_id']} AND region_powierzchnia={r['new_area_km2']};")
    rollback.append('COMMIT;')
    (out/'rollback.sql').write_text('\n'.join(rollback)+'\n')
    for r in rows:
        result=conn.execute(text('UPDATE regiony SET region_powierzchnia=:area WHERE region_id=:id AND region_powierzchnia <=> :old'),{'area':r['new_area_km2'],'id':r['region_id'],'old':r['region_powierzchnia']})
        assert result.rowcount==1
    actual={r['region_id']:r['region_powierzchnia'] for r in conn.execute(query).mappings() if r['region_id'] in geometries}
    assert actual=={r['region_id']:r['new_area_km2'] for r in rows}
with engine.connect() as conn:
    actual={r['region_id']:r['region_powierzchnia'] for r in conn.execute(query).mappings() if r['region_id'] in geometries}
    assert actual=={r['region_id']:r['new_area_km2'] for r in rows}
print('Committed and verified',len(rows),'regions in',engine.url.database)
print('Report:',out)
print('Missing geometry:',missing)
print('Total km²:',sum(r['new_area_km2'] for r in rows))
