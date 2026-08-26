// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { Filters } from "./Filters";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function renderFilters() {
  const container = document.createElement("div");
  document.body.append(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <Filters
        search=""
        onSearch={vi.fn()}
        vendors={["Acme", "OpenAI"]}
        vendorFilter={new Set(["OpenAI"])}
        onToggleVendor={vi.fn()}
        categoryFilter={null}
        onCategory={vi.fn()}
        openWeightsOnly={false}
        onToggleOpenWeights={vi.fn()}
        onClear={vi.fn()}
        resultCount={2}
        hasModelsWithNoPublishedScores
        showModelsWithNoPublishedScores={false}
        onToggleModelsWithNoPublishedScores={vi.fn()}
      />
    );
  });

  return {
    container,
    cleanup() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("Filters accessibility semantics", () => {
  it("provides a durable search label and polite result status", () => {
    const view = renderFilters();
    try {
      const search = view.container.querySelector("#model-search");
      expect(search?.getAttribute("aria-label")).toBeNull();
      expect(view.container.querySelector('label[for="model-search"]')?.textContent).toContain(
        "Search models, vendors, and families"
      );
      const status = view.container.querySelector('[role="status"]');
      expect(status?.getAttribute("aria-live")).toBe("polite");
      expect(status?.textContent).toBe("2 models");
    } finally {
      view.cleanup();
    }
  });

  it("exposes vendor and category filter groups with pressed state", () => {
    const view = renderFilters();
    try {
      expect(view.container.querySelector('[role="group"][aria-label="Vendor filters"]')).toBeTruthy();
      expect(view.container.querySelector('[role="group"][aria-label="Category filters"]')).toBeTruthy();

      const openAi = view.container.querySelector<HTMLButtonElement>(
        '[aria-label="Filter by vendor OpenAI"]'
      );
      const acme = view.container.querySelector<HTMLButtonElement>(
        '[aria-label="Filter by vendor Acme"]'
      );
      expect(openAi?.getAttribute("aria-pressed")).toBe("true");
      expect(acme?.getAttribute("aria-pressed")).toBe("false");
      expect(
        view.container.querySelector('[aria-label="Show all categories"]')?.getAttribute("aria-pressed")
      ).toBe("true");
    } finally {
      view.cleanup();
    }
  });

  it("exposes the zero-score visibility control as an accessible switch", () => {
    const view = renderFilters();
    try {
      const toggle = view.container.querySelector(
        '[aria-label="Show models with no published scores"]'
      );
      expect(toggle?.getAttribute("role")).toBe("switch");
      expect(toggle?.getAttribute("aria-checked")).toBe("false");
    } finally {
      view.cleanup();
    }
  });
});
