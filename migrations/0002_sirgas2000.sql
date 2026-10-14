-- Keep the first migration immutable. Upgrade existing WGS84 coordinates,
-- including queued job snapshots, through a real transform. RLS stays forced.
SELECT set_config('delta.worker', 'on', true);
ALTER TABLE fields ALTER COLUMN shape TYPE geometry(MultiPolygon, 4674)
    USING ST_Transform(shape, 4674);
UPDATE fields SET geometry = ST_AsGeoJSON(
    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326), 4674), 15, 0)::jsonb,
    area_ha = ST_Area(shape::geography) / 10000.0;
UPDATE analyses SET geometry = ST_AsGeoJSON(
    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326), 4674), 15, 0)::jsonb;
ALTER TABLE fields ADD COLUMN geometry_crs INTEGER NOT NULL DEFAULT 4674 CHECK (geometry_crs = 4674);
ALTER TABLE analyses ADD COLUMN geometry_crs INTEGER NOT NULL DEFAULT 4674 CHECK (geometry_crs = 4674);
ALTER TABLE fields ADD CONSTRAINT fields_geometry_matches_shape CHECK (
    ST_Equals(ST_SnapToGrid(shape, 1e-12), ST_SnapToGrid(ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4674), 1e-12)));
