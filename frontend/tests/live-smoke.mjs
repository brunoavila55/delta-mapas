// Optional end-to-end smoke test against an isolated, running Delta environment.
import { chromium, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const base = process.env.DELTA_UI_URL;
if (!base)
  throw new Error("Configure DELTA_UI_URL para um ambiente isolado de teste.");
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const email = `ui-${randomUUID()}@delta.example.test`,
  password = randomUUID() + "-Delta";
try {
  await page.goto(base);
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await page.getByRole("textbox", { name: "E-mail" }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Propriedades", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Nova propriedade", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Nome da propriedade" })
    .fill("Fazenda Boa Vista");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cadastrar propriedade" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Fazenda Boa Vista" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Adicionar talhão" }).click();
  await page
    .getByRole("textbox", { name: "Nome do talhão" })
    .fill("Talhão Norte");
  await page
    .getByLabel("Importar área", { exact: true })
    .setInputFiles(
      fileURLToPath(new URL("../../examples/talhao.geojson", import.meta.url)),
    );
  await expect(
    page.getByText("talhao.geojson · carregado.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Salvar talhão" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Talhões" })
    .click();
  await page.getByRole("button", { name: "Editar", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Nome do talhão" })
    .fill("Talhão Norte · Safra");
  await page.getByRole("button", { name: "Salvar talhão" }).click();
  await expect(
    page.getByRole("heading", { name: "Talhão Norte · Safra" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Analisar talhão" }).click();
  await page.getByLabel("Tipo de análise").selectOption("synthetic");
  await page.getByRole("button", { name: "Gerar análise NDVI" }).click();
  await expect(page.getByRole("button", { name: "Ver resultado" })).toBeVisible(
    { timeout: 60000 },
  );
  await page.getByRole("button", { name: "Ver resultado" }).click();
  const image = page.getByRole("img", {
    name: "Mapa de NDVI de Talhão Norte · Safra",
  });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((img) => img.naturalWidth))
    .toBeGreaterThan(1);
  for (const [label, filename] of [
    ["Relatório PDF", "report.pdf"],
    ["Mapa PNG", "ndvi.png"],
    ["GeoTIFF", "ndvi.tif"],
    ["Metadados JSON", "analysis.json"],
  ]) {
    const downloaded = page.waitForEvent("download");
    await page.getByRole("link", { name: label }).click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe(filename);
    expect(await download.failure()).toBeNull();
    const stream = await download.createReadStream();
    let bytes = 0;
    for await (const chunk of stream) bytes += chunk.length;
    expect(bytes).toBeGreaterThan(20);
  }
  await mkdir(new URL("../test-results/", import.meta.url), {
    recursive: true,
  });
  await page.screenshot({
    path: fileURLToPath(
      new URL("../test-results/live-result.png", import.meta.url),
    ),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Fechar", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  await page.screenshot({
    path: fileURLToPath(
      new URL("../test-results/live-overview.png", import.meta.url),
    ),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sair da conta" }).click();
  await expect(
    page.getByRole("heading", { name: "Bem-vindo de volta." }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "E-mail" }).fill(email);
  await page.getByLabel("Senha", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar na plataforma" }).click();
  await expect(
    page.getByRole("heading", { name: "Seu campo, em perspectiva." }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  console.log(
    "PASS: cadastro, sessão, propriedade, importação GeoJSON, edição, NDVI sintético, quatro downloads, reload e login no backend real.",
  );
} finally {
  await browser.close();
}
