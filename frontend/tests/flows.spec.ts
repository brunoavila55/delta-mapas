import { test, expect, type Page } from "@playwright/test";
const geometry = {
  type: "Polygon",
  coordinates: [
    [
      [-47.1, -22.0],
      [-47.09, -22.002],
      [-47.087, -22.009],
      [-47.099, -22.01],
      [-47.104, -22.006],
      [-47.1, -22.0],
    ],
  ],
};
const property = { id: "p1", name: "Fazenda Boa Vista" };
const field = {
  id: "f1",
  name: "Talhão Norte",
  property_id: "p1",
  property_name: property.name,
  area_ha: 128.42,
  geometry,
};
const result = {
  id: "a1",
  field_name: field.name,
  status: "completed",
  mode: "synthetic",
  date_from: "2026-09-01",
  date_to: "2026-09-30",
  statistics: {
    mean: 0.653,
    minimum: 0.12,
    maximum: 0.89,
    valid_percent: 98.2,
  },
};
async function fixture(
  page: Page,
  opts: { guest?: boolean; empty?: boolean; register?: boolean } = {},
) {
  const state = {
    authenticated: !opts.guest,
    properties: opts.empty ? [] : [property],
    fields: opts.empty ? [] : [field],
    analyses: opts.empty ? [] : [result],
    monitoring: [] as any[],
    alerts: [] as any[],
    failAnalysis: false,
    analysisKeys: [] as string[],
    requests: [] as {
      path: string;
      method: string;
      body: any;
      csrf?: string;
    }[],
    meStatus: 200,
    analysisReads: 0,
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname,
      method = request.method();
    const body =
      method !== "GET" && request.headers()["content-type"]?.includes("json")
        ? request.postDataJSON()
        : null;
    state.requests.push({
      path,
      method,
      body,
      csrf: request.headers()["x-csrf-token"],
    });
    let status = 200,
      data: any = {};
    if (path === "/api/config")
      data = {
        registration_enabled: opts.register !== false,
        demo_enabled: true,
      };
    else if (path === "/api/login" || path === "/api/register") {
      state.authenticated = true;
      data = { csrf_token: "token-test" };
    } else if (path === "/api/logout") state.authenticated = false;
    else if (!state.authenticated || state.meStatus === 401) {
      status = 401;
      data = { error: "E-mail, senha ou sessão inválidos" };
    } else if (path === "/api/me") {
      status = state.meStatus;
      data =
        status === 200
          ? {
              email: "gestao@boavista.com.br",
              csrf_token: "token-test",
              usage: { limit: 30, used: 8, reserved: 0, available: 22 },
            }
          : { error: "Serviço temporariamente indisponível" };
    } else if (path === "/api/monitoring") data = state.monitoring;
    else if (path === "/api/alerts") data = state.alerts;
    else if (path === "/api/fields/f1/monitoring" && method === "PUT") {
      state.monitoring = [
        {
          ...body,
          field_id: "f1",
          state: "scheduled",
          next_run: "2026-10-15T12:00:00Z",
        },
      ];
      data = { saved: true };
    } else if (path.endsWith("/read") && method === "POST") {
      state.alerts.forEach((a) => {
        if (path.includes(a.id)) a.read_at = "2026-10-14T12:00:00Z";
      });
      data = { saved: true };
    } else if (path === "/api/analyses/a1") data = result;
    else if (path === "/api/properties") {
      if (method === "POST") {
        state.properties.push({ id: "p2", name: body.name });
        data = { id: "p2" };
      } else data = state.properties;
    } else if (path === "/api/fields") {
      if (method === "POST") {
        const p = state.properties.find((p) => p.id === body.property_id)!;
        state.fields.push({
          ...body,
          id: "f2",
          property_name: p.name,
          area_ha: 98.7,
        });
        data = { id: "f2" };
      } else data = state.fields;
    } else if (path === "/api/fields/f1" && method === "PUT") {
      state.fields[0] = { ...state.fields[0], ...body };
      data = { id: "f1" };
    } else if (path === "/api/imports/car")
      data = {
        geometry,
        area_ha: 128.42,
        warnings: ["Confira o limite da propriedade."],
      };
    else if (path === "/api/analyses") {
      if (method === "POST") {
        state.analysisKeys.push(request.headers()["idempotency-key"]);
        if (state.failAnalysis) {
          status = 503;
          data = { error: "Tente novamente em instantes." };
        } else {
          state.analyses.unshift({
            ...result,
            id: "a2",
            status: "queued",
            ...body,
          });
          data = { id: "a2" };
        }
      } else {
        state.analysisReads++;
        if (state.analysisReads > 2)
          state.analyses.forEach((a) => {
            if (a.id === "a2") a.status = "completed";
          });
        data = state.analyses;
      }
    } else if (path.endsWith("analysis.json"))
      data = { products: ["map.pdf", "report.pdf", "ndvi.png", "ndvi.tif"] };
    else if (path.endsWith("ndvi.png")) {
      await route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
          "base64",
        ),
      });
      return;
    } else if (path.endsWith("analysis.json"))
      data = {
        source: {
          metadata: { tiles: [{ date: "2026-09-12", cloudCoverage: 12 }] },
        },
      };
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
  return state;
}
async function navigate(page: Page, name: string) {
  await expect(page.locator("#main-content")).toBeVisible();
  if (await page.getByRole("button", { name: "Abrir menu" }).isVisible())
    await page.getByRole("button", { name: "Abrir menu" }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name, exact: name !== "Talhões" })
    .click();
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
}

