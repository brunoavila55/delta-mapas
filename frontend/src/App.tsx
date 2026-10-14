import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleAlert,
  Cloud,
  FolderOpen,
  LayoutDashboard,
  Leaf,
  LoaderCircle,
  LogOut,
  Map,
  Menu,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sprout,
  Upload,
  X,
} from "lucide-react";
import { api, clearSession, sessionEpoch, setSession } from "./api";
import type {
  Analysis,
  Monitoring,
  MonitoringAlert,
  Config,
  Field,
  Geometry,
  Property,
  User,
  View,
} from "./types";

const number = (value: number, digits = 0) =>
  value.toLocaleString("pt-BR", { maximumFractionDigits: digits });
const day = (value: string) =>
  value.slice(0, 10).split("-").reverse().join("/");
const localDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const labels = {
  queued: "Na fila",
  running: "Processando",
  completed: "Concluída",
  failed: "Não concluída",
};
const navigation = [
  { id: "overview", label: "Visão geral", icon: LayoutDashboard },
  { id: "properties", label: "Propriedades", icon: FolderOpen },
  { id: "fields", label: "Talhões", icon: Map },
  { id: "analyses", label: "Análises", icon: Leaf },
] as const;
const pages = {
  overview: [
    "Seu campo, em perspectiva.",
    "Uma visão de suas áreas e das últimas análises.",
  ],
  properties: ["Propriedades", "O ponto de partida para organizar suas áreas."],
  fields: ["Talhões", "Cada área, com seu próprio olhar."],
  analyses: ["Análises", "Da imagem de satélite à informação para sua área."],
};
type Modal =
  | { kind: "property" }
  | { kind: "field"; field?: Field; property?: string }
  | { kind: "analysis"; field: Field }
  | { kind: "monitoring"; field: Field }
  | { kind: "result"; analysis: Analysis };

