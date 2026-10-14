export type Geometry = {
  type: "Polygon" | "MultiPolygon";
  coordinates: number[][][] | number[][][][];
};
export type Property = { id: string; name: string };
export type Field = {
  id: string;
  property_id: string;
  property_name: string;
  name: string;
  area_ha: number;
  geometry: Geometry;
};
export type Analysis = {
  id: string;
  field_id: string;
  field_name: string;
  date_from: string;
  date_to: string;
  mode: "synthetic" | "satellite";
  status: "queued" | "running" | "completed" | "failed";
  origin?: "manual" | "automatic";
  error?: string;
  statistics?: {
    mean: number;
    minimum: number;
    maximum: number;
    valid_percent: number;
  };
};
export type User = {
  email: string;
  csrf_token: string;
  usage: { limit: number; used: number; reserved: number; available: number };
};
export type Config = { registration_enabled: boolean; demo_enabled: boolean };
export type View = "overview" | "properties" | "fields" | "analyses";

export type Monitoring = {
  field_id: string;
  enabled: boolean;
  crop: string;
  stage: "vegetative" | "reproductive" | "maturation" | "harvest";
  season_start: string;
  season_end: string;
  drop_threshold: number;
  next_run: string;
  state: string;
};
export type MonitoringAlert = {
  id: string;
  field_name: string;
  analysis_id: string;
  previous_mean: number;
  current_mean: number;
  scene_date: string;
  previous_date: string;
  read_at: string | null;
};