test("visão geral, busca, filtros, exportações e layout", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const violations: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") violations.push(msg.text());
  });
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  await expect(page.getByText("128,42 hectares cadastrados")).toBeVisible();
  await noOverflow(page);
  await page.screenshot({
    path: `test-results/overview-${info.project.name}.png`,
    fullPage: true,
  });
  await navigate(page, "Talhões");
  await page
    .getByRole("textbox", { name: "Buscar talhões" })
    .fill("inexistente");
  await expect(page.getByText("Nenhum talhão encontrado")).toBeVisible();
  await page.getByRole("textbox", { name: "Buscar talhões" }).fill("boa vista");
  await expect(page.getByRole("heading", { name: field.name })).toBeVisible();
  await navigate(page, "Análises");
  await page
    .getByRole("combobox", { name: "Filtrar por status" })
    .selectOption("failed");
  await expect(page.getByText("Nenhuma análise encontrada")).toBeVisible();
  await page
    .getByRole("combobox", { name: "Filtrar por status" })
    .selectOption("all");
  await page.getByRole("button", { name: "Ver resultado" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText("Demonstração · resultado gerado com dados sintéticos."),
  ).toBeVisible();
  for (const [label, file] of [
    ["Mapa cartográfico PDF", "map.pdf"],
    ["Relatório PDF", "report.pdf"],
    ["Mapa PNG", "ndvi.png"],
    ["GeoTIFF", "ndvi.tif"],
    ["Metadados JSON", "analysis.json"],
  ])
    await expect(page.getByRole("link", { name: label })).toHaveAttribute(
      "href",
      "/api/analyses/a1/files/" + file,
    );
  await noOverflow(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(errors).toEqual([]);
  expect(violations).toEqual([]);
});
test("acesso, cadastro e logout", async ({ page }, info) => {
  const state = await fixture(page, { guest: true });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Bem-vindo de volta." }),
  ).toBeVisible();
  await expect(
    page.getByText("Sua sessão expirou. Entre novamente."),
  ).not.toBeVisible();
  await noOverflow(page);
  await page.screenshot({
    path: `test-results/login-${info.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await page.getByRole("textbox", { name: "E-mail" }).fill("nova@empresa.test");
  await page.getByLabel("Senha", { exact: true }).fill("senha-longuissima-123");
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  expect(
    state.requests.find((r) => r.path === "/api/register")?.body.email,
  ).toBe("nova@empresa.test");
  if (await page.getByRole("button", { name: "Abrir menu" }).isVisible())
    await page.getByRole("button", { name: "Abrir menu" }).click();
  await page.getByRole("button", { name: "Sair da conta" }).click();
  await expect(
    page.getByRole("heading", { name: "Comece pelo seu campo." }),
  ).toBeVisible();
  expect(state.requests.find((r) => r.path === "/api/logout")?.csrf).toBe(
    "token-test",
  );
});
test("cadastro de propriedade e talhão com GeoJSON", async ({ page }) => {
  const state = await fixture(page, { empty: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Novo talhão" }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Nova propriedade" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Nome da propriedade" })
    .fill("Fazenda Horizonte");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cadastrar propriedade" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Fazenda Horizonte" }),
  ).toBeVisible();
  await navigate(page, "Talhões");
  await page.getByRole("button", { name: "Novo talhão" }).click();
  await page.getByRole("textbox", { name: "Nome do talhão" }).fill("Área Sul");
  await page.getByLabel("Importar área", { exact: true }).setInputFiles({
    name: "area.geojson",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(geometry)),
  });
  await expect(
    page.getByText("area.geojson · carregado.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Salvar talhão" }).click();
  await expect(page.getByRole("heading", { name: "Área Sul" })).toBeVisible();
  const saved = state.requests.find(
    (r) => r.path === "/api/fields" && r.method === "POST",
  );
  expect(saved?.body.geometry).toEqual(geometry);
  expect(saved?.body.property_id).toBe("p2");
  expect(saved?.csrf).toBe("token-test");
});
test("importação CAR, edição e validação de geometria", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/");
  await navigate(page, "Talhões");
  await page.getByRole("button", { name: "Editar", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Nome do talhão" })
    .fill("Talhão atualizado");
  await page.getByLabel("Geometria da área").fill("json inválido");
  await page.getByRole("button", { name: "Salvar talhão" }).click();
  await expect(
    page.getByText("O GeoJSON informado não é válido."),
  ).toBeVisible();
  await page.getByLabel("Importar área", { exact: true }).setInputFiles({
    name: "imovel.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("test CAR transport"),
  });
  await expect(
    page.getByText("imovel.zip · 128,42 ha.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Salvar talhão" }).click();
  await expect(
    page.getByRole("heading", { name: "Talhão atualizado" }),
  ).toBeVisible();
  expect(
    state.requests.find((r) => r.path === "/api/fields/f1")?.body.geometry,
  ).toEqual(geometry);
});
test("análise mantém idempotência ao repetir e atualiza resultado", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.goto("/");
  await navigate(page, "Talhões");
  await page.getByRole("button", { name: "Analisar talhão" }).click();
  state.failAnalysis = true;
  await page.getByRole("button", { name: "Gerar análise NDVI" }).click();
  await expect(page.getByText("Tente novamente em instantes.")).toBeVisible();
  state.failAnalysis = false;
  await page.getByRole("button", { name: "Gerar análise NDVI" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(state.analysisKeys).toHaveLength(2);
  expect(state.analysisKeys[0]).toBe(state.analysisKeys[1]);
  expect(state.analysisKeys[0]).toBeTruthy();
  const request = state.requests.find(
    (r) => r.path === "/api/analyses" && r.method === "POST",
  );
  expect(request?.csrf).toBe("token-test");
  expect(request?.body.field_id).toBe("f1");
  expect(request?.body.max_cloud).toBe(20);
  await expect(page.locator(".badge.queued")).toBeVisible();
  await expect(page.locator(".badge.queued")).not.toBeVisible({
    timeout: 12000,
  });
  await expect(page.getByRole("button", { name: "Ver resultado" })).toHaveCount(
    2,
  );
});
test("falha ao atualizar preserva tela e sessão expirada limpa dados", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  state.meStatus = 503;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(
    page.getByText("Serviço temporariamente indisponível"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: field.name }).first(),
  ).toBeVisible();
  state.meStatus = 200;
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(
    page.getByText("Serviço temporariamente indisponível"),
  ).not.toBeVisible();
  state.meStatus = 401;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Bem-vindo de volta." }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: field.name }),
  ).not.toBeVisible();
});

test("configura acompanhamento semanal e confere alerta", async ({ page }) => {
  const state = await fixture(page);
  state.alerts.push({
    id: "alert1",
    field_name: field.name,
    analysis_id: "a1",
    previous_mean: 0.8,
    current_mean: 0.6,
    previous_date: "2026-10-01",
    scene_date: "2026-10-08",
    read_at: null,
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Marcar conferido" }).click();
  await expect(page.getByText("Conferido", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ver análise", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: /Fechar/ }).click();
  await navigate(page, "Talhões");
  await page
    .getByRole("button", { name: "Ativar acompanhamento", exact: true })
    .first()
    .click();
  await page.getByLabel("Cultura", { exact: true }).fill("Soja");
  await page.getByLabel("Início da safra").fill("2026-10-01");
  await page.getByLabel("Fim da safra").fill("2027-03-01");
  await page.getByRole("button", { name: "Salvar acompanhamento" }).click();
  await expect(
    page.getByRole("button", { name: "Configurar acompanhamento" }).first(),
  ).toBeVisible();
  const saved = state.requests.find(
    (r) => r.path.endsWith("/monitoring") && r.method === "PUT",
  )!;
  expect(saved.body).toMatchObject({
    enabled: true,
    crop: "Soja",
    drop_threshold: 0.15,
  });
  expect(saved.csrf).toBe("token-test");
  await page
    .getByRole("button", { name: "Configurar acompanhamento" })
    .first()
    .click();
  await page.getByLabel("Ativar acompanhamento semanal").uncheck();
  await page.getByRole("button", { name: "Salvar acompanhamento" }).click();
  await expect(page.getByText("Acompanhamento pausado").first()).toBeVisible();
  await noOverflow(page);
  await page.screenshot({
    path: `test-results/monitoring-${test.info().project.name}.png`,
    fullPage: true,
  });
});