function Brand() {
  return (
    <span className="brand">
      <span className="brand-symbol">△</span>
      <span>
        delta<span className="brand-sub">MAPAS</span>
      </span>
    </span>
  );
}
function Button({
  children,
  secondary = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean }) {
  return (
    <button
      {...props}
      className={`${secondary ? "button secondary" : "button"} ${props.className || ""}`}
    >
      {children}
    </button>
  );
}
function Status({ status }: { status: Analysis["status"] }) {
  return (
    <span className={`badge ${status}`}>
      <span />
      {labels[status]}
    </span>
  );
}
function Empty({
  icon = "field",
  title,
  description,
  action,
  onAction,
}: {
  icon?: "field" | "analysis" | "property" | "search";
  title: string;
  description: string;
  action?: string;
  onAction?: () => void;
}) {
  const Icon = {
    field: Map,
    analysis: Leaf,
    property: FolderOpen,
    search: Search,
  }[icon];
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={26} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action && (
        <Button onClick={onAction}>
          <Plus size={16} />
          {action}
        </Button>
      )}
    </div>
  );
}
function FieldPreview({
  geometry,
  compact = false,
}: {
  geometry: Geometry;
  compact?: boolean;
}) {
  const polygons = (
    geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates
  ) as number[][][][];
  const coords = polygons
    .flat(2)
    .filter((c) => Number.isFinite(c[0]) && Number.isFinite(c[1]));
  if (!coords.length)
    return (
      <div className="field-visual">
        <Map aria-label="Prévia indisponível" />
      </div>
    );
  const [left, right, bottom, top] = coords.reduce(
    ([l, r, b, t], [x, y]) => [
      Math.min(l, x),
      Math.max(r, x),
      Math.min(b, y),
      Math.max(t, y),
    ],
    [Infinity, -Infinity, Infinity, -Infinity],
  );
  const scale = Math.min(
    240 / Math.max(right - left, 0.000001),
    130 / Math.max(top - bottom, 0.000001),
  );
  const x = (n: number) => 160 + (n - (left + right) / 2) * scale;
  const y = (n: number) => 95 - (n - (top + bottom) / 2) * scale;
  return (
    <div className={`field-visual ${compact ? "compact" : ""}`}>
      <svg
        viewBox="0 0 320 190"
        role="img"
        aria-label="Contorno geográfico do talhão"
      >
        {polygons.map((polygon, i) => (
          <path
            key={i}
            fillRule="evenodd"
            d={polygon
              .map(
                (ring) =>
                  ring
                    .map((c, j) => `${j ? "L" : "M"}${x(c[0])},${y(c[1])}`)
                    .join(" ") + "Z",
              )
              .join(" ")}
          />
        ))}
      </svg>
      {!compact && <span className="visual-caption">CONTORNO DA ÁREA</span>}
    </div>
  );
}
function Dialog({
  title,
  subtitle,
  children,
  onClose,
  locked,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  locked: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!locked) onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !locked) {
          const b = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < b.left ||
            e.clientX > b.right ||
            e.clientY < b.top ||
            e.clientY > b.bottom
          )
            onClose();
        }
      }}
    >
      <div className="modal-heading">
        <div>
          <span className="eyebrow">DELTA MAPAS</span>
          <h2 id="dialog-title">{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <button
          className="icon-button"
          aria-label="Fechar"
          onClick={onClose}
          disabled={locked}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function Result({ item }: { item: Analysis }) {
  const [origin, setOrigin] = useState(
    item.mode === "synthetic"
      ? "Demonstração · resultado gerado com dados sintéticos."
      : "Imagem de satélite · consulte a origem e a data da cena no relatório.",
  );
  const [imageError, setImageError] = useState(false);
  const [cartographicAvailable, setCartographicAvailable] = useState(false);
  const base = `/api/analyses/${encodeURIComponent(item.id)}/files/`;
  useEffect(() => {
    let active = true;
    api<{
      products?: string[];
      source?: {
        metadata?: { tiles?: { date?: string; cloudCoverage?: number }[] };
      };
    }>(base + "analysis.json")
      .then((metadata) => {
        if (active)
          setCartographicAvailable(
            metadata.products?.includes("map.pdf") ?? false,
          );
        const scene = metadata.source?.metadata?.tiles?.[0];
        if (active && scene?.date)
          setOrigin(
            `Sentinel-2 L2A · Cena de ${day(scene.date)}${Number.isFinite(scene.cloudCoverage) ? ` · ${number(scene.cloudCoverage!, 1)}% de nuvens` : ""}`,
          );
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [base, item.mode]);
  return (
    <div className="result">
      <div className={`info-box ${item.mode === "synthetic" ? "demo" : ""}`}>
        <Leaf size={18} />
        {origin}
      </div>
      <div className="result-map">
        {imageError ? (
          <p role="alert">
            Não foi possível carregar o mapa. Feche e abra o resultado para
            tentar novamente.
          </p>
        ) : (
          <img
            src={base + "ndvi.png"}
            alt={`Mapa de NDVI de ${item.field_name}`}
            onError={() => setImageError(true)}
          />
        )}
      </div>
      <div className="legend">
        <span>−1</span>
        <div />
        <span>+1</span>
      </div>
      <p className="help center">
        Índice de vegetação (NDVI). Cinza indica ausência de observação válida.
      </p>
      {item.statistics && (
        <div className="result-stats">
          {[
            ["NDVI médio", item.statistics.mean.toFixed(3)],
            ["Mínimo", item.statistics.minimum.toFixed(3)],
            ["Máximo", item.statistics.maximum.toFixed(3)],
            ["Pixels válidos", number(item.statistics.valid_percent, 1) + "%"],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      )}
      <h3 className="download-title">Exporte seus resultados</h3>
      <div className="downloads">
        {[
          ...(cartographicAvailable
            ? [["map.pdf", "Mapa cartográfico PDF"]]
            : []),
          ["report.pdf", "Relatório PDF"],
          ["ndvi.png", "Mapa PNG"],
          ["ndvi.tif", "GeoTIFF"],
          ["analysis.json", "Metadados JSON"],
        ].map(([file, label]) => (
          <a href={base + file} download={file} key={file}>
            <ArrowDownToLine size={17} />
            {label}
          </a>
        ))}
      </div>
    </div>
  );
}
function FieldForm({
  initial,
  properties,
  property,
  pending,
  onSave,
}: {
  initial?: Field;
  properties: Property[];
  property?: string;
  pending: boolean;
  onSave: (data: {
    name: string;
    property_id: string;
    geometry: unknown;
  }) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [propertyId, setPropertyId] = useState(
    initial?.property_id || property || properties[0]?.id || "",
  );
  const [geometry, setGeometry] = useState(
    initial ? JSON.stringify(initial.geometry, null, 2) : "",
  );
  const [importing, setImporting] = useState(false),
    [detail, setDetail] = useState(""),
    [error, setError] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function importFile(file?: File) {
    if (!file) return;
    setImporting(true);
    setError("");
    setGeometry("");
    setDetail("");
    try {
      const zipped = file.name.toLowerCase().endsWith(".zip");
      if (file.size > (zipped ? 10000000 : 2000000))
        throw new Error(
          zipped ? "O ZIP deve ter até 10 MB." : "O GeoJSON deve ter até 2 MB.",
        );
      if (zipped) {
        const report = await api<{
          geometry: Geometry;
          area_ha: number;
          warnings: string[];
        }>("/api/imports/car", {
          method: "POST",
          headers: { "Content-Type": "application/zip" },
          body: file,
        });
        if (!active.current) return;
        setGeometry(JSON.stringify(report.geometry));
        setDetail(
          `${file.name} · ${number(report.area_ha, 2)} ha. ${report.warnings.join(" ")}`,
        );
        setName((current) =>
          current.trim() ? current : "Área do imóvel (CAR)",
        );
      } else {
        const content = await file.text();
        JSON.parse(content);
        if (!active.current) return;
        setGeometry(content);
        setDetail(`${file.name} · carregado. A área será validada ao salvar.`);
      }
    } catch (e) {
      if (active.current)
        setError(
          e instanceof Error ? e.message : "Não foi possível importar a área.",
        );
    } finally {
      if (active.current) setImporting(false);
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!geometry.trim()) {
      setError("Importe um arquivo ou cole o GeoJSON da área.");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(geometry);
    } catch {
      setError("O GeoJSON informado não é válido.");
      return;
    }
    await onSave({ name, property_id: propertyId, geometry: parsed });
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={pending || importing}>
        <label>
          Propriedade
          <select
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            required
          >
            {properties.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Nome do talhão
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ex.: Talhão Norte"
            required
            maxLength={120}
          />
        </label>
        <label className="upload-zone">
          <Upload size={25} />
          <strong>
            {importing ? "Importando área…" : "Importe o limite da sua área"}
          </strong>
          <span>ZIP do CAR (até 10 MB) ou GeoJSON (até 2 MB)</span>
          <input
            type="file"
            accept=".zip,.json,.geojson,application/zip,application/json"
            aria-label="Importar área"
            onChange={(e) => {
              void importFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        {detail && (
          <div className="info-box">
            <Check size={18} />
            {detail}
          </div>
        )}
        <details open={!!initial}>
          <summary>Colar ou conferir GeoJSON</summary>
          <label>
            Geometria da área
            <textarea
              value={geometry}
              onChange={(e) => setGeometry(e.target.value)}
              rows={6}
              placeholder="Cole o GeoJSON da área"
            />
          </label>
        </details>
        <p className="help">
          No ZIP do CAR, usamos a Área do Imóvel. Esse limite corresponde à
          propriedade inteira.
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit">
          <span>
            {pending
              ? "Salvando…"
              : importing
                ? "Importando…"
                : "Salvar talhão"}
          </span>
          <ArrowRight size={17} />
        </Button>
      </fieldset>
    </form>
  );
}
function AnalysisForm({
  field,
  config,
  pending,
  onSave,
}: {
  field: Field;
  config: Config;
  pending: boolean;
  onSave: (data: Record<string, unknown>, key: string) => Promise<void>;
}) {
  const today = new Date(),
    before = new Date(today);
  before.setDate(today.getDate() - 30);
  const [from, setFrom] = useState(localDate(before)),
    [to, setTo] = useState(localDate(today)),
    [cloud, setCloud] = useState(20),
    [mode, setMode] = useState(config.demo_enabled ? "synthetic" : "satellite"),
    [error, setError] = useState("");
  const key = useRef(crypto.randomUUID());
  function changed() {
    key.current = crypto.randomUUID();
    setError("");
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (from > to) {
          setError("A data final deve ser igual ou posterior à inicial.");
          return;
        }
        void onSave(
          {
            field_id: field.id,
            date_from: from,
            date_to: to,
            max_cloud: cloud,
            mode,
          },
          key.current,
        );
      }}
      onChange={changed}
    >
      <fieldset disabled={pending}>
        <div className="selected-area">
          <Map size={22} />
          <div>
            <strong>{field.name}</strong>
            <span>
              {field.property_name} · {number(field.area_ha, 2)} ha
            </span>
          </div>
        </div>
        <div className="form-row">
          <label>
            Data inicial
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              max={localDate(today)}
              required
            />
          </label>
          <label>
            Data final
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              min={from}
              max={localDate(today)}
              required
            />
          </label>
        </div>
        <label>
          Limite de nuvens na cena (%)
          <input
            type="number"
            value={cloud}
            onChange={(e) => setCloud(Number(e.target.value))}
            min={0}
            max={100}
            step={1}
            required
          />
        </label>
        <label>
          Tipo de análise
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="satellite">NDVI · imagem de satélite</option>
            {config.demo_enabled && (
              <option value="synthetic">
                NDVI · demonstração com dados sintéticos
              </option>
            )}
          </select>
        </label>
        <div className="info-box">
          <Cloud size={19} />
          Uma solicitação reserva uma análise. Se o processamento falhar, a
          reserva é liberada.
        </div>
        {mode === "synthetic" && (
          <p className="help">
            Dados sintéticos servem para demonstração e não representam a
            vegetação real.
          </p>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <Button type="submit">
          <Leaf size={17} />
          {pending ? "Solicitando…" : "Gerar análise NDVI"}
        </Button>
      </fieldset>
    </form>
  );
}

function MonitoringForm({
  initial,
  pending,
  onSave,
}: {
  initial?: Monitoring;
  pending: boolean;
  onSave: (data: Record<string, unknown>) => void;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const values = new FormData(e.currentTarget);
        onSave({
          enabled: values.get("enabled") === "on",
          crop: values.get("crop"),
          stage: values.get("stage"),
          season_start: values.get("season_start"),
          season_end: values.get("season_end"),
          drop_threshold: Number(values.get("drop_threshold")),
        });
      }}
    >
      <fieldset disabled={pending}>
        <label className="monitor-toggle">
          <input
            type="checkbox"
            name="enabled"
            defaultChecked={initial?.enabled ?? true}
          />{" "}
          Ativar acompanhamento semanal
        </label>
        <label>
          Cultura
          <input
            name="crop"
            required
            maxLength={80}
            placeholder="Ex.: Soja"
            defaultValue={initial?.crop}
          />
        </label>
        <label>
          Fase atual da cultura
          <select name="stage" defaultValue={initial?.stage ?? "vegetative"}>
            <option value="vegetative">Desenvolvimento vegetativo</option>
            <option value="reproductive">Fase reprodutiva</option>
            <option value="maturation">Maturação</option>
            <option value="harvest">Colheita</option>
          </select>
        </label>
        <p className="help">
          Atualize a fase conforme a safra avança. Na maturação e na colheita,
          os mapas continuam sendo gerados e os alertas de queda ficam
          suspensos.
        </p>
        <label>
          Início da safra
          <input
            name="season_start"
            type="date"
            required
            defaultValue={initial?.season_start ?? localDate(new Date())}
          />
        </label>
        <label>
          Fim da safra
          <input
            name="season_end"
            type="date"
            required
            defaultValue={
              initial?.season_end ??
              localDate(new Date(Date.now() + 180 * 86400000))
            }
          />
        </label>
        <label>
          Queda mínima de NDVI para alertar
          <input
            name="drop_threshold"
            type="number"
            required
            min="0.05"
            max="1"
            step="0.01"
            defaultValue={initial?.drop_threshold ?? 0.15}
          />
        </label>
        <p className="help">
          Cada análise concluída usa 1 crédito da sua franquia. Sem saldo, o
          acompanhamento aguarda reposição. A disponibilidade depende de imagens
          utilizáveis.
        </p>
        <p className="help">
          Alertas comparam imagens com pelo menos 90% de cobertura válida, na
          mesma safra e geometria. Uma queda indica um ponto de atenção para
          conferir em campo; pode refletir o ciclo da cultura. Ao salvar, a
          comparação começa uma nova sequência.
        </p>
        <Button type="submit">
          {pending ? "Salvando…" : "Salvar acompanhamento"}
        </Button>
      </fieldset>
    </form>
  );
}

export default function App() {
  const [config, setConfig] = useState<Config>({
    registration_enabled: false,
    demo_enabled: false,
  });
  const [user, setUser] = useState<User | null>(null),
    [properties, setProperties] = useState<Property[]>([]),
    [fields, setFields] = useState<Field[]>([]),
    [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [monitoring, setMonitoring] = useState<Monitoring[]>([]);
  const [alerts, setAlerts] = useState<MonitoringAlert[]>([]);
  const [booting, setBooting] = useState(true),
    [loading, setLoading] = useState(false),
    [pending, setPending] = useState(false),
    [registering, setRegistering] = useState(false);
  const [view, setView] = useState<View>("overview"),
    [modal, setModal] = useState<Modal | null>(null),
    [mobile, setMobile] = useState(false),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all");
  const [notice, setNotice] = useState<{
      message: string;
      error: boolean;
    } | null>(null),
    [refreshError, setRefreshError] = useState("");
  const [operationError, setOperationError] = useState("");
  const [compact, setCompact] = useState(
    () => window.matchMedia("(max-width: 640px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(max-width: 640px)");
    const changed = () => setCompact(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    setOperationError("");
  }, [modal, registering]);
  const refreshFlight = useRef<Promise<void> | null>(null),
    pendingRef = useRef(false);
  const notify = useCallback(
    (message: string, error = false) => setNotice({ message, error }),
    [],
  );
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(null), 8000);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  const reset = useCallback(() => {
    setUser(null);
    setProperties([]);
    setFields([]);
    setAnalyses([]);
    setMonitoring([]);
    setAlerts([]);
    setModal(null);
    setRefreshError("");
    setSearch("");
    setFilter("all");
    setView("overview");
  }, []);
  useEffect(() => {
    const expired = () => {
      reset();
      notify("Sua sessão expirou. Entre novamente.", true);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, [reset, notify]);
  const refresh = useCallback(() => {
    if (refreshFlight.current) return refreshFlight.current;
    const epoch = sessionEpoch();
    setLoading(true);
    const task = (async () => {
      try {
        const me = await api<User>("/api/me");
        if (epoch !== sessionEpoch()) return;
        setSession(me.csrf_token);
        const [p, f, a, m, alerts] = await Promise.all([
          api<Property[]>("/api/properties"),
          api<Field[]>("/api/fields"),
          api<Analysis[]>("/api/analyses"),
          api<Monitoring[]>("/api/monitoring"),
          api<MonitoringAlert[]>("/api/alerts"),
        ]);
        if (epoch !== sessionEpoch()) return;
        setUser(me);
        setProperties(p);
        setFields(f);
        setAnalyses(a);
        setMonitoring(m);
        setAlerts(alerts);
        setRefreshError("");
      } finally {
        setLoading(false);
        refreshFlight.current = null;
      }
    })();
    refreshFlight.current = task;
    return task;
  }, []);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const settings = await api<Config>("/api/config");
        if (active) setConfig(settings);
        await refresh();
      } catch (e) {
        if (
          active &&
          !String(e).includes("sessão") &&
          !String(e).includes("sessão foi alterada")
        )
          notify(
            e instanceof Error ? e.message : "Não foi possível conectar.",
            true,
          );
      } finally {
        if (active) setBooting(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [refresh, notify]);
  useEffect(() => {
    if (
      user &&
      (monitoring.some((m) => m.enabled) ||
        analyses.some((a) => a.status === "queued" || a.status === "running"))
    ) {
      const timer = setInterval(() => {
        void refresh().catch((e) => setRefreshError(e.message));
      }, 5000);
      return () => clearInterval(timer);
    }
  }, [user, analyses, monitoring, refresh]);
  async function run(task: () => Promise<void>) {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setOperationError("");
    try {
      await task();
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Não foi possível concluir.";
      if (modal || !user) setOperationError(message);
      else notify(message, true);
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }
  async function updateAfterSave(message: string) {
    setModal(null);
    notify(message);
    await refresh().catch((e) =>
      setRefreshError(
        `Alteração salva. Não foi possível atualizar a lista: ${e.message}`,
      ),
    );
  }
  function navigate(next: View) {
    setView(next);
    setSearch("");
    setFilter("all");
    setMobile(false);
    document.title = `Delta Mapas · ${next === "overview" ? "Visão geral" : pages[next][0]}`;
  }
  function openField(field?: Field, property?: string) {
    if (!properties.length) {
      navigate("properties");
      setModal({ kind: "property" });
      notify("Comece cadastrando a propriedade do seu talhão.");
    } else setModal({ kind: "field", field, property });
  }
  const term = search.trim().toLocaleLowerCase("pt-BR");
  const visibleFields = fields.filter((f) =>
    `${f.name} ${f.property_name}`.toLocaleLowerCase("pt-BR").includes(term),
  );
  const visibleProperties = properties.filter((p) =>
    p.name.toLocaleLowerCase("pt-BR").includes(term),
  );
  const visibleAnalyses = analyses.filter(
    (a) =>
      a.field_name.toLocaleLowerCase("pt-BR").includes(term) &&
      (filter === "all" || a.status === filter),
  );
  const totalArea = fields.reduce((sum, f) => sum + f.area_ha, 0),
    completed = analyses.filter((a) => a.status === "completed").length;
  const inProgress = analyses.filter(
    (a) => a.status === "running" || a.status === "queued",
  ).length;
  function FieldCard({ field }: { field: Field }) {
    const monitor = monitoring.find((m) => m.field_id === field.id);
    return (
      <article className="field-card">
        <FieldPreview geometry={field.geometry} />
        <div className="field-card-content">
          <span className="eyebrow">{field.property_name}</span>
          <div className="field-card-title">
            <h3>{field.name}</h3>
            <span>
              {number(field.area_ha, 2)} <small>ha</small>
            </span>
          </div>
          <div className="monitor-summary">
            <button
              disabled={pending}
              className="text-link"
              onClick={() => setModal({ kind: "monitoring", field })}
            >
              {monitor?.enabled
                ? "Configurar acompanhamento"
                : "Ativar acompanhamento"}
            </button>
            {monitor && (
              <p>
                {!monitor.enabled
                  ? monitor.state === "season_finished"
                    ? "Safra encerrada"
                    : "Acompanhamento pausado"
                  : monitor.state === "quota_exhausted"
                    ? "Aguardando créditos"
                    : monitor.state === "waiting_season"
                      ? "Aguardando início da safra"
                      : monitor.stage === "maturation" ||
                          monitor.stage === "harvest"
                        ? "Acompanhamento ativo · alertas suspensos nesta fase"
                        : monitor.state === "insufficient_quality"
                          ? "Imagem sem qualidade suficiente para comparar"
                          : monitor.state === "failed"
                            ? "Última análise falhou; crédito liberado"
                            : monitor.state === "attention"
                              ? "Queda detectada · confira os alertas"
                              : `${monitor.crop} · próxima verificação ${new Date(monitor.next_run).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}`}
              </p>
            )}
          </div>
          <div className="field-card-actions">
            <button onClick={() => setModal({ kind: "analysis", field })}>
              <Leaf size={16} />
              Analisar talhão
              <ArrowUpRight size={16} />
            </button>
            <button className="edit-button" onClick={() => openField(field)}>
              Editar
            </button>
          </div>
        </div>
      </article>
    );
  }
  function AnalysisList({ items }: { items: Analysis[] }) {
    return (
      <div className="analysis-list">
        <div className="table-heading">
          <span>Talhão / período</span>
          <span>Fonte</span>
          <span>Status</span>
          <span>Resultado</span>
        </div>
        {items.map((a) => (
          <article className="analysis-row" key={a.id}>
            <div className="analysis-title">
              <span className="row-icon">
                <Leaf size={18} />
              </span>
              <div>
                <h3>{a.field_name}</h3>
                <p>
                  {day(a.date_from)} — {day(a.date_to)}
                </p>
                {a.error && <p className="row-error">{a.error}</p>}
              </div>
            </div>
            <span
              className={`source-label ${a.mode === "synthetic" ? "synthetic" : ""}`}
            >
              {a.mode === "synthetic"
                ? "Dados sintéticos"
                : a.origin === "automatic"
                  ? "Automático · NDVI"
                  : "Satélite · NDVI"}
            </span>
            <Status status={a.status} />
            {a.status === "completed" ? (
              <button
                className="result-button"
                onClick={() => setModal({ kind: "result", analysis: a })}
              >
                Ver resultado
                <ArrowUpRight size={16} />
              </button>
            ) : (
              <span className="result-pending">
                {a.status === "failed" ? "Indisponível" : "Aguardando"}
              </span>
            )}
          </article>
        ))}
      </div>
    );
  }
  const toast = notice && (
    <div
      className={`toast ${notice.error ? "error" : ""}`}
      role={notice.error ? "alert" : "status"}
    >
      {notice.error ? <CircleAlert size={19} /> : <Check size={19} />}
      <span>{notice.message}</span>
      <button aria-label="Dispensar mensagem" onClick={() => setNotice(null)}>
        <X size={16} />
      </button>
    </div>
  );
  if (booting)
    return (
      <main className="boot">
        <Brand />
        <LoaderCircle className="spin" />
        <p>Preparando seu espaço de trabalho…</p>
      </main>
    );
  if (!user)
    return (
      <>
        <main className="auth-shell">
          <section className="auth-intro">
            <Brand />
            <div className="auth-story">
              <span className="eyebrow">INTELIGÊNCIA PARA SUA ÁREA</span>
              <h1>
                Um novo olhar
                <br />
                sobre o seu campo.
              </h1>
              <p>
                Transforme imagens de satélite em uma visão mais clara de cada
                talhão.
              </p>
              <div className="terrain-art" aria-hidden="true">
                <svg viewBox="0 0 600 270">
                  <path d="M25 130 190 20 565 95 410 235Z" />
                  <path d="M65 128 200 45 520 106 400 208Z" />
                  <path d="M112 128 218 74 461 116 388 174Z" />
                  <path d="M165 128 230 99 400 124 375 148Z" />
                  <path
                    className="terrain-lines"
                    d="M140 55 360 249 M210 10 440 220 M285 30 500 163 M350 45 550 130"
                  />
                </svg>
                <span className="terrain-label">
                  <Sprout size={16} />
                  Seu campo, em perspectiva
                </span>
              </div>
            </div>
            <div className="auth-trust">
              <ShieldCheck size={17} />
              Suas áreas e análises ficam privadas na sua conta.
            </div>
          </section>
          <section className="auth-panel">
            <div className="auth-card">
              <span className="eyebrow">SEU ESPAÇO DE TRABALHO</span>
              <h2>
                {registering ? "Comece pelo seu campo." : "Bem-vindo de volta."}
              </h2>
              <p>
                {registering
                  ? "Crie sua conta no Delta Mapas."
                  : "Entre para acompanhar suas propriedades e análises."}
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const data = Object.fromEntries(
                    new FormData(e.currentTarget),
                  );
                  void run(async () => {
                    const result = await api<User>(
                      registering ? "/api/register" : "/api/login",
                      { method: "POST", body: JSON.stringify(data) },
                    );
                    clearSession();
                    setSession(result.csrf_token);
                    await refreshFlight.current?.catch(() => {});
                    await refresh();
                  });
                }}
              >
                <fieldset disabled={pending}>
                  <label>
                    E-mail
                    <input
                      name="email"
                      type="email"
                      autoComplete="username"
                      placeholder="voce@empresa.com.br"
                      required
                      maxLength={254}
                    />
                  </label>
                  <label>
                    Senha
                    <input
                      name="password"
                      type="password"
                      autoComplete={
                        registering ? "new-password" : "current-password"
                      }
                      placeholder="Sua senha"
                      minLength={registering ? 12 : 1}
                      maxLength={128}
                      required
                    />
                  </label>
                  {registering && (
                    <p className="help">Use pelo menos 12 caracteres.</p>
                  )}
                  {operationError && (
                    <p className="form-error" role="alert">
                      {operationError}
                    </p>
                  )}
                  <Button type="submit">
                    {pending
                      ? "Conectando…"
                      : registering
                        ? "Criar conta"
                        : "Entrar na plataforma"}
                    <ArrowRight size={18} />
                  </Button>
                </fieldset>
              </form>
              {config.registration_enabled && (
                <p className="auth-switch">
                  {registering
                    ? "Já tem uma conta?"
                    : "Ainda não tem uma conta?"}{" "}
                  <button
                    disabled={pending}
                    onClick={() => setRegistering(!registering)}
                  >
                    {registering ? "Entrar" : "Criar conta"}
                  </button>
                </p>
              )}
              <div className="auth-footer">
                <ShieldCheck size={16} />
                Acesso seguro ao seu ambiente
              </div>
            </div>
            <span className="auth-copyright">
              DELTA MAPAS · INTELIGÊNCIA GEOSPACIAL
            </span>
          </section>
        </main>
        {toast}
      </>
    );
  return (
    <>
      <a href="#main-content" className="skip-link">
        Ir para o conteúdo
      </a>
      <div className="app-shell">
        <aside
          className={`sidebar ${mobile ? "is-open" : ""}`}
          inert={compact && !mobile}
        >
          <a href="/" className="brand-link" aria-label="Delta Mapas — início">
            <Brand />
          </a>
          <div className="workspace-label">
            <span className="workspace-dot" />
            ESPAÇO DE TRABALHO
          </div>
          <nav aria-label="Navegação principal">
            {navigation.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                className={`nav-item ${view === id ? "active" : ""}`}
                aria-current={view === id ? "page" : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={19} />
                <span>{label}</span>
                {id === "fields" && <small>{fields.length}</small>}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="usage-card">
              <div>
                <Leaf size={17} />
                <strong>Suas análises</strong>
              </div>
              <p>
                <b>{number(user.usage.available)}</b> disponíveis
              </p>
              <progress
                max={Math.max(user.usage.limit, 1)}
                value={user.usage.used + user.usage.reserved}
                aria-label="Análises utilizadas e reservadas"
              />
              <span>
                {number(user.usage.used)} utilizadas ·{" "}
                {number(user.usage.reserved)} reservadas
              </span>
            </div>
            <div className="account">
              <span className="avatar">
                {user.email.charAt(0).toUpperCase()}
              </span>
              <div>
                <strong>Minha conta</strong>
                <span title={user.email}>{user.email}</span>
              </div>
              <button
                className="icon-button"
                aria-label="Sair da conta"
                disabled={pending}
                onClick={() =>
                  void run(async () => {
                    await api("/api/logout", { method: "POST" });
                    clearSession();
                    reset();
                  })
                }
              >
                <LogOut size={18} />
              </button>
            </div>
          </div>
        </aside>
        {mobile && (
          <button
            className="mobile-backdrop"
            aria-label="Fechar menu"
            onClick={() => setMobile(false)}
          />
        )}
        <div className="main-shell">
          <header className="topbar">
            <div>
              <button
                className="icon-button mobile-toggle"
                aria-label="Abrir menu"
                aria-expanded={mobile}
                onClick={() => setMobile(!mobile)}
              >
                <Menu size={21} />
              </button>
              <span className="breadcrumb">
                Espaço de trabalho
                <ChevronRight size={14} />
                <b>{navigation.find((n) => n.id === view)?.label}</b>
              </span>
            </div>
            <div className="topbar-end">
              <span className="private-label">
                <ShieldCheck size={14} />
                Ambiente privado
              </span>
              <span className="topbar-avatar">
                {user.email.charAt(0).toUpperCase()}
              </span>
            </div>
          </header>
          <main id="main-content" tabIndex={-1} className="content">
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {view === "overview" ? "VISÃO GERAL" : "ESPAÇO DE TRABALHO"}
                </span>
                <h1>{pages[view][0]}</h1>
                <p>{pages[view][1]}</p>
              </div>
              <div className="page-actions">
                <Button
                  secondary
                  disabled={loading}
                  onClick={() =>
                    void refresh().catch((e) => setRefreshError(e.message))
                  }
                >
                  <RefreshCw size={16} className={loading ? "spin" : ""} />
                  Atualizar
                </Button>
                {view !== "analyses" && (
                  <Button
                    onClick={() =>
                      view === "properties"
                        ? setModal({ kind: "property" })
                        : openField()
                    }
                  >
                    <Plus size={17} />
                    {view === "properties" ? "Nova propriedade" : "Novo talhão"}
                  </Button>
                )}
              </div>
            </div>
            {config.demo_enabled && (
              <div className="demo-banner">
                <CircleAlert size={17} />
                <span>
                  Ambiente de demonstração. Resultados de teste com dados
                  sintéticos serão identificados.
                </span>
              </div>
            )}
            {refreshError && (
              <div role="alert" className="refresh-error">
                <CircleAlert size={18} />
                <span>{refreshError}</span>
                <button
                  disabled={loading}
                  onClick={() =>
                    void refresh().catch((e) => setRefreshError(e.message))
                  }
                >
                  Tentar novamente
                </button>
              </div>
            )}
            {view === "overview" && (
              <>
                <section className="metrics" aria-label="Resumo da conta">
                  {[
                    {
                      label: "Propriedades",
                      value: number(properties.length),
                      detail: "Na sua conta",
                      icon: FolderOpen,
                    },
                    {
                      label: "Talhões cadastrados",
                      value: number(fields.length),
                      detail: `${number(totalArea, 2)} hectares cadastrados`,
                      icon: Map,
                    },
                    {
                      label: "Análises concluídas",
                      value: number(completed),
                      detail: inProgress
                        ? `${inProgress} em processamento`
                        : "Resultados no histórico",
                      icon: Leaf,
                    },
                    {
                      label: "Análises disponíveis",
                      value: number(user.usage.available),
                      detail: `${number(user.usage.used)} utilizadas`,
                      icon: Sprout,
                    },
                  ].map(({ label, value, detail, icon: Icon }) => (
                    <article key={label} className="metric">
                      <div>
                        <span>{label}</span>
                        <Icon size={19} />
                      </div>
                      <strong>{value}</strong>
                      <p>{detail}</p>
                    </article>
                  ))}
                </section>
                <section className="overview-grid">
                  <div className="panel fields-panel">
                    <div className="section-heading">
                      <div>
                        <h2>Seus talhões</h2>
                        <p>Uma visão das áreas cadastradas.</p>
                      </div>
                      <button
                        className="text-link"
                        onClick={() => navigate("fields")}
                      >
                        Ver todos
                        <ArrowRight size={16} />
                      </button>
                    </div>
                    {fields.length ? (
                      <div className="overview-fields">
                        {fields.slice(0, 2).map((field) => (
                          <FieldCard key={field.id} field={field} />
                        ))}
                      </div>
                    ) : (
                      <Empty
                        title="Seu primeiro talhão começa aqui"
                        description="Cadastre uma propriedade e importe a área que deseja acompanhar."
                        action="Cadastrar talhão"
                        onAction={() => openField()}
                      />
                    )}
                  </div>
                  <aside className="insight-panel">
                    <span className="insight-icon">
                      <Sprout size={25} />
                    </span>
                    <span className="eyebrow">DO CAMPO À INFORMAÇÃO</span>
                    <h2>
                      Entenda a vegetação
                      <br />
                      de cada área.
                    </h2>
                    <p>
                      Escolha um talhão e um período para gerar seu mapa NDVI.
                      Acompanhe o processamento e consulte os resultados aqui.
                    </p>
                    <div className="insight-steps">
                      <span>
                        <b>01</b>Cadastre sua área
                      </span>
                      <span>
                        <b>02</b>Escolha o período
                      </span>
                      <span>
                        <b>03</b>Explore o resultado
                      </span>
                    </div>
                    <button
                      onClick={() =>
                        fields.length ? navigate("fields") : openField()
                      }
                    >
                      Começar uma análise
                      <ArrowUpRight size={18} />
                    </button>
                  </aside>
                </section>
                <section className="panel history-panel">
                  <div className="section-heading">
                    <div>
                      <h2>Análises recentes</h2>
                      <p>As últimas solicitações da sua conta.</p>
                    </div>
                    <button
                      className="text-link"
                      onClick={() => navigate("analyses")}
                    >
                      Ver histórico
                      <ArrowRight size={16} />
                    </button>
                  </div>
                  {analyses.length ? (
                    <AnalysisList items={analyses.slice(0, 4)} />
                  ) : (
                    <Empty
                      icon="analysis"
                      title="Seu histórico começa com uma análise"
                      description="Os resultados aparecerão aqui depois que você analisar um talhão."
                      action="Escolher talhão"
                      onAction={() =>
                        fields.length ? navigate("fields") : openField()
                      }
                    />
                  )}
                </section>
              </>
            )}
            {view !== "overview" && (
              <>
                <div className="list-toolbar">
                  <label className="search-box">
                    <Search size={18} />
                    <input
                      aria-label={`Buscar ${view === "fields" ? "talhões" : view === "properties" ? "propriedades" : "análises"}`}
                      placeholder={`Buscar ${view === "fields" ? "talhão ou propriedade" : view === "properties" ? "propriedade" : "análise por talhão"}…`}
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </label>
                  {view === "analyses" ? (
                    <select
                      aria-label="Filtrar por status"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    >
                      <option value="all">Todos os status</option>
                      {Object.entries(labels).map(([id, label]) => (
                        <option key={id} value={id}>
                          {label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="list-count">
                      {view === "fields"
                        ? `${visibleFields.length} talhões · ${number(totalArea, 2)} ha no total`
                        : `${visibleProperties.length} propriedades`}
                    </span>
                  )}
                </div>
                {view === "fields" &&
                  (visibleFields.length ? (
                    <div className="field-grid">
                      {visibleFields.map((field) => (
                        <FieldCard key={field.id} field={field} />
                      ))}
                    </div>
                  ) : (
                    <div className="panel">
                      <Empty
                        icon={term ? "search" : "field"}
                        title={
                          term
                            ? "Nenhum talhão encontrado"
                            : "Cadastre seu primeiro talhão"
                        }
                        description={
                          term
                            ? "Tente buscar por outro nome de talhão ou propriedade."
                            : "Importe um ZIP do CAR ou GeoJSON para começar."
                        }
                        action={term ? undefined : "Cadastrar talhão"}
                        onAction={() => openField()}
                      />
                    </div>
                  ))}
                {view === "properties" &&
                  (visibleProperties.length ? (
                    <div className="property-grid">
                      {visibleProperties.map((p) => {
                        const areas = fields.filter(
                          (f) => f.property_id === p.id,
                        );
                        return (
                          <article className="property-card" key={p.id}>
                            <span className="property-icon">
                              <FolderOpen size={24} />
                            </span>
                            <span className="eyebrow">PROPRIEDADE</span>
                            <h2>{p.name}</h2>
                            <div className="property-stats">
                              <span>
                                <strong>{areas.length}</strong> talhões
                              </span>
                              <span>
                                <strong>
                                  {number(
                                    areas.reduce((s, f) => s + f.area_ha, 0),
                                    2,
                                  )}
                                </strong>{" "}
                                ha
                              </span>
                            </div>
                            <button onClick={() => openField(undefined, p.id)}>
                              Adicionar talhão
                              <Plus size={17} />
                            </button>
                          </article>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="panel">
                      <Empty
                        icon={term ? "search" : "property"}
                        title={
                          term
                            ? "Nenhuma propriedade encontrada"
                            : "Um lugar para organizar suas áreas"
                        }
                        description={
                          term
                            ? "Tente buscar por outro nome."
                            : "Cadastre uma propriedade para reunir seus talhões."
                        }
                        action={term ? undefined : "Cadastrar propriedade"}
                        onAction={() => setModal({ kind: "property" })}
                      />
                    </div>
                  ))}
                {view === "analyses" && (
                  <section className="panel">
                    <div className="section-heading">
                      <div>
                        <h2>Histórico de análises</h2>
                        <p>
                          {inProgress
                            ? "Atualizado automaticamente durante o processamento."
                            : "Consulte os resultados e exporte seus mapas."}
                        </p>
                      </div>
                      <span className="list-count">
                        {visibleAnalyses.length} análises
                      </span>
                    </div>
                    {visibleAnalyses.length ? (
                      <AnalysisList items={visibleAnalyses} />
                    ) : (
                      <Empty
                        icon={term || filter !== "all" ? "search" : "analysis"}
                        title={
                          term || filter !== "all"
                            ? "Nenhuma análise encontrada"
                            : "Seu primeiro mapa está a um passo"
                        }
                        description={
                          term || filter !== "all"
                            ? "Ajuste a busca ou o filtro de status."
                            : "Escolha um talhão e solicite uma análise de vegetação."
                        }
                        action={
                          term || filter !== "all"
                            ? undefined
                            : "Escolher talhão"
                        }
                        onAction={() =>
                          fields.length ? navigate("fields") : openField()
                        }
                      />
                    )}
                  </section>
                )}
              </>
            )}
            <section
              className="panel monitoring-alerts"
              aria-label="Alertas de acompanhamento"
            >
              <div className="section-heading">
                <div>
                  <h2>Alertas de acompanhamento</h2>
                  <p>Quedas de vegetação para conferir em campo.</p>
                </div>
              </div>
              {alerts.length === 0 ? (
                <p className="help">
                  Nenhum alerta. Ative o acompanhamento nos talhões para
                  comparar novas observações.
                </p>
              ) : (
                alerts.map((alert) => (
                  <article className="monitor-alert" key={alert.id}>
                    <div>
                      <strong>{alert.field_name}</strong>
                      <p>
                        NDVI {number(alert.previous_mean, 3)} →{" "}
                        {number(alert.current_mean, 3)} ·{" "}
                        {day(alert.previous_date)} a {day(alert.scene_date)}
                      </p>
                      <p className="help">
                        Confira o mapa e as condições da safra antes de decidir
                        uma intervenção.
                      </p>
                    </div>
                    <div className="field-card-actions">
                      <button
                        disabled={pending}
                        onClick={() =>
                          void run(async () => {
                            const result = await api<Analysis>(
                              `/api/analyses/${alert.analysis_id}`,
                            );
                            setModal({ kind: "result", analysis: result });
                          })
                        }
                      >
                        Ver análise
                      </button>
                      {alert.read_at ? (
                        <span>Conferido</span>
                      ) : (
                        <button
                          disabled={pending}
                          onClick={() =>
                            void run(async () => {
                              await api(`/api/alerts/${alert.id}/read`, {
                                method: "POST",
                              });
                              await refresh();
                            })
                          }
                        >
                          Marcar conferido
                        </button>
                      )}
                    </div>
                  </article>
                ))
              )}
            </section>
            <footer className="page-footer">
              <span>Delta Mapas</span>
              <span>Seu campo, em perspectiva.</span>
            </footer>
          </main>
        </div>
      </div>
      {modal && (
        <Dialog
          key={modal.kind + ("field" in modal ? modal.field?.id || "" : "")}
          title={
            modal.kind === "property"
              ? "Nova propriedade"
              : modal.kind === "field"
                ? modal.field
                  ? "Editar talhão"
                  : "Novo talhão"
                : modal.kind === "analysis"
                  ? "Solicitar análise"
                  : modal.kind === "monitoring"
                    ? `Acompanhamento · ${modal.field.name}`
                    : `${modal.analysis.field_name} · NDVI`
          }
          subtitle={
            modal.kind === "property"
              ? "Organize os talhões da sua propriedade."
              : modal.kind === "field"
                ? "Identifique a área e importe seu limite geográfico."
                : undefined
          }
          locked={pending}
          onClose={() => setModal(null)}
        >
          {operationError && (
            <p className="form-error" role="alert">
              {operationError}
            </p>
          )}
          {modal.kind === "property" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = Object.fromEntries(new FormData(e.currentTarget));
                void run(async () => {
                  await api("/api/properties", {
                    method: "POST",
                    body: JSON.stringify(data),
                  });
                  await updateAfterSave(
                    "Propriedade cadastrada. Agora você pode adicionar talhões.",
                  );
                });
              }}
            >
              <fieldset disabled={pending}>
                <label>
                  Nome da propriedade
                  <input
                    name="name"
                    autoFocus
                    placeholder="Ex.: Fazenda Boa Vista"
                    required
                    maxLength={120}
                  />
                </label>
                <p className="help">
                  Use um nome que facilite identificar a propriedade na sua
                  conta.
                </p>
                <Button type="submit">
                  {pending ? "Salvando…" : "Cadastrar propriedade"}
                  <ArrowRight size={17} />
                </Button>
              </fieldset>
            </form>
          )}
          {modal.kind === "field" && (
            <FieldForm
              initial={modal.field}
              property={modal.property}
              properties={properties}
              pending={pending}
              onSave={(data) =>
                run(async () => {
                  await api(
                    modal.field
                      ? `/api/fields/${modal.field.id}`
                      : "/api/fields",
                    {
                      method: modal.field ? "PUT" : "POST",
                      body: JSON.stringify(data),
                    },
                  );
                  await updateAfterSave("Talhão salvo com sucesso.");
                })
              }
            />
          )}
          {modal.kind === "analysis" && (
            <AnalysisForm
              field={modal.field}
              config={config}
              pending={pending}
              onSave={(data, key) =>
                run(async () => {
                  await api("/api/analyses", {
                    method: "POST",
                    body: JSON.stringify(data),
                    headers: { "Idempotency-Key": key },
                  });
                  navigate("analyses");
                  await updateAfterSave(
                    "Análise solicitada. Acompanhe o processamento no histórico.",
                  );
                })
              }
            />
          )}
          {modal.kind === "monitoring" && (
            <MonitoringForm
              initial={monitoring.find((m) => m.field_id === modal.field.id)}
              pending={pending}
              onSave={(data) =>
                void run(async () => {
                  await api(`/api/fields/${modal.field.id}/monitoring`, {
                    method: "PUT",
                    body: JSON.stringify(data),
                  });
                  await updateAfterSave("Acompanhamento atualizado.");
                })
              }
            />
          )}
          {modal.kind === "result" && <Result item={modal.analysis} />}
        </Dialog>
      )}
      {toast}
    </>
  );
}
