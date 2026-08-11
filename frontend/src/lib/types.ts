export type Geometry =
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] }

export type User = {
  id: string
  username: string
  email: string
  first_name: string
  last_name: string
}

export type Tenant = {
  id: string
  name: string
  schema_name: string
  role: string
}

export type Session = { user: User; tenant: Tenant }
export type LoginResponse = Session & { access: string; refresh: string }

export type Paginated<T> = {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export type Property = {
  id: string
  name: string
  description: string
  geometry: Geometry
  area_hectares: string
  city: string
  state: string
  country: string
  created_by: string
  created_at: string
  updated_at: string
}

export type CreditAccount = {
  id: string
  available_balance: number
  reserved_balance: number
  updated_at: string
}

export type CreditTransaction = {
  id: string
  transaction_type: string
  amount: number
  map_job: string | null
  available_balance_after: number
  reserved_balance_after: number
  metadata: Record<string, unknown>
  created_at: string
}

export type ProcessingPrice = { index_type: string; credit_cost: number }

export type MapJobStatus =
  | 'PENDING'
  | 'SEARCHING_SCENE'
  | 'DOWNLOADING'
  | 'PREPROCESSING'
  | 'PROCESSING'
  | 'RENDERING'
  | 'UPLOADING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export type MapJob = {
  id: string
  status: MapJobStatus
  progress: number
  current_step: string
  index_type: string
  geometry_snapshot: Geometry
  property_id: string | null
  property_name: string | null
  requested_scene_date: string | null
  date_from: string | null
  date_to: string | null
  max_cloud_cover: string
  stac_item_id: string
  error_code: string
  error_message: string
  credit_cost: number
  created_by: string
  created_at: string
  heartbeat_at: string | null
  started_at: string | null
  finished_at: string | null
  cancelled_at: string | null
  cancelled_by: string | null
  reprocessed_from_id: string | null
  generated_map_id: string | null
}

export type GeneratedMap = {
  id: string
  job_id: string
  property_id: string | null
  property_name: string | null
  index_type: string
  geometry_snapshot: Geometry
  scene_date: string
  stac_item_id: string
  cloud_cover: string | null
  metadata: Record<string, unknown>
  png_download_url: string
  pdf_download_url: string
  created_by: string
  created_at: string
}
